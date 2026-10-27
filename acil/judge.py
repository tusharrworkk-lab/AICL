import json
import os
from dataclasses import dataclass
from typing import Protocol
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field

from acil.config import get_settings


@dataclass(frozen=True)
class JudgeResult:
    passed: bool
    metrics: dict
    blockers: list[str]
    improvement_suggestions: list[str]
    user_action_requests: list[dict]
    negative_case_analysis: list[dict]


class JourneyJudge(Protocol):
    provider: str

    def evaluate(
        self,
        expected_actions: list[str],
        observed_actions: list[str],
        outcome: str,
        evidence: dict | None = None,
    ) -> JudgeResult: ...


class DeterministicJudge:
    """Credential-free judge for reproducible tests and promotion safety."""

    provider = "deterministic"

    def evaluate(
        self,
        expected_actions: list[str],
        observed_actions: list[str],
        outcome: str,
        evidence: dict | None = None,
    ) -> JudgeResult:
        matched = 0
        for action in observed_actions:
            if matched < len(expected_actions) and action == expected_actions[matched]:
                matched += 1
        blockers = []
        if matched < len(expected_actions):
            blockers.append(f"missing_or_out_of_order_action:{expected_actions[matched]}")
        if outcome.lower() != "success":
            blockers.append("journey_outcome_not_success")
        return JudgeResult(
            passed=not blockers,
            metrics={
                "expected_action_count": len(expected_actions),
                "observed_action_count": len(observed_actions),
                "matched_action_count": matched,
                "action_coverage": matched / len(expected_actions) if expected_actions else 0.0,
                "outcome_success": outcome.lower() == "success",
                "reliability_score": (
                    100 if not blockers else int(100 * matched / len(expected_actions))
                    if expected_actions
                    else 0
                ),
            },
            blockers=blockers,
            improvement_suggestions=(
                [f"Add or verify action: {expected_actions[matched]}"]
                if matched < len(expected_actions)
                else []
            ),
            user_action_requests=[],
            negative_case_analysis=[],
        )


class LLMJudge(Protocol):
    provider: str

    def evaluate(
        self,
        expected_actions: list[str],
        observed_actions: list[str],
        outcome: str,
        evidence: dict | None = None,
    ) -> JudgeResult: ...


class NegativeCaseAnalysis(BaseModel):
    """A bounded, evidence-backed explanation—not private model reasoning."""

    failure_case: str = "unspecified"
    observed_facts: list[str] = Field(default_factory=list, max_length=5)
    likely_cause: str = "insufficient evidence to determine"
    confidence: int = Field(default=0, ge=0, le=100)
    evidence_gaps: list[str] = Field(default_factory=list, max_length=5)
    impact: str = "unknown"
    recommended_next_actions: list[str] = Field(default_factory=list, max_length=5)


class JudgeOutput(BaseModel):
    passed: bool
    metrics: dict[str, float | int | bool] = Field(default_factory=dict)
    blockers: list[str] = Field(default_factory=list)
    improvement_suggestions: list[str] = Field(default_factory=list)
    reliability_score: int = Field(ge=0, le=100)
    user_action_requests: list[dict[str, str]] = Field(default_factory=list)
    negative_case_analysis: list[NegativeCaseAnalysis] = Field(default_factory=list, max_length=5)


def redact_evidence(value: object, *, depth: int = 0) -> object:
    """Bound and redact evidence before it leaves ACIL for model assessment."""
    if depth > 4:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        secret_words = ("token", "secret", "password", "api_key", "authorization")
        return {
            str(key): "[REDACTED]"
            if any(word in str(key).lower() for word in secret_words)
            else redact_evidence(item, depth=depth + 1)
            for key, item in list(value.items())[:30]
        }
    if isinstance(value, list):
        return [redact_evidence(item, depth=depth + 1) for item in value[:30]]
    if isinstance(value, str):
        return value[:1_000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:1_000]


