from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,99}$")
    description: str | None = None


class ProjectRead(ProjectCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    created_at: datetime


class EventIn(BaseModel):
    event_id: str = Field(min_length=1, max_length=200)
    project_id: UUID
    session_id: UUID
    trace_id: str = Field(min_length=1, max_length=200)
    span_id: str = Field(min_length=1, max_length=200)
    parent_span_id: str | None = Field(default=None, max_length=200)
    agent_type: str = Field(min_length=1, max_length=100)
    event_type: str = Field(min_length=1, max_length=100)
    canonical_action: str = Field(min_length=1, max_length=100)
    native_tool_name: str | None = Field(default=None, max_length=200)
    status: str = Field(min_length=1, max_length=30)
    timestamp: datetime
    duration_ms: int | None = Field(default=None, ge=0)
    error_type: str | None = Field(default=None, max_length=100)
    # Convenience input accepted by integrations. The value is normalized into
    # attributes.api_target before persistence; the raw URL is never stored.
    api_url: str | None = Field(default=None, max_length=4_096, exclude=True)
    attributes: dict = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def preserve_observable_tool_fields(cls, value):
        """Move common Codex/CLI fields into bounded attributes for normalization."""
        if not isinstance(value, dict):
            return value
        data = dict(value)
        attributes = dict(data.get("attributes") or {})
        for key in (
            "command",
            "cmd",
            "arguments",
            "input",
            "output",
            "result",
            "error",
            "request",
            "response",
        ):
            if key in data and key not in attributes:
                attributes[key] = data[key]
        data["attributes"] = attributes
        return data


class EventBatch(BaseModel):
    events: list[EventIn] = Field(min_length=1, max_length=1000)


class EventRead(EventIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID


class FailureOccurrenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    event_id: UUID
    session_id: UUID
    observed_at: datetime
    observed_error: str
    evidence: dict


class FailurePatternRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    project_id: UUID
    fingerprint: str
    canonical_action: str
    error_type: str
    native_tool_name: str | None
    environment_fingerprint: str | None
    occurrence_count: int
    first_seen: datetime
    last_seen: datetime
    occurrences: list[FailureOccurrenceRead] = []


class EvaluationRunRequest(BaseModel):
    observed_actions: list[str] = Field(default_factory=list, max_length=100)
    outcome: str = Field(min_length=1, max_length=50)
    evidence: dict = Field(default_factory=dict)


class EvaluationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    project_id: UUID
    failure_pattern_id: UUID
    name: str
    version: int
    inputs: dict
    preconditions: dict
    expected_outcomes: dict
    constraints: dict
    pass_criteria: dict
    evidence_requirements: dict
    created_at: datetime


class EvaluationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    definition_id: UUID
    status: str
    passed: bool | None
    observed_actions: list
    evidence: dict
    started_at: datetime
    finished_at: datetime | None


class StrategyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    project_id: UUID
    failure_pattern_id: UUID
    name: str
    applicability: dict
    status: str
    version: int
    actions: list
    validation_status: str
    created_at: datetime
    last_validated_at: datetime | None


class ContextCompileRequest(BaseModel):
    project_id: UUID
    task_type: str = Field(min_length=1, max_length=100)
    agent_type: str = Field(min_length=1, max_length=100)
    failure_type: str | None = Field(default=None, max_length=100)
    canonical_action: str | None = Field(default=None, max_length=100)
    environment_fingerprint: str | None = Field(default=None, max_length=200)
    max_strategies: int = Field(default=5, ge=0, le=20)
    render_markdown: bool = False


class NormalizedEventRequest(BaseModel):
    adapter: str = Field(min_length=1, max_length=50)
    project_id: UUID
    session_id: UUID
    trace_id: str = Field(min_length=1, max_length=200)
    agent_type: str = Field(min_length=1, max_length=100)
    event: dict


class LearningPreferenceRequest(BaseModel):
    enabled: bool


class GlobalEvaluationRunRequest(BaseModel):
    observed_actions: list[str] = Field(default_factory=list, max_length=100)
    outcome: str = Field(min_length=1, max_length=50)
    evidence: dict = Field(default_factory=dict)
    judge_provider: str = Field(default="deterministic", pattern=r"^(deterministic|bedrock)$")


class IsolatedEvaluationRunRequest(BaseModel):
    judge_provider: str = Field(default="bedrock", pattern=r"^(deterministic|bedrock)$")


class ActionRiskRequest(BaseModel):
    project_id: UUID
    canonical_action: str = Field(min_length=1, max_length=100)
    error_type: str | None = Field(default=None, max_length=100)
    environment_fingerprint: str | None = Field(default=None, max_length=200)
    api_url: str | None = Field(default=None, max_length=4_096)
