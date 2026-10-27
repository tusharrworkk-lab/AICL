"""MCP tools for agent-facing ACIL context and execution reporting."""

from uuid import UUID

from mcp.server.fastmcp import FastMCP
from sqlalchemy import select

from acil.auth import authenticate_api_key
from acil.background_judge import (
    create_queued_global_evaluation,
    enqueue_global_evaluation,
    resume_pending_global_evaluations,
)
from acil.config import get_settings
from acil.context import compile_context
from acil.db import SessionLocal
from acil.failures import failure_fingerprint
from acil.judge import redact_evidence
from acil.main import persist_event
from acil.models import (
    FailurePattern,
    GlobalEvaluationDefinition,
    GlobalEvaluationRun,
    GlobalFailurePattern,
    Project,
    StrategyCandidate,
    StrategyVersion,
    Tenant,
)
from acil.risk import evaluate_action_risk as evaluate_action_risk_service
from acil.schemas import EventIn

mcp = FastMCP("ACIL")


def _context(raw_api_key: str | None, db):
    try:
        return authenticate_api_key(raw_api_key or get_settings().api_key, db)
    except ValueError as exc:
        raise ValueError("Unauthorized MCP request") from exc


def _authorized_project(project_id: str, ctx, db) -> UUID:
    project_uuid = UUID(project_id)
    if (
        db.scalar(
            select(Project).where(Project.id == project_uuid, Project.tenant_id == ctx.tenant_id)
        )
        is None
    ):
        raise ValueError("Project not found")
    return project_uuid


@mcp.tool()
def get_execution_context(
    project_id: str,
    task_type: str,
    agent_type: str,
    failure_type: str | None = None,
    canonical_action: str | None = None,
    environment_fingerprint: str | None = None,
    max_strategies: int = 5,
    render_markdown: bool = False,
    api_key: str | None = None,
) -> dict:
    """Retrieve authorized active operational context for an agent task."""
    with SessionLocal() as db:
        ctx = _context(api_key, db)
        project_uuid = _authorized_project(project_id, ctx, db)
        package = compile_context(
            tenant_id=ctx.tenant_id,
            project_id=project_uuid,
            task_type=task_type,
            agent_type=agent_type,
            failure_type=failure_type,
            canonical_action=canonical_action,
            environment_fingerprint=environment_fingerprint,
            max_strategies=max_strategies,
            render_markdown_output=render_markdown,
            db=db,
        )
        db.commit()
        return package


@mcp.tool()
def get_known_failures(project_id: str, api_key: str | None = None) -> list[dict]:
    """Retrieve observed failure patterns for an authorized project."""
    with SessionLocal() as db:
        ctx = _context(api_key, db)
        project_uuid = _authorized_project(project_id, ctx, db)
        failures = db.scalars(
            select(FailurePattern)
            .where(
                FailurePattern.tenant_id == ctx.tenant_id, FailurePattern.project_id == project_uuid
            )
            .order_by(FailurePattern.occurrence_count.desc())
        )
        return [
            {
                "failure_id": str(item.id),
                "fingerprint": item.fingerprint,
                "canonical_action": item.canonical_action,
                "error_type": item.error_type,
                "occurrence_count": item.occurrence_count,
            }
            for item in failures
        ]


@mcp.tool()
def get_validated_strategies(project_id: str, api_key: str | None = None) -> list[dict]:
    """Retrieve validated or active strategies for an authorized project."""
    with SessionLocal() as db:
        ctx = _context(api_key, db)
        project_uuid = _authorized_project(project_id, ctx, db)
        candidates = db.scalars(
            select(StrategyCandidate).where(
                StrategyCandidate.tenant_id == ctx.tenant_id,
                StrategyCandidate.project_id == project_uuid,
                StrategyCandidate.status.in_(["VALIDATED", "ACTIVE"]),
            )
        )
        result = []
        for candidate in candidates:
            version = db.scalar(
                select(StrategyVersion)
                .where(
                    StrategyVersion.candidate_id == candidate.id,
                    StrategyVersion.validation_status.in_(["VALIDATED", "ACTIVE"]),
                )
                .order_by(StrategyVersion.version.desc())
            )
            if version is not None:
                result.append(
                    {
                        "strategy_id": str(candidate.id),
                        "name": candidate.name,
                        "status": candidate.status,
                        "version": version.version,
                        "validation_status": version.validation_status,
                        "actions": version.actions,
                        "applicability": candidate.applicability,
                        "failure_pattern_id": str(candidate.failure_pattern_id),
                    }
                )
        return result


@mcp.tool()
def evaluate_action_risk(
    project_id: str,
    canonical_action: str,
    error_type: str | None = None,
    environment_fingerprint: str | None = None,
    api_url: str | None = None,
    api_key: str | None = None,
) -> dict:
    """Check aggregate failure risk before executing an action.

    REQUIRE_CONFIRMATION means the agent must ask before repeating the action.
    Results never include raw traces or judge reports from other tenants.
    """
    with SessionLocal() as db:
        ctx = _context(api_key, db)
        _authorized_project(project_id, ctx, db)
        return evaluate_action_risk_service(
            tenant_id=ctx.tenant_id,
            canonical_action=canonical_action,
            error_type=error_type,
            environment_fingerprint=environment_fingerprint,
            api_url=api_url,
            db=db,
        )


