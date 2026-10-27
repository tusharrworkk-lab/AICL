from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from acil.models import (
    EvaluationDefinition,
    EvaluationRun,
    FailurePattern,
    StrategyCandidate,
    StrategyEvidence,
    StrategyVersion,
)

RECOVERY_ACTIONS = ["CHECK_DEPENDENCIES", "PREPARE_ENVIRONMENT", "RUN_TESTS"]


def ensure_candidates(pattern: FailurePattern, db: Session) -> None:
    definition = db.scalar(
        select(EvaluationDefinition).where(
            EvaluationDefinition.tenant_id == pattern.tenant_id,
            EvaluationDefinition.failure_pattern_id == pattern.id,
        )
    )
    if definition is not None:
        return
    definition = EvaluationDefinition(
        tenant_id=pattern.tenant_id,
        project_id=pattern.project_id,
        failure_pattern_id=pattern.id,
        name=f"recover_{pattern.error_type.lower()}",
        inputs={"failure_fingerprint": pattern.fingerprint},
        preconditions={"canonical_action": pattern.canonical_action},
        expected_outcomes={"outcome": "success"},
        constraints={"commands_executed_by_acil": False},
        pass_criteria={"ordered_actions": RECOVERY_ACTIONS, "outcome": "success"},
        evidence_requirements={"event_trace": True},
    )
    db.add(definition)
    candidate = StrategyCandidate(
        tenant_id=pattern.tenant_id,
        project_id=pattern.project_id,
        failure_pattern_id=pattern.id,
        name="verify_test_environment",
        applicability={
            "error_type": pattern.error_type,
            "canonical_action": pattern.canonical_action,
            "environment_fingerprint": pattern.environment_fingerprint,
        },
        status="CANDIDATE",
    )
    db.add(candidate)
    db.flush()
    db.add(
        StrategyVersion(
            candidate_id=candidate.id,
            version=1,
            actions=RECOVERY_ACTIONS,
            validation_status="CANDIDATE",
        )
    )


def run_evaluation(
    definition: EvaluationDefinition,
    observed_actions: list[str],
    outcome: str,
    evidence: dict,
    db: Session,
) -> EvaluationRun:
    expected = definition.pass_criteria.get("ordered_actions", [])
    action_index = 0
    for action in observed_actions:
        if action_index < len(expected) and action == expected[action_index]:
            action_index += 1
    passed = outcome.lower() == definition.pass_criteria.get(
        "outcome", "success"
    ) and action_index == len(expected)
    run = EvaluationRun(
        tenant_id=definition.tenant_id,
        definition_id=definition.id,
        status="PASSED" if passed else "FAILED",
        passed=passed,
        observed_actions=observed_actions,
        evidence=evidence,
        finished_at=datetime.now(UTC),
    )
    db.add(run)
    db.flush()
    candidate = db.scalar(
        select(StrategyCandidate).where(
            StrategyCandidate.failure_pattern_id == definition.failure_pattern_id,
            StrategyCandidate.tenant_id == definition.tenant_id,
        )
    )
    if candidate is not None:
        version = db.scalar(
            select(StrategyVersion)
            .where(StrategyVersion.candidate_id == candidate.id)
            .order_by(StrategyVersion.version.desc())
        )
        if version is not None:
            candidate.status = "VALIDATED" if passed else "CANDIDATE"
            if passed:
                version.validation_status = "VALIDATED"
                version.last_validated_at = run.finished_at
                db.add(
                    StrategyEvidence(
                        strategy_version_id=version.id, evaluation_run_id=run.id, evidence=evidence
                    )
                )
    return run
