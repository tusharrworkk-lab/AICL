from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from acil.db import Base


def now() -> datetime:
    return datetime.now(UTC)


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200))
    global_learning_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    memberships: Mapped[list["TenantMembership"]] = relationship(back_populates="tenant")
    projects: Mapped[list["Project"]] = relationship(back_populates="tenant")


class User(Base):
    __tablename__ = "users"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class TenantMembership(Base):
    __tablename__ = "tenant_memberships"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(50), default="member")
    tenant: Mapped[Tenant] = relationship(back_populates="memberships")


class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    key_hash: Mapped[str] = mapped_column(String(128), unique=True)
    name: Mapped[str] = mapped_column(String(100), default="integration")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug"),
        Index("ix_projects_tenant", "tenant_id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    tenant: Mapped[Tenant] = relationship(back_populates="projects")


class Agent(Base):
    __tablename__ = "agents"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    agent_type: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ExecutionSession(Base):
    __tablename__ = "sessions"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    agent_type: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ExecutionEvent(Base):
    __tablename__ = "execution_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "event_id"),
        Index("ix_execution_events_trace", "tenant_id", "trace_id", "timestamp"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    event_id: Mapped[str] = mapped_column(String(200))
    trace_id: Mapped[str] = mapped_column(String(200), index=True)
    span_id: Mapped[str] = mapped_column(String(200))
    parent_span_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    agent_type: Mapped[str] = mapped_column(String(100))
    event_type: Mapped[str] = mapped_column(String(100))
    canonical_action: Mapped[str] = mapped_column(String(100))
    native_tool_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(30))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)


class FailurePattern(Base):
    __tablename__ = "failure_patterns"
    __table_args__ = (
        UniqueConstraint("tenant_id", "project_id", "fingerprint"),
        Index("ix_failure_patterns_tenant", "tenant_id", "project_id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    fingerprint: Mapped[str] = mapped_column(String(64))
    canonical_action: Mapped[str] = mapped_column(String(100))
    error_type: Mapped[str] = mapped_column(String(100))
    native_tool_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    environment_fingerprint: Mapped[str | None] = mapped_column(String(200), nullable=True)
    api_target_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    occurrence_count: Mapped[int] = mapped_column(default=0)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class FailureOccurrence(Base):
    __tablename__ = "failure_occurrences"
    __table_args__ = (UniqueConstraint("tenant_id", "event_id"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    pattern_id: Mapped[UUID] = mapped_column(
        ForeignKey("failure_patterns.id", ondelete="CASCADE"), index=True
    )
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("execution_events.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    observed_error: Mapped[str] = mapped_column(String(200))
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)


class EvaluationDefinition(Base):
    __tablename__ = "evaluation_definitions"
    __table_args__ = (UniqueConstraint("tenant_id", "failure_pattern_id", "version"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    failure_pattern_id: Mapped[UUID] = mapped_column(
        ForeignKey("failure_patterns.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(default=1)
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    preconditions: Mapped[dict] = mapped_column(JSON, default=dict)
    expected_outcomes: Mapped[dict] = mapped_column(JSON, default=dict)
    constraints: Mapped[dict] = mapped_column(JSON, default=dict)
    pass_criteria: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_requirements: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    definition_id: Mapped[UUID] = mapped_column(
        ForeignKey("evaluation_definitions.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(30))
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    observed_actions: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StrategyCandidate(Base):
    __tablename__ = "strategy_candidates"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    failure_pattern_id: Mapped[UUID] = mapped_column(
        ForeignKey("failure_patterns.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    applicability: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="CANDIDATE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class StrategyVersion(Base):
    __tablename__ = "strategy_versions"
    __table_args__ = (UniqueConstraint("candidate_id", "version"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("strategy_candidates.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(default=1)
    actions: Mapped[list] = mapped_column(JSON, default=list)
    validation_status: Mapped[str] = mapped_column(String(30), default="CANDIDATE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class StrategyEvidence(Base):
    __tablename__ = "strategy_evidence"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    strategy_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("strategy_versions.id", ondelete="CASCADE"), index=True
    )
    evaluation_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"), index=True
    )
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ContextRequest(Base):
    __tablename__ = "context_requests"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    task_type: Mapped[str] = mapped_column(String(100))
    agent_type: Mapped[str] = mapped_column(String(100))
    request_conditions: Mapped[dict] = mapped_column(JSON, default=dict)
    result_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class GlobalFailurePattern(Base):
    __tablename__ = "global_failure_patterns"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    canonical_action: Mapped[str] = mapped_column(String(100))
    error_type: Mapped[str] = mapped_column(String(100))
    native_tool_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    environment_fingerprint: Mapped[str | None] = mapped_column(String(200), nullable=True)
    api_target_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    recurrence_count: Mapped[int] = mapped_column(default=0)
    source_tenant_count: Mapped[int] = mapped_column(default=0)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class GlobalFailureObservation(Base):
    __tablename__ = "global_failure_observations"
    __table_args__ = (UniqueConstraint("global_pattern_id", "tenant_id", "failure_pattern_id"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    global_pattern_id: Mapped[UUID] = mapped_column(
        ForeignKey("global_failure_patterns.id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    failure_pattern_id: Mapped[UUID] = mapped_column(
        ForeignKey("failure_patterns.id", ondelete="CASCADE"), index=True
    )
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class GlobalEvaluationDefinition(Base):
    __tablename__ = "global_evaluation_definitions"
    __table_args__ = (UniqueConstraint("global_pattern_id", "version"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    global_pattern_id: Mapped[UUID] = mapped_column(
        ForeignKey("global_failure_patterns.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(default=1)
    preconditions: Mapped[dict] = mapped_column(JSON, default=dict)
    pass_criteria: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_requirements: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="CANDIDATE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class GlobalEvaluationRun(Base):
    __tablename__ = "global_evaluation_runs"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    definition_id: Mapped[UUID] = mapped_column(
        ForeignKey("global_evaluation_definitions.id", ondelete="CASCADE"), index=True
    )
    # Global definitions may be shared, but run evidence and judge analysis stay tenant-private.
    tenant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=True
    )
    judge_provider: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(30))
    passed: Mapped[bool] = mapped_column(Boolean)
    observed_actions: Mapped[list] = mapped_column(JSON, default=list)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    blockers: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class GlobalStrategyCandidate(Base):
    __tablename__ = "global_strategy_candidates"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    global_pattern_id: Mapped[UUID] = mapped_column(
        ForeignKey("global_failure_patterns.id", ondelete="CASCADE"), index=True
    )
    evaluation_definition_id: Mapped[UUID] = mapped_column(
        ForeignKey("global_evaluation_definitions.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(default=1)
    actions: Mapped[list] = mapped_column(JSON, default=list)
    applicability: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="CANDIDATE")
    validation_status: Mapped[str] = mapped_column(String(30), default="CANDIDATE")
    last_validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