@mcp.tool()
def report_execution_outcome(event: dict, api_key: str | None = None) -> dict:
    """Report one canonical observed execution event; no commands are executed."""
    with SessionLocal() as db:
        ctx = _context(api_key, db)
        payload = EventIn.model_validate(event)
        _authorized_project(str(payload.project_id), ctx, db)
        persisted = persist_event(payload, ctx, db)
        db.commit()
        db.refresh(persisted)
        return {
            "event_id": persisted.event_id,
            "id": str(persisted.id),
            "tenant_id": str(persisted.tenant_id),
            "project_id": str(persisted.project_id),
            "status": persisted.status,
        }


@mcp.tool()
def report_failure_for_review(
    event: dict,
    failure_summary: str,
    observed_actions: list[str] | None = None,
    request_bedrock_judgment: bool = False,
    api_key: str | None = None,
) -> dict:
    """Persist a Codex-observed failure and optionally submit safe evidence to Bedrock.

    `failure_summary` must be a concise account of observed errors, outputs, and attempted
    recovery—not hidden chain-of-thought, private reasoning, source code, or credentials.
    Bedrock is called only when `request_bedrock_judgment` is true and the tenant has opted
    into global learning. A Bedrock failure never discards the captured execution evidence.
    """
    if len(failure_summary.strip()) < 3:
        raise ValueError("failure_summary must describe an observed failure")
    with SessionLocal() as db:
        ctx = _context(api_key, db)
        payload = EventIn.model_validate(event)
        _authorized_project(str(payload.project_id), ctx, db)
        is_failure = payload.status.lower() in {"failed", "failure", "error"} or (
            payload.event_type.lower().endswith(".failed")
        )
        if not is_failure:
            raise ValueError("report_failure_for_review requires a failed execution event")

        reported_evidence = redact_evidence(
            {
                "failure_summary": failure_summary[:4_000],
                "reported_by": "codex_mcp",
                "observed_actions": (observed_actions or [])[:100],
            }
        )
        attributes = dict(payload.attributes)
        attributes["codex_failure_report"] = reported_evidence
        payload = payload.model_copy(update={"attributes": attributes})
        persisted = persist_event(payload, ctx, db)
        # Evidence must survive a subsequent provider outage or malformed model response.
        db.commit()
        db.refresh(persisted)

        result = {
            "event_id": persisted.event_id,
            "id": str(persisted.id),
            "tenant_id": str(persisted.tenant_id),
            "project_id": str(persisted.project_id),
            "status": persisted.status,
            "canonical_action": persisted.canonical_action,
            "error_type": persisted.error_type,
            "api_target": persisted.attributes.get("api_target"),
            "bedrock_judgment": {"requested": request_bedrock_judgment, "status": "not_requested"},
        }
        if not request_bedrock_judgment:
            return result

        tenant = db.get(Tenant, ctx.tenant_id)
        if tenant is None or not tenant.global_learning_enabled:
            result["bedrock_judgment"] = {
                "requested": True,
                "status": "not_eligible",
                "reason": "Enable tenant global learning before requesting shared-evaluation judgment.",
            }
            return result

        fingerprint = failure_fingerprint(persisted)
        pattern = db.scalar(
            select(GlobalFailurePattern).where(GlobalFailurePattern.fingerprint == fingerprint)
        )
        definition = (
            db.scalar(
                select(GlobalEvaluationDefinition).where(
                    GlobalEvaluationDefinition.global_pattern_id == pattern.id
                )
            )
            if pattern is not None
            else None
        )
        if definition is None:
            result["bedrock_judgment"] = {
                "requested": True,
                "status": "not_eligible",
                "reason": "No global evaluation definition was created for this failure.",
            }
            return result

        run = create_queued_global_evaluation(
            definition=definition,
            tenant_id=ctx.tenant_id,
            observed_actions=observed_actions or [persisted.canonical_action],
            evidence={
                "event_id": persisted.event_id,
                "trace_id": persisted.trace_id,
                "canonical_action": persisted.canonical_action,
                "error_type": persisted.error_type,
                "codex_failure_report": reported_evidence,
            },
            db=db,
        )
        db.commit()
        db.refresh(run)
        enqueue_global_evaluation(run.id)

        result["bedrock_judgment"] = {
            "requested": True,
            "status": "queued",
            "run_id": str(run.id),
            "message": "Bedrock judgment is running asynchronously; Codex does not need to wait.",
        }
        return result


@mcp.tool()
def get_judge_run_status(run_id: str, api_key: str | None = None) -> dict:
    """Get the tenant-private status and final evidence for an asynchronous judge run."""
    with SessionLocal() as db:
        ctx = _context(api_key, db)
        run = db.scalar(
            select(GlobalEvaluationRun).where(
                GlobalEvaluationRun.id == UUID(run_id),
                GlobalEvaluationRun.tenant_id == ctx.tenant_id,
            )
        )
        if run is None:
            raise ValueError("Judge run not found")
        return {
            "run_id": str(run.id),
            "definition_id": str(run.definition_id),
            "judge_provider": run.judge_provider,
            "status": run.status,
            "passed": run.passed if run.status in {"PASSED", "FAILED"} else None,
            "reliability_score": (run.metrics or {}).get("reliability_score"),
            "blockers": run.blockers,
            "negative_case_analysis": (run.metrics or {}).get(
                "negative_case_analysis", []
            ),
            "user_action_requests": (run.metrics or {}).get("user_action_requests", []),
            "created_at": run.created_at.isoformat(),
        }


if __name__ == "__main__":
    resume_pending_global_evaluations()
    mcp.run()
