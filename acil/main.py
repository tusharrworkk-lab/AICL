import logging
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from acil.adapters import AdapterContext, normalize_event
from acil.api_targets import extract_api_target
from acil.auth import TenantContext, hash_api_key, require_tenant
from acil.config import get_settings
from acil.context import compile_context
from acil.db import Base, build_engine, get_db
from acil.evaluations import run_evaluation
from acil.failures import record_failure
from acil.global_evaluations import run_global_evaluation
from acil.global_learning import global_pattern_response
from acil.models import (
    ApiKey,
    EvaluationDefinition,
    ExecutionEvent,
    ExecutionSession,
    FailureOccurrence,
    FailurePattern,
    GlobalEvaluationDefinition,
    GlobalEvaluationRun,
    GlobalFailurePattern,
    GlobalStrategyCandidate,
    Project,
    StrategyCandidate,
    StrategyVersion,
    Tenant,
)
from acil.risk import evaluate_action_risk
from acil.runner import DockerEvaluationRunner
from acil.schemas import (
    ActionRiskRequest,
    ContextCompileRequest,
    EvaluationRead,
    EvaluationRunRead,
    EvaluationRunRequest,
    EventBatch,
    EventIn,
    EventRead,
    FailurePatternRead,
    GlobalEvaluationRunRequest,
    IsolatedEvaluationRunRequest,
    LearningPreferenceRequest,
    NormalizedEventRequest,
    ProjectCreate,
    ProjectRead,
    StrategyRead,
)