def _parse_judge_output(content: str) -> JudgeOutput:
    """Accept strict, fenced, or prose-wrapped JSON from providers."""
    candidate = content.strip()
    if candidate.startswith("```"):
        candidate = candidate.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        return JudgeOutput.model_validate_json(candidate)
    except ValueError:
        decoder = json.JSONDecoder()
        for start, character in enumerate(candidate):
            if character != "{":
                continue
            try:
                parsed, _ = decoder.raw_decode(candidate[start:])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return JudgeOutput.model_validate(parsed)
        raise


class BedrockJudge:
    """Gemma-compatible Amazon Bedrock Converse judge."""

    provider = "bedrock"

    def __init__(self, client=None, model: str | None = None):
        settings = get_settings()
        if client is None:
            try:
                import boto3
            except ImportError as exc:
                raise RuntimeError(
                    "Bedrock judge dependency missing; run: uv sync --extra bedrock"
                ) from exc
            auth_mode = settings.bedrock_auth_mode.lower()
            if auth_mode == "api_key":
                if not settings.bedrock_api_key:
                    raise RuntimeError("BEDROCK_API_KEY is required when BEDROCK_AUTH_MODE=api_key")
                os.environ["AWS_BEARER_TOKEN_BEDROCK"] = settings.bedrock_api_key
            elif auth_mode != "iam":
                raise RuntimeError("BEDROCK_AUTH_MODE must be 'iam' or 'api_key'")
            session = boto3.Session(
                profile_name=settings.aws_profile or None,
                region_name=settings.bedrock_region,
            )
            client = session.client("bedrock-runtime")
        self.client = client
        self.model = model or settings.bedrock_model
        self.settings = settings

    def evaluate(
        self,
        expected_actions: list[str],
        observed_actions: list[str],
        outcome: str,
        evidence: dict | None = None,
    ) -> JudgeResult:
        system = (
            "You are an execution-evaluation judge. Evaluate only the supplied abstract journey "
            "and redacted evidence. Never invent hidden reasoning, source code, secrets, command "
            "results, or tool execution. Scenario analysis is hypothetical unless backed by observed "
            "evidence. Do not reveal private chain-of-thought. For each negative case, provide "
            "only a concise evidence-backed explanation containing observed facts, likely cause, "
            "confidence, evidence gaps, impact, and next actions. Return JSON only, matching this schema: "
            + json.dumps(JudgeOutput.model_json_schema(), separators=(",", ":"))
        )
        payload = {
            "expected_actions": expected_actions,
            "observed_actions": observed_actions,
            "outcome": outcome,
            "redacted_evidence": redact_evidence(evidence or {}),
            "task": "Assess reliability, identify blockers, and propose measurable improvements. "
            "Set reliability_score from 0 to 100. If human input is required, emit concise "
            "user_action_requests with kind and message. Return at most five negative_case_analysis items.",
        }
        inference_config = {"maxTokens": self.settings.bedrock_max_output_tokens}
        # Kimi K3 rejects the Converse temperature field; retain the configured
        # temperature for providers that support it.
        if "moonshotai.kimi-k3" not in self.model:
            inference_config["temperature"] = self.settings.bedrock_temperature
        additional_fields = None
        if "moonshotai.kimi-k3" in self.model:
            additional_fields = {
                "reasoning_effort": self.settings.bedrock_reasoning_effort
            }
        try:
            request = {
                "modelId": self.model,
                "system": [{"text": system}],
                "messages": [{"role": "user", "content": [{"text": json.dumps(payload)}]}],
                "inferenceConfig": inference_config,
            }
            if additional_fields is not None:
                request["additionalModelRequestFields"] = additional_fields
            response = self.client.converse(**request)
            parts = response["output"]["message"]["content"]
            content = "".join(part.get("text", "") for part in parts)
        except Exception as exc:
            raise RuntimeError(f"Amazon Bedrock request failed: {exc}") from exc
        if not content.strip():
            raise RuntimeError("Amazon Bedrock returned an empty judge response")
        try:
            result = _parse_judge_output(content)
        except Exception as exc:
            raise RuntimeError(
                "Amazon Bedrock returned invalid structured judge output; "
                "set BEDROCK_MAX_OUTPUT_TOKENS to at least 256"
            ) from exc
        return JudgeResult(
            passed=result.passed,
            metrics={**result.metrics, "reliability_score": result.reliability_score},
            blockers=result.blockers,
            improvement_suggestions=result.improvement_suggestions,
            user_action_requests=result.user_action_requests,
            negative_case_analysis=[item.model_dump() for item in result.negative_case_analysis],
        )


