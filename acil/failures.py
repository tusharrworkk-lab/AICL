import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from acil.evaluations import ensure_candidates
from acil.global_learning import record_global_failure
from acil.models import ExecutionEvent, FailureOccurrence, FailurePattern


def _normalized(value: str | None) -> str:
    return (value or "unknown").strip().lower()


def failure_fingerprint(event: ExecutionEvent) -> str:
    """Create a stable fingerprint from observed, non-secret execution facts."""
    attributes = event.attributes or {}
    capabilities = attributes.get("tool_capabilities", [])
    if not isinstance(capabilities, list):
        capabilities = [str(capabilities)]
    identity = {
        "canonical_action": _normalized(event.canonical_action),
        "error_type": _normalized(event.error_type or event.event_type),
        "native_tool_name": _normalized(event.native_tool_name),
        "environment_fingerprint": _normalized(attributes.get("environment_fingerprint")),
        "api_target_fingerprint": _normalized(
            (attributes.get("api_target") or {}).get("fingerprint")
            if isinstance(attributes.get("api_target"), dict)
            else None
        ),
        "tool_capabilities": sorted(str(item).strip().lower() for item in capabilities),
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def record_failure(event: ExecutionEvent, db: Session) -> FailureOccurrence | None:
    if event.status.lower() not in {
        "failed",
        "failure",
        "error",
    } and not event.event_type.lower().endswith(".failed"):
        return None
    fingerprint = failure_fingerprint(event)
    pattern = db.scalar(
        select(FailurePattern).where(
            FailurePattern.tenant_id == event.tenant_id,
            FailurePattern.project_id == event.project_id,
            FailurePattern.fingerprint == fingerprint,
        )
    )
    attributes = event.attributes or {}
    if pattern is None:
        pattern = FailurePattern(
            tenant_id=event.tenant_id,
            project_id=event.project_id,
            fingerprint=fingerprint,
            canonical_action=event.canonical_action,
            error_type=event.error_type or event.event_type,
            native_tool_name=event.native_tool_name,
            environment_fingerprint=attributes.get("environment_fingerprint"),
            api_target_fingerprint=(attributes.get("api_target") or {}).get("fingerprint")
            if isinstance(attributes.get("api_target"), dict)
            else None,
            occurrence_count=0,
            first_seen=event.timestamp,
            last_seen=event.timestamp,
        )
        db.add(pattern)
        db.flush()
        ensure_candidates(pattern, db)
    occurrence = FailureOccurrence(
        tenant_id=event.tenant_id,
        project_id=event.project_id,
        pattern_id=pattern.id,
        event_id=event.id,
        session_id=event.session_id,
        observed_at=event.timestamp,
        observed_error=event.error_type or event.event_type,
        evidence={"event_id": event.event_id, "trace_id": event.trace_id, "span_id": event.span_id},
    )
    db.add(occurrence)
    pattern.occurrence_count += 1
    pattern_time = pattern.last_seen.replace(tzinfo=None)
    event_time = event.timestamp.replace(tzinfo=None)
    if event_time > pattern_time:
        pattern.last_seen = event.timestamp
    record_global_failure(pattern, event, db)
    return occurrence