logging.basicConfig(level=get_settings().log_level, format="%(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if get_settings().database_url.startswith("sqlite"):
        Base.metadata.create_all(build_engine())
    yield


app = FastAPI(title="ACIL", version="0.1.0", lifespan=lifespan)
app.mount("/console/assets", StaticFiles(directory="acil/static"), name="console-assets")

MAX_ATTRIBUTES_BYTES = 32_000


def redact_attributes(attributes: dict) -> dict:
    secret_words = ("password", "secret", "token", "api_key", "authorization")
    return {
        str(key): "[REDACTED]" if any(word in str(key).lower() for word in secret_words) else value
        for key, value in attributes.items()
    }


def persist_event(payload: EventIn, ctx: TenantContext, db: Session) -> ExecutionEvent:
    project = db.scalar(
        select(Project).where(Project.id == payload.project_id, Project.tenant_id == ctx.tenant_id)
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    existing = db.scalar(
        select(ExecutionEvent).where(
            ExecutionEvent.tenant_id == ctx.tenant_id, ExecutionEvent.event_id == payload.event_id
        )
    )
    if existing is not None:
        return existing
    attributes = redact_attributes(payload.attributes)
    attributes, _ = extract_api_target(attributes)
    if len(str(attributes).encode()) > MAX_ATTRIBUTES_BYTES:
        raise HTTPException(status_code=413, detail="Event attributes exceed payload limit")
    session = db.get(ExecutionSession, payload.session_id)
    if session is None:
        session = ExecutionSession(
            id=payload.session_id,
            tenant_id=ctx.tenant_id,
            project_id=payload.project_id,
            agent_type=payload.agent_type,
        )
        db.add(session)
        db.flush()
    elif session.tenant_id != ctx.tenant_id or session.project_id != payload.project_id:
        raise HTTPException(status_code=404, detail="Session not found")
    event = ExecutionEvent(
        tenant_id=ctx.tenant_id, **payload.model_dump(exclude={"attributes"}), attributes=attributes
    )
    db.add(event)
    db.flush()
    record_failure(event, db)
    return event


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "acil"}


@app.get("/v1/judge/status")
def judge_status(_: TenantContext = Depends(require_tenant)) -> dict:
    """Return non-secret runtime readiness for the authenticated operator."""
    settings = get_settings()
    credential_source = (
        "bedrock_api_key"
        if settings.bedrock_auth_mode.lower() == "api_key"
        else "aws_profile"
        if settings.aws_profile
        else "default_aws_credential_chain"
    )
    return {
        "provider": "amazon_bedrock",
        "auth_mode": settings.bedrock_auth_mode,
        "model": settings.bedrock_model,
        "region": settings.bedrock_region,
        "max_output_tokens": settings.bedrock_max_output_tokens,
        "credential_source": credential_source,
        "ready": True,
        "live_verification": "not_run",
        "isolated_runner_enabled": settings.evaluation_runner_enabled,
        "evaluation_image_configured": bool(settings.evaluation_docker_image),
    }


@app.get("/", include_in_schema=False)
@app.get("/console", include_in_schema=False)
def console() -> FileResponse:
    """Serve the local operator console from the same origin as the API."""
    return FileResponse("acil/static/index.html")


@app.post("/v1/tenant/learning")
def set_learning_preference(
    payload: LearningPreferenceRequest,
    ctx: TenantContext = Depends(require_tenant),
    db: Session = Depends(get_db),
):
    tenant = db.get(Tenant, ctx.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    tenant.global_learning_enabled = payload.enabled
    db.commit()
    return {"global_learning_enabled": tenant.global_learning_enabled}


@app.get("/v1/global/failures")
def list_global_failures(
    ctx: TenantContext = Depends(require_tenant), db: Session = Depends(get_db)
):
    patterns = db.scalars(
        select(GlobalFailurePattern).order_by(GlobalFailurePattern.recurrence_count.desc())
    )
    return [global_pattern_response(pattern) for pattern in patterns]


@app.get("/v1/global/evaluations")
def list_global_evaluations(
    _: TenantContext = Depends(require_tenant), db: Session = Depends(get_db)
):
    definitions = db.scalars(
        select(GlobalEvaluationDefinition).order_by(GlobalEvaluationDefinition.created_at.desc())
    )
    return [
        {
            "id": str(item.id),
            "global_pattern_id": str(item.global_pattern_id),
            "name": item.name,
            "version": item.version,
            "preconditions": item.preconditions,
            "pass_criteria": item.pass_criteria,
            "status": item.status,
        }
        for item in definitions
    ]


@app.post("/v1/global/evaluations/{evaluation_id}/run")
def run_global_evaluation_endpoint(
    evaluation_id: UUID,
    payload: GlobalEvaluationRunRequest,
    ctx: TenantContext = Depends(require_tenant),
    db: Session = Depends(get_db),
):
    definition = db.get(GlobalEvaluationDefinition, evaluation_id)
    if definition is None:
        raise HTTPException(status_code=404, detail="Global evaluation not found")
    try:
        run = run_global_evaluation(
            definition,
            payload.observed_actions,
            payload.outcome,
            payload.evidence,
            db,
            tenant_id=ctx.tenant_id,
            judge_provider=payload.judge_provider,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    db.commit()
    db.refresh(run)
    return {
        "id": str(run.id),
        "definition_id": str(run.definition_id),
        "judge_provider": run.judge_provider,
        "status": run.status,
        "passed": run.passed,
        "metrics": run.metrics,
        "blockers": run.blockers,
        "user_action_requests": run.metrics.get("user_action_requests", []),
        "negative_case_analysis": run.metrics.get("negative_case_analysis", []),
    }


@app.post("/v1/global/evaluations/{evaluation_id}/execute")
def execute_isolated_global_evaluation(
    evaluation_id: UUID,
    payload: IsolatedEvaluationRunRequest,
    ctx: TenantContext = Depends(require_tenant),
    db: Session = Depends(get_db),
):
    """Execute the definition's fixed actions in an enabled isolated Docker target.

    The image is selected only by server configuration. Gemini judges redacted run
    evidence afterward; it never receives control of Docker commands.
    """
    definition = db.get(GlobalEvaluationDefinition, evaluation_id)
    if definition is None:
        raise HTTPException(status_code=404, detail="Global evaluation not found")
    try:
        runner_result = DockerEvaluationRunner.from_settings().run(
            definition.pass_criteria.get("ordered_actions", [])
        )
        run = run_global_evaluation(
            definition,
            runner_result.observed_actions,
            runner_result.outcome,
            runner_result.evidence,
            db,
            tenant_id=ctx.tenant_id,
            judge_provider=payload.judge_provider,
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    db.commit()
    db.refresh(run)
    return {
        "id": str(run.id),
        "definition_id": str(run.definition_id),
        "judge_provider": run.judge_provider,
        "status": run.status,
        "passed": run.passed,
        "metrics": run.metrics,
        "blockers": run.blockers,
        "user_action_requests": run.metrics.get("user_action_requests", []),
        "negative_case_analysis": run.metrics.get("negative_case_analysis", []),
        "execution_evidence": runner_result.evidence,
    }


@app.get("/v1/negative-cases")
def list_negative_case_analyses(
    limit: int = Query(default=20, ge=1, le=100),
    ctx: TenantContext = Depends(require_tenant),
    db: Session = Depends(get_db),
):
    """Return only this tenant's judge explanations for failed or risky journeys."""
    runs = db.scalars(
        select(GlobalEvaluationRun)
        .where(GlobalEvaluationRun.tenant_id == ctx.tenant_id)
        .order_by(GlobalEvaluationRun.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "run_id": str(run.id),
            "definition_id": str(run.definition_id),
            "judge_provider": run.judge_provider,
            "status": run.status,
            "created_at": run.created_at,
            "blockers": run.blockers,
            "analysis": run.metrics.get("negative_case_analysis", []),
            "user_action_requests": run.metrics.get("user_action_requests", []),
        }
        for run in runs
        if run.metrics.get("negative_case_analysis")
    ]


@app.post("/v1/risk/evaluate")
def evaluate_action_risk_endpoint(
    payload: ActionRiskRequest,
    ctx: TenantContext = Depends(require_tenant),
    db: Session = Depends(get_db),
):
    project = db.scalar(
        select(Project).where(Project.id == payload.project_id, Project.tenant_id == ctx.tenant_id)
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return evaluate_action_risk(
        tenant_id=ctx.tenant_id,
        canonical_action=payload.canonical_action,
        error_type=payload.error_type,
        environment_fingerprint=payload.environment_fingerprint,
        api_url=payload.api_url,
        db=db,
    )


@app.get("/v1/global/strategies")
def list_global_strategies(
    _: TenantContext = Depends(require_tenant), db: Session = Depends(get_db)
):
    candidates = db.scalars(
        select(GlobalStrategyCandidate).where(
            GlobalStrategyCandidate.status.in_(["VALIDATED", "ACTIVE"])
        )
    )
    return [
        {
            "id": str(item.id),
            "global_pattern_id": str(item.global_pattern_id),
            "name": item.name,
            "version": item.version,
            "actions": item.actions,
            "applicability": item.applicability,
            "status": item.status,
            "validation_status": item.validation_status,
        }
        for item in candidates
    ]


@app.post("/v1/global/strategies/{strategy_id}/activate")
def activate_global_strategy(
    strategy_id: UUID,
    _: TenantContext = Depends(require_tenant),
    db: Session = Depends(get_db),
):
    strategy = db.get(GlobalStrategyCandidate, strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail="Global strategy not found")
    if strategy.validation_status != "VALIDATED":
        raise HTTPException(
            status_code=409, detail="Only validated global strategies can be activated"
        )
    strategy.status = "ACTIVE"
    strategy.validation_status = "ACTIVE"
    db.commit()
    return {
        "id": str(strategy.id),
        "status": strategy.status,
        "validation_status": strategy.validation_status,
    }


@app.post("/v1/events", response_model=EventRead, status_code=201)
def ingest_event(
    payload: EventIn, ctx: TenantContext = Depends(require_tenant), db: Session = Depends(get_db)
):
    event = persist_event(payload, ctx, db)
    db.commit()
    db.refresh(event)
    return event


@app.post("/v1/events/batch", response_model=list[EventRead], status_code=201)
def ingest_events(
    payload: EventBatch, ctx: TenantContext = Depends(require_tenant), db: Session = Depends(get_db)
):
    events = [persist_event(item, ctx, db) for item in payload.events]
    db.commit()
    return events


@app.post("/v1/events/normalized", response_model=EventRead, status_code=201)
def ingest_normalized_event(
    payload: NormalizedEventRequest,
    ctx: TenantContext = Depends(require_tenant),
    db: Session = Depends(get_db),
):
    try:
        event = normalize_event(
            payload.adapter,
            payload.event,
            AdapterContext(
                project_id=payload.project_id,
                session_id=payload.session_id,
                trace_id=payload.trace_id,
                agent_type=payload.agent_type,
            ),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    persisted = persist_event(event, ctx, db)
    db.commit()
    db.refresh(persisted)
    return persisted


@app.get("/v1/sessions/{session_id}/trace", response_model=list[EventRead])
def get_trace(
    session_id: UUID, ctx: TenantContext = Depends(require_tenant), db: Session = Depends(get_db)
):
    session = db.scalar(
        select(ExecutionSession).where(
            ExecutionSession.id == session_id, ExecutionSession.tenant_id == ctx.tenant_id
        )
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return list(
        db.scalars(
            select(ExecutionEvent)
            .where(
                ExecutionEvent.session_id == session_id, ExecutionEvent.tenant_id == ctx.tenant_id
            )
            .order_by(ExecutionEvent.timestamp, ExecutionEvent.id)
        )
    )


@app.get("/v1/projects/{project_id}/events", response_model=list[EventRead])
def list_project_events(
    project_id: UUID,
    limit: int = 100,
    ctx: TenantContext = Depends(require_tenant),
    db: Session = Depends(get_db),
):
    """Return recent observed events for the authenticated tenant's project only."""
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    project = db.scalar(
        select(Project).where(Project.id == project_id, Project.tenant_id == ctx.tenant_id)
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return list(
        db.scalars(
            select(ExecutionEvent)
            .where(
                ExecutionEvent.tenant_id == ctx.tenant_id,
                ExecutionEvent.project_id == project_id,
            )
            .order_by(ExecutionEvent.timestamp.desc(), ExecutionEvent.id.desc())
            .limit(limit)
        )
    )


@app.get("/v1/failures", response_model=list[FailurePatternRead])
def list_failures(
    project_id: UUID | None = None,
    ctx: TenantContext = Depends(require_tenant),
    db: Session = Depends(get_db),
):
    query = select(FailurePattern).where(FailurePattern.tenant_id == ctx.tenant_id)
    if project_id is not None:
        query = query.where(FailurePattern.project_id == project_id)
    patterns = list(db.scalars(query.order_by(FailurePattern.last_seen.desc())))
    for pattern in patterns:
        pattern.occurrences = list(
            db.scalars(
                select(FailureOccurrence)
                .where(
                    FailureOccurrence.pattern_id == pattern.id,
                    FailureOccurrence.tenant_id == ctx.tenant_id,
                )
                .order_by(FailureOccurrence.observed_at)
            )
        )
    return patterns


@app.get("/v1/failures/{failure_id}", response_model=FailurePatternRead)
def get_failure(
    failure_id: UUID,
    ctx: TenantContext = Depends(require_tenant),
    db: Session = Depends(get_db),
):
    pattern = db.scalar(
        select(FailurePattern).where(
            FailurePattern.id == failure_id, FailurePattern.tenant_id == ctx.tenant_id
        )
    )
    if pattern is None:
        raise HTTPException(status_code=404, detail="Failure pattern not found")
    pattern.occurrences = list(
        db.scalars(
            select(FailureOccurrence)
            .where(
                FailureOccurrence.pattern_id == pattern.id,
                FailureOccurrence.tenant_id == ctx.tenant_id,
            )
            .order_by(FailureOccurrence.observed_at)
        )
    )
    return pattern


@app.get("/v1/evaluations", response_model=list[EvaluationRead])
def list_evaluations(
    project_id: UUID | None = None,
    ctx: TenantContext = Depends(require_tenant),
    db: Session = Depends(get_db),
):
    query = select(EvaluationDefinition).where(EvaluationDefinition.tenant_id == ctx.tenant_id)
    if project_id is not None:
        query = query.where(EvaluationDefinition.project_id == project_id)
    return list(db.scalars(query.order_by(EvaluationDefinition.created_at.desc())))


@app.post("/v1/evaluations/{evaluation_id}/run", response_model=EvaluationRunRead, status_code=201)
def execute_evaluation(
    evaluation_id: UUID,
    payload: EvaluationRunRequest,
    ctx: TenantContext = Depends(require_tenant),
    db: Session = Depends(get_db),
):
    definition = db.scalar(
        select(EvaluationDefinition).where(
            EvaluationDefinition.id == evaluation_id,
            EvaluationDefinition.tenant_id == ctx.tenant_id,
        )
    )
    if definition is None:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    run = run_evaluation(
        definition, payload.observed_actions, payload.outcome, payload.evidence, db
    )
    db.commit()
    db.refresh(run)
    return run


@app.get("/v1/strategies", response_model=list[StrategyRead])
def list_strategies(
    project_id: UUID | None = None,
    ctx: TenantContext = Depends(require_tenant),
    db: Session = Depends(get_db),
):
    query = select(StrategyCandidate).where(StrategyCandidate.tenant_id == ctx.tenant_id)
    if project_id is not None:
        query = query.where(StrategyCandidate.project_id == project_id)
    candidates = list(db.scalars(query.order_by(StrategyCandidate.created_at.desc())))
    result = []
    for candidate in candidates:
        version = db.scalar(
            select(StrategyVersion)
            .where(StrategyVersion.candidate_id == candidate.id)
            .order_by(StrategyVersion.version.desc())
        )
        if version is not None:
            result.append(
                StrategyRead(
                    id=candidate.id,
                    tenant_id=candidate.tenant_id,
                    project_id=candidate.project_id,
                    failure_pattern_id=candidate.failure_pattern_id,
                    name=candidate.name,
                    applicability=candidate.applicability,
                    status=candidate.status,
                    version=version.version,
                    actions=version.actions,
                    validation_status=version.validation_status,
                    created_at=candidate.created_at,
                    last_validated_at=version.last_validated_at,
                )
            )
    return result


@app.get("/v1/strategies/{strategy_id}", response_model=StrategyRead)
def get_strategy(
    strategy_id: UUID,
    ctx: TenantContext = Depends(require_tenant),
    db: Session = Depends(get_db),
):
    candidate = db.scalar(
        select(StrategyCandidate).where(
            StrategyCandidate.id == strategy_id, StrategyCandidate.tenant_id == ctx.tenant_id
        )
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    version = db.scalar(
        select(StrategyVersion)
        .where(StrategyVersion.candidate_id == candidate.id)
        .order_by(StrategyVersion.version.desc())
    )
    if version is None:
        raise HTTPException(status_code=404, detail="Strategy version not found")
    return StrategyRead(
        id=candidate.id,
        tenant_id=candidate.tenant_id,
        project_id=candidate.project_id,
        failure_pattern_id=candidate.failure_pattern_id,
        name=candidate.name,
        applicability=candidate.applicability,
        status=candidate.status,
        version=version.version,
        actions=version.actions,
        validation_status=version.validation_status,
        created_at=candidate.created_at,
        last_validated_at=version.last_validated_at,
    )


@app.post("/v1/strategies/{strategy_id}/activate", response_model=StrategyRead)
def activate_strategy(
    strategy_id: UUID,
    ctx: TenantContext = Depends(require_tenant),
    db: Session = Depends(get_db),
):
    candidate = db.scalar(
        select(StrategyCandidate).where(
            StrategyCandidate.id == strategy_id, StrategyCandidate.tenant_id == ctx.tenant_id
        )
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    version = db.scalar(
        select(StrategyVersion)
        .where(StrategyVersion.candidate_id == candidate.id)
        .order_by(StrategyVersion.version.desc())
    )
    if version is None or version.validation_status != "VALIDATED":
        raise HTTPException(status_code=409, detail="Only validated strategies can be activated")
    candidate.status = "ACTIVE"
    version.validation_status = "ACTIVE"
    db.commit()
    db.refresh(candidate)
    return StrategyRead(
        id=candidate.id,
        tenant_id=candidate.tenant_id,
        project_id=candidate.project_id,
        failure_pattern_id=candidate.failure_pattern_id,
        name=candidate.name,
        applicability=candidate.applicability,
        status=candidate.status,
        version=version.version,
        actions=version.actions,
        validation_status=version.validation_status,
        created_at=candidate.created_at,
        last_validated_at=version.last_validated_at,
    )


@app.post("/v1/context/compile")
def compile_execution_context(
    payload: ContextCompileRequest,
    ctx: TenantContext = Depends(require_tenant),
    db: Session = Depends(get_db),
):
    project = db.scalar(
        select(Project).where(Project.id == payload.project_id, Project.tenant_id == ctx.tenant_id)
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    package = compile_context(
        tenant_id=ctx.tenant_id,
        project_id=payload.project_id,
        task_type=payload.task_type,
        agent_type=payload.agent_type,
        failure_type=payload.failure_type,
        canonical_action=payload.canonical_action,
        environment_fingerprint=payload.environment_fingerprint,
        max_strategies=payload.max_strategies,
        render_markdown_output=payload.render_markdown,
        db=db,
    )
    db.commit()
    return package


@app.post("/v1/projects", response_model=ProjectRead, status_code=201)
def create_project(
    payload: ProjectCreate,
    ctx: TenantContext = Depends(require_tenant),
    db: Session = Depends(get_db),
):
    project = Project(tenant_id=ctx.tenant_id, **payload.model_dump())
    db.add(project)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Project slug already exists") from exc
    db.refresh(project)
    return project


@app.get("/v1/projects", response_model=list[ProjectRead])
def list_projects(ctx: TenantContext = Depends(require_tenant), db: Session = Depends(get_db)):
    return list(
        db.scalars(
            select(Project).where(Project.tenant_id == ctx.tenant_id).order_by(Project.created_at)
        )
    )


@app.get("/v1/projects/{project_id}", response_model=ProjectRead)
def get_project(
    project_id: UUID, ctx: TenantContext = Depends(require_tenant), db: Session = Depends(get_db)
):
    project = db.scalar(
        select(Project).where(Project.id == project_id, Project.tenant_id == ctx.tenant_id)
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def bootstrap_dev_data(db: Session) -> Tenant:
    tenant = db.scalar(select(Tenant).where(Tenant.name == "Development"))
    if tenant is None:
        tenant = Tenant(name="Development")
        db.add(tenant)
        db.flush()
        db.add(
            ApiKey(
                tenant_id=tenant.id,
                key_hash=hash_api_key(get_settings().api_key),
                name="development",
            )
        )
        db.commit()
    return tenant