class KimiK3ChatJudge:
    """Kimi K3 judge through Bedrock's OpenAI-compatible Chat Completions API.

    Reasoning output is deliberately never stored or returned. Only the final
    JSON-schema-constrained completion becomes ACIL evaluation evidence.
    """

    provider = "bedrock_kimi_k3_chat"

    def __init__(self, requester=None, model: str | None = None):
        self.settings = get_settings()
        self.model = model or self.settings.bedrock_model
        self.requester = requester or self._signed_chat_completion

    def _signed_chat_completion(self, payload: dict) -> dict:
        try:
            import boto3
            from botocore.auth import SigV4Auth
            from botocore.awsrequest import AWSRequest
        except ImportError as exc:
            raise RuntimeError(
                "Bedrock judge dependency missing; run: uv sync --extra bedrock"
            ) from exc
        session = boto3.Session(
            profile_name=self.settings.aws_profile or None,
            region_name=self.settings.bedrock_region,
        )
        credentials = session.get_credentials()
        if credentials is None:
            raise RuntimeError("No AWS credentials available for Kimi K3 Chat Completions")
        endpoint = (
            f"https://bedrock-runtime.{self.settings.bedrock_region}.amazonaws.com"
            "/openai/v1/chat/completions"
        )
        encoded = json.dumps(payload).encode()
        aws_request = AWSRequest(
            method="POST", url=endpoint, data=encoded, headers={"content-type": "application/json"}
        )
        SigV4Auth(credentials.get_frozen_credentials(), "bedrock", self.settings.bedrock_region).add_auth(
            aws_request
        )
        request = Request(endpoint, data=encoded, headers=dict(aws_request.headers.items()), method="POST")
        try:
            with urlopen(request, timeout=120) as response:
                return json.loads(response.read())
        except Exception as exc:
            raise RuntimeError(f"Kimi K3 Chat Completions request failed: {exc}") from exc

    def evaluate(
        self,
        expected_actions: list[str],
        observed_actions: list[str],
        outcome: str,
        evidence: dict | None = None,
    ) -> JudgeResult:
        system = (
            "You are an execution-evaluation judge. Evaluate only supplied abstract journey and "
            "redacted evidence. Never invent hidden reasoning, source code, secrets, command results, "
            "or tool execution. Do not expose private chain-of-thought. Return the required JSON schema."
        )
        evaluation_input = {
            "expected_actions": expected_actions,
            "observed_actions": observed_actions,
            "outcome": outcome,
            "redacted_evidence": redact_evidence(evidence or {}),
            "task": "Assess reliability, identify blockers, and propose measurable improvements.",
        }
        request_payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(evaluation_input)},
            ],
            "max_tokens": self.settings.kimi_chat_max_output_tokens,
            "reasoning_effort": self.settings.bedrock_reasoning_effort,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "acil_judge_result",
                    "strict": True,
                    "schema": JudgeOutput.model_json_schema(),
                },
            },
        }
        try:
            response = self.requester(request_payload)
            content = response["choices"][0]["message"].get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Kimi K3 returned no final completion content")
            try:
                result = _parse_judge_output(content)
            except ValueError as exc:
                finish_reason = response["choices"][0].get("finish_reason", "unknown")
                raise RuntimeError(
                    "Kimi K3 final JSON was invalid "
                    f"(finish_reason={finish_reason}, final_content_chars={len(content)})"
                ) from exc
        except Exception as exc:
            if isinstance(exc, RuntimeError):
                raise
            raise RuntimeError(f"Kimi K3 returned invalid structured judge output: {exc}") from exc
        return JudgeResult(
            passed=result.passed,
            metrics={**result.metrics, "reliability_score": result.reliability_score},
            blockers=result.blockers,
            improvement_suggestions=result.improvement_suggestions,
            user_action_requests=result.user_action_requests,
            negative_case_analysis=[item.model_dump() for item in result.negative_case_analysis],
        )


