"""Pre-execution risk assessment from de-identified operational evidence."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from acil.api_targets import normalize_api_target
from acil.models import GlobalFailurePattern, GlobalStrategyCandidate, Tenant


def _same(left: str | None, right: str | None) -> bool:
    return (left or "").strip().lower() == (right or "").strip().lower()


def evaluate_action_risk(
    *,
    tenant_id: UUID,
    canonical_action: str,
    error_type: str | None,
    environment_fingerprint: str | None,
    api_url: str | None,
    db: Session,
) -> dict:
    """Return aggregate preflight guidance without disclosing tenant evidence."""
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise ValueError("Tenant not found")
    if not tenant.global_learning_enabled:
        return {
            "decision": "ALLOW",
            "reason": "Shared learning is disabled for this tenant.",
            "matched_patterns": [],
            "recommended_actions": ["Proceed using local project context only."],
            "requires_user_confirmation": False,
        }

    target = normalize_api_target(api_url)
    patterns = db.scalars(select(GlobalFailurePattern)).all()
    matches = []
    active_strategies = []
    for pattern in patterns:
        if target is not None:
            if pattern.api_target_fingerprint != target["fingerprint"]:
                continue
        elif not _same(pattern.canonical_action, canonical_action):
            continue
        if error_type and not _same(pattern.error_type, error_type):
            continue
        if pattern.environment_fingerprint and not _same(
            pattern.environment_fingerprint, environment_fingerprint
        ):
            continue
        matches.append(pattern)
        active_strategies.extend(
            db.scalars(
                select(GlobalStrategyCandidate).where(
                    GlobalStrategyCandidate.global_pattern_id == pattern.id,
                    GlobalStrategyCandidate.status == "ACTIVE",
                    GlobalStrategyCandidate.validation_status == "ACTIVE",
                )
            ).all()
        )

    if not matches:
        return {
            "decision": "ALLOW",
            "reason": "No matching shared failure pattern has validated preflight relevance.",
            "matched_patterns": [],
            "recommended_actions": ["Proceed and report the observable outcome."],
            "requires_user_confirmation": False,
        }

    recurrence = max(pattern.recurrence_count for pattern in matches)
    decision = "REQUIRE_CONFIRMATION" if recurrence >= 3 else "WARN"
    actions = [
        "Do not repeat the call unchanged.",
        "Inspect the matching environment and recovery guidance first.",
        "Ask for user confirmation before execution."
        if decision == "REQUIRE_CONFIRMATION"
        else "Report the outcome to ACIL.",
    ]
    for strategy in active_strategies:
        actions.append(f"Validated alternative: {' → '.join(strategy.actions)}")
    return {
        "decision": decision,
        "reason": "A matching de-identified failure pattern is recurrent across opted-in evidence.",
        "matched_patterns": [
            {
                "canonical_action": pattern.canonical_action,
                "error_type": pattern.error_type,
                "environment_fingerprint": pattern.environment_fingerprint,
                "recurrence_count": pattern.recurrence_count,
                "source_tenant_count": pattern.source_tenant_count,
                "api_target_matched": target is not None,
            }
            for pattern in matches[:5]
        ],
        "recommended_actions": actions[:8],
        "requires_user_confirmation": decision == "REQUIRE_CONFIRMATION",
    }
