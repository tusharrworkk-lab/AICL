from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from acil.config import get_settings
from acil.judge import BedrockJudge, DeterministicJudge, KimiK3ChatJudge
from acil.models import (
    GlobalEvaluationDefinition,
    GlobalEvaluationRun,
    GlobalFailurePattern,
    GlobalStrategyCandidate,
)

RECOVERY_ACTIONS = ["CHECK_DEPENDENCIES", "PREPARE_ENVIRONMENT", "RUN_TESTS"]


def ensure_global_candidates(pattern: GlobalFailurePattern, db: Session) -> None:
    definition = db.scalar(
        select(GlobalEvaluationDefinition).where(
            GlobalEvaluationDefinition.global_pattern_id == pattern.id
        )
    )
    if definition is not None:
        return
    definition = GlobalEvaluationDefinition(
        global_pattern_id=pattern.id,
        name=f"global_recover_{pattern.error_type.lower()}",
        preconditions={
            "canonical_action": pattern.canonical_action,
            "environment_fingerprint": pattern.environment_fingerprint,
        },
        pass_criteria={"ordered_actions": RECOVERY_ACTIONS, "outcome": "success"},
        evidence_requirements={"journey_trace": True, "observable_outcome": True},
    )
    db.add(definition)
    db.flush()
    db.add(
        GlobalStrategyCandidate(
            global_pattern_id=pattern.id,
            evaluation_definition_id=definition.id,
            name="global_verify_test_environment",
            actions=RECOVERY_ACTIONS,
            applicability={
                "error_type": pattern.error_type,
                "canonical_action": pattern.canonical_action,
                "environment_fingerprint": pattern.environment_fingerprint,
            },
        )
    )


def run_global_evaluation(
    definition: GlobalEvaluationDefinition,
    observed_actions: list[str],
    outcome: str,
    evidence: dict,
    db: Session,
    tenant_id: UUID,
    judge_provider: str = "deterministic",
    judge=None,
) -> GlobalEvaluationRun:
    selected_judge = judge or (
        KimiK3ChatJudge()
        if judge_provider == "bedrock" and "moonshotai.kimi-k3" in get_settings().bedrock_model
        else BedrockJudge()
        if judge_provider == "bedrock"
        else DeterministicJudge()
    )
    expected_actions = definition.pass_criteria.get("ordered_actions", [])
    # An LLM can enrich analysis, but never replaces reproducible evidence for promotion.
    deterministic_result = DeterministicJudge().evaluate(
        expected_actions, observed_actions, outcome, evidence
    )
    result = selected_judge.evaluate(expected_actions, observed_actions, outcome, evidence)
    passed = result.passed and deterministic_result.passed
    blockers = list(dict.fromkeys(result.blockers + deterministic_result.blockers))
    if result.passed and not deterministic_result.passed:
        blockers.append("deterministic_evidence_gate_failed")
    run = GlobalEvaluationRun(
        definition_id=definition.id,
        tenant_id=tenant_id,
        judge_provider=selected_judge.provider,
        status="PASSED" if passed else "FAILED",
        passed=passed,
        observed_actions=observed_actions,
        metrics={
            **result.metrics,
            "improvement_suggestions": result.improvement_suggestions,
            "user_action_requests": result.user_action_requests,
            "negative_case_analysis": result.negative_case_analysis,
            "deterministic_evidence_gate_passed": deterministic_result.passed,
        },
        blockers=blockers,
        evidence=evidence,
        created_at=datetime.now(UTC),
    )
    db.add(run)
    db.flush()
    candidate = db.scalar(
        select(GlobalStrategyCandidate).where(
            GlobalStrategyCandidate.evaluation_definition_id == definition.id
        )
    )
    if candidate is not None and passed:
        candidate.status = "VALIDATED"
        candidate.validation_status = "VALIDATED"
        candidate.last_validated_at = run.created_at
    return run