class GeminiJudge:
    """Vertex Gemini judge supporting ADC or Vertex AI Express API-key authentication."""

    provider = "gemini"

    def __init__(self, client=None, model: str | None = None):
        settings = get_settings()
        self._types = None
        if client is None:
            try:
                from google import genai
                from google.genai import types
            except ImportError as exc:
                raise RuntimeError(
                    "Gemini judge dependency missing; run: uv sync --extra gemini"
                ) from exc
            self._types = types
            http_options = types.HttpOptions(api_version="v1")
            auth_mode = settings.gemini_auth_mode.lower()
            if auth_mode == "vertex_api_key":
                if not settings.gemini_api_key:
                    raise RuntimeError("GEMINI_API_KEY is required for Vertex AI Express Mode")
                client = genai.Client(
                    vertexai=True, api_key=settings.gemini_api_key, http_options=http_options
                )
            elif auth_mode == "vertex_adc":
                if not settings.google_cloud_project:
                    raise RuntimeError(
                        "GOOGLE_CLOUD_PROJECT is required for regional Vertex AI authentication"
                    )
                # Settings reads `.env`; ADC itself reads process environment variables.
                if settings.google_application_credentials:
                    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = (
                        settings.google_application_credentials
                    )
                client = genai.Client(
                    vertexai=True,
                    project=settings.google_cloud_project,
                    location=settings.google_cloud_location,
                    http_options=http_options,
                )
            else:
                raise RuntimeError(
                    "GEMINI_AUTH_MODE must be 'vertex_api_key' or 'vertex_adc'"
                )
        self.client = client
        self.model = model or settings.gemini_judge_model
        self.settings = settings

    def _config(self, system: str):
        config = {
            "system_instruction": system,
            "max_output_tokens": self.settings.gemini_max_output_tokens,
            "response_mime_type": "application/json",
            "response_json_schema": JudgeOutput.model_json_schema(),
        }
        thinking_level = (self.settings.gemini_thinking_level or "").upper()
        if thinking_level:
            if thinking_level not in {"MINIMAL", "LOW", "MEDIUM", "HIGH"}:
                raise RuntimeError(
                    "GEMINI_THINKING_LEVEL must be MINIMAL, LOW, MEDIUM, or HIGH"
                )
            config["thinking_config"] = {"thinking_level": thinking_level}
        if self._types is None:
            return config
        return self._types.GenerateContentConfig(**config)

    def evaluate(
        self,
        expected_actions: list[str],
        observed_actions: list[str],
        outcome: str,
        evidence: dict | None = None,
    ) -> JudgeResult:
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=json.dumps(
                    {
                        "expected_actions": expected_actions,
                        "observed_actions": observed_actions,
                        "outcome": outcome,
                        "redacted_evidence": redact_evidence(evidence or {}),
                        "task": "Assess recovery, identify blockers, and suggest measurable evaluation improvements.",
                    },
                    separators=(",", ":"),
                ),
                config=self._config(
                    "You are an execution-evaluation judge. Evaluate only the abstract journey "
                    "and redacted evidence supplied. Never invent hidden reasoning, source code, "
                    "secrets, command results, or tool execution. Scenario analysis is hypothetical "
                    "unless backed by observed evidence. Return a reliability score from 0 to 100. "
                    "When human input is genuinely required, return concise user_action_requests "
                    "with kind and message; kinds include scoped_credential_required, "
                    "tool_api_required, and user_decision_required."
                ),
            )
        except Exception as exc:
            raise RuntimeError(f"Gemini Vertex AI request failed: {exc}") from exc
        result = JudgeOutput.model_validate_json(response.text)
        return JudgeResult(
            passed=result.passed,
            metrics={**result.metrics, "reliability_score": result.reliability_score},
            blockers=result.blockers,
            improvement_suggestions=result.improvement_suggestions,
            user_action_requests=result.user_action_requests,
            negative_case_analysis=[item.model_dump() for item in result.negative_case_analysis],
        )
