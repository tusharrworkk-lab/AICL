"""In-process durable-enough queue for asynchronous LLM judge runs.

The database row is committed before work is submitted. A fresh MCP process
can resume QUEUED/RUNNING rows after an interrupted local development run.
"""

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from acil.db import SessionLocal
from acil.global_evaluations import run_global_evaluation
from acil.models import GlobalEvaluationDefinition, GlobalEvaluationRun

logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="acil-bedrock-judge")


def create_queued_global_evaluation(
    *,
    definition: GlobalEvaluationDefinition,
    tenant_id: UUID,
    observed_actions: list[str],
    evidence: dict,
    db,
) -> GlobalEvaluationRun:
    run = GlobalEvaluationRun(
        definition_id=definition.id,
        tenant_id=tenant_id,
        judge_provider="bedrock",
        status="QUEUED",
        passed=False,
        observed_actions=observed_actions,
        metrics={"queued_at": datetime.now(UTC).isoformat()},
        blockers=[],
        evidence=evidence,
        created_at=datetime.now(UTC),
    )
    db.add(run)
    db.flush()
    return run


def _mark_error(run_id: UUID, message: str) -> None:
    with SessionLocal() as db:
        run = db.get(GlobalEvaluationRun, run_id)
        if run is None:
            return
        run.status = "ERROR"
        run.passed = False
        run.blockers = ["judge_execution_error"]
        run.metrics = {
            **(run.metrics or {}),
            "error": message[:1_000],
            "finished_at": datetime.now(UTC).isoformat(),
        }
        db.commit()


def execute_queued_global_evaluation(run_id: UUID) -> None:
    try:
        with SessionLocal() as db:
            run = db.get(GlobalEvaluationRun, run_id)
            if run is None or run.status in {"PASSED", "FAILED", "ERROR"}:
                return
            definition = db.get(GlobalEvaluationDefinition, run.definition_id)
            if definition is None or run.tenant_id is None:
                raise RuntimeError("Queued evaluation definition or tenant is unavailable")
            run.status = "RUNNING"
            run.metrics = {
                **(run.metrics or {}),
                "started_at": datetime.now(UTC).isoformat(),
            }
            db.commit()
            db.refresh(run)
            run_global_evaluation(
                definition=definition,
                observed_actions=list(run.observed_actions or []),
                outcome="failure",
                evidence=dict(run.evidence or {}),
                db=db,
                tenant_id=run.tenant_id,
                judge_provider="bedrock",
                existing_run=run,
            )
            run.metrics = {
                **(run.metrics or {}),
                "finished_at": datetime.now(UTC).isoformat(),
            }
            db.commit()
    except Exception as exc:  # provider failures must be persisted, never lost
        logger.exception("async_bedrock_judge_failed", extra={"run_id": str(run_id)})
        _mark_error(run_id, str(exc))


def enqueue_global_evaluation(run_id: UUID) -> Future[None]:
    return _executor.submit(execute_queued_global_evaluation, run_id)


def resume_pending_global_evaluations() -> int:
    with SessionLocal() as db:
        run_ids = list(
            db.scalars(
                select(GlobalEvaluationRun.id).where(
                    GlobalEvaluationRun.status.in_(["QUEUED", "RUNNING"])
                )
            )
        )
    for run_id in run_ids:
        enqueue_global_evaluation(run_id)
    return len(run_ids)
