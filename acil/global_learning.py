from sqlalchemy import func, select
from sqlalchemy.orm import Session

from acil.global_evaluations import ensure_global_candidates
from acil.models import (
    ExecutionEvent,
    FailurePattern,
    GlobalFailureObservation,
    GlobalFailurePattern,
    Tenant,
)


def record_global_failure(pattern: FailurePattern, event: ExecutionEvent, db: Session) -> None:
    tenant = db.get(Tenant, pattern.tenant_id)
    if tenant is None or not tenant.global_learning_enabled:
        return
    global_pattern = db.scalar(
        select(GlobalFailurePattern).where(GlobalFailurePattern.fingerprint == pattern.fingerprint)
    )
    if global_pattern is None:
        global_pattern = GlobalFailurePattern(
            fingerprint=pattern.fingerprint,
            canonical_action=pattern.canonical_action,
            error_type=pattern.error_type,
            native_tool_name=pattern.native_tool_name,
            environment_fingerprint=pattern.environment_fingerprint,
            api_target_fingerprint=pattern.api_target_fingerprint,
            recurrence_count=0,
            source_tenant_count=0,
            first_seen=event.timestamp,
            last_seen=event.timestamp,
        )
        db.add(global_pattern)
        db.flush()
    observation = db.scalar(
        select(GlobalFailureObservation).where(
            GlobalFailureObservation.global_pattern_id == global_pattern.id,
            GlobalFailureObservation.tenant_id == pattern.tenant_id,
            GlobalFailureObservation.failure_pattern_id == pattern.id,
        )
    )
    if observation is None:
        db.add(
            GlobalFailureObservation(
                global_pattern_id=global_pattern.id,
                tenant_id=pattern.tenant_id,
                failure_pattern_id=pattern.id,
            )
        )
        db.flush()
        global_pattern.source_tenant_count = db.scalar(
            select(func.count(func.distinct(GlobalFailureObservation.tenant_id))).where(
                GlobalFailureObservation.global_pattern_id == global_pattern.id
            )
        )
    global_pattern.recurrence_count += 1
    if event.timestamp.replace(tzinfo=None) > global_pattern.last_seen.replace(tzinfo=None):
        global_pattern.last_seen = event.timestamp
    ensure_global_candidates(global_pattern, db)


def global_pattern_response(pattern: GlobalFailurePattern) -> dict:
    """Return only de-identified aggregate fields; no raw trace data is included."""
    return {
        "id": str(pattern.id),
        "fingerprint": pattern.fingerprint,
        "canonical_action": pattern.canonical_action,
        "error_type": pattern.error_type,
        "native_tool_name": pattern.native_tool_name,
        "environment_fingerprint": pattern.environment_fingerprint,
        "api_target_fingerprint": pattern.api_target_fingerprint,
        "recurrence_count": pattern.recurrence_count,
        "source_tenant_count": pattern.source_tenant_count,
        "first_seen": pattern.first_seen.isoformat(),
        "last_seen": pattern.last_seen.isoformat(),
    }
