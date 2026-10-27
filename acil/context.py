from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from acil.models import (
    ContextRequest,
    FailurePattern,
    GlobalStrategyCandidate,
    StrategyCandidate,
    StrategyVersion,
)


def _matches(
    candidate: StrategyCandidate,
    failure_type: str | None,
    canonical_action: str | None,
    environment_fingerprint: str | None,
) -> tuple[bool, int]:
    conditions = candidate.applicability or {}
    score = 0
    for key, actual in (
        ("error_type", failure_type),
        ("canonical_action", canonical_action),
        ("environment_fingerprint", environment_fingerprint),
    ):
        expected = conditions.get(key)
        if expected is None:
            continue
        if actual is None:
            continue
        if str(expected).lower() != str(actual).lower():
            return False, 0
        score += 3 if key == "error_type" else 2
    return True, score


def render_markdown(package: dict) -> str:
    lines = [
        "# ACIL Execution Context",
        "",
        f"Task type: `{package['task_type']}`",
        f"Project: `{package['project_id']}`",
        "",
        "## Known failures",
    ]
    if package["known_failures"]:
        lines.extend(
            f"- `{failure['error_type']}` during `{failure['canonical_action']}`: {failure['occurrence_count']} occurrence(s)"
            for failure in package["known_failures"]
        )
    else:
        lines.append("- None recorded")
    lines.extend(["", "## Recommended strategies"])
    if package["recommended_strategies"]:
        for strategy in package["recommended_strategies"]:
            lines.append(f"### {strategy['name']} (v{strategy['version']})")
            lines.append(f"- Provenance: failure pattern `{strategy['failure_pattern_id']}`")
            lines.append(f"- Actions: `{' → '.join(strategy['actions'])}`")
    else:
        lines.append("- None applicable")
    return "\n".join(lines)


def compile_context(
    *,
    tenant_id: UUID,
    project_id: UUID,
    task_type: str,
    agent_type: str,
    failure_type: str | None,
    canonical_action: str | None,
    environment_fingerprint: str | None,
    max_strategies: int,
    render_markdown_output: bool,
    db: Session,
) -> dict:
    candidates = list(
        db.scalars(
            select(StrategyCandidate).where(
                StrategyCandidate.tenant_id == tenant_id,
                StrategyCandidate.project_id == project_id,
                StrategyCandidate.status == "ACTIVE",
            )
        )
    )
    ranked = []
    for candidate in candidates:
        version = db.scalar(
            select(StrategyVersion)
            .where(
                StrategyVersion.candidate_id == candidate.id,
                StrategyVersion.validation_status == "ACTIVE",
            )
            .order_by(StrategyVersion.version.desc())
        )
        if version is None:
            continue
        matches, score = _matches(
            candidate, failure_type, canonical_action, environment_fingerprint
        )
        if matches:
            ranked.append((score, candidate, version))
    ranked.sort(key=lambda item: (-item[0], item[1].created_at))
    global_strategies = list(
        db.scalars(
            select(GlobalStrategyCandidate).where(
                GlobalStrategyCandidate.status == "ACTIVE",
                GlobalStrategyCandidate.validation_status == "ACTIVE",
            )
        )
    )
    global_ranked = []
    for strategy in global_strategies:
        conditions = strategy.applicability or {}
        if failure_type and conditions.get("error_type", "").lower() != failure_type.lower():
            continue
        if (
            environment_fingerprint
            and conditions.get("environment_fingerprint")
            and conditions.get("environment_fingerprint").lower() != environment_fingerprint.lower()
        ):
            continue
        global_ranked.append(strategy)
    known_failures = list(
        db.scalars(
            select(FailurePattern)
            .where(
                FailurePattern.tenant_id == tenant_id,
                FailurePattern.project_id == project_id,
            )
            .order_by(FailurePattern.occurrence_count.desc())
        )
    )
    package = {
        "task_type": task_type,
        "project_id": str(project_id),
        "agent_type": agent_type,
        "known_failures": [
            {
                "failure_pattern_id": str(failure.id),
                "error_type": failure.error_type,
                "canonical_action": failure.canonical_action,
                "occurrence_count": failure.occurrence_count,
            }
            for failure in known_failures
            if failure_type is None or failure.error_type.lower() == failure_type.lower()
        ],
        "recommended_strategies": [
            {
                "strategy_id": str(candidate.id),
                "name": candidate.name,
                "version": version.version,
                "actions": version.actions,
                "validation_status": version.validation_status,
                "failure_pattern_id": str(candidate.failure_pattern_id),
                "applicability": candidate.applicability,
            }
            for _, candidate, version in ranked[:max_strategies]
        ]
        + [
            {
                "strategy_id": str(strategy.id),
                "name": strategy.name,
                "version": strategy.version,
                "actions": strategy.actions,
                "validation_status": strategy.validation_status,
                "failure_pattern_id": str(strategy.global_pattern_id),
                "applicability": strategy.applicability,
                "scope": "global",
            }
            for strategy in global_ranked[: max(0, max_strategies - len(ranked[:max_strategies]))]
        ],
    }
    request = ContextRequest(
        tenant_id=tenant_id,
        project_id=project_id,
        task_type=task_type,
        agent_type=agent_type,
        request_conditions={
            "failure_type": failure_type,
            "canonical_action": canonical_action,
            "environment_fingerprint": environment_fingerprint,
        },
        result_summary={
            "strategy_count": len(package["recommended_strategies"]),
            "known_failure_count": len(package["known_failures"]),
        },
        created_at=datetime.now(UTC),
    )
    db.add(request)
    db.flush()
    package["context_request_id"] = str(request.id)
    if render_markdown_output:
        package["markdown"] = render_markdown(package)
    return package
