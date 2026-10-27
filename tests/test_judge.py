from types import SimpleNamespace

import pytest

from acil.judge import BedrockJudge, GeminiJudge, KimiK3ChatJudge, _parse_judge_output


def test_gemini_judge_validates_structured_response_without_network():
    class FakeModels:
        def generate_content(self, **kwargs):
            assert kwargs["model"] == "test-model"
            assert kwargs["config"]["response_mime_type"] == "application/json"
            assert "[REDACTED]" in kwargs["contents"]
            return SimpleNamespace(
                text='{"passed":true,"metrics":{"coverage":1.0},"blockers":[],"improvement_suggestions":["Add a state invariant"],"reliability_score":91,"user_action_requests":[{"kind":"scoped_credential_required","message":"Provide a scoped tool credential."}]}'
            )

    fake_client = SimpleNamespace(models=FakeModels())
    judge = GeminiJudge(client=fake_client, model="test-model")
    result = judge.evaluate(
        ["CHECK_DEPENDENCIES"], ["CHECK_DEPENDENCIES"], "success", {"api_token": "nope"}
    )
    assert result.passed is True
    assert result.metrics["coverage"] == 1.0
    assert result.improvement_suggestions == ["Add a state invariant"]
    assert result.metrics["reliability_score"] == 91
    assert result.user_action_requests[0]["kind"] == "scoped_credential_required"


def test_gemini_judge_wraps_provider_errors():
    class FailingModels:
        def generate_content(self, **kwargs):
            raise ValueError("provider unavailable")

    judge = GeminiJudge(client=SimpleNamespace(models=FailingModels()), model="test-model")
    with pytest.raises(RuntimeError, match="Gemini Vertex AI request failed"):
        judge.evaluate(["RUN_TESTS"], ["RUN_TESTS"], "success")


def test_bedrock_judge_uses_converse_and_parses_structured_json():
    class FakeBedrockClient:
        def converse(self, **kwargs):
            assert kwargs["modelId"] == "google.gemma-3-4b-it"
            assert kwargs["messages"][0]["role"] == "user"
            return {
                "output": {
                    "message": {
                        "content": [
                            {
                                "text": """```json
                                {\"passed\":true,\"metrics\":{\"coverage\":1.0},\"blockers\":[],\"improvement_suggestions\":[],\"reliability_score\":93,\"user_action_requests\":[],\"negative_case_analysis\":[{\"failure_case\":\"dependency unavailable\",\"observed_facts\":[\"RUN_TESTS failed\"],\"likely_cause\":\"dependency missing\",\"confidence\":85,\"evidence_gaps\":[\"environment package list\"],\"impact\":\"tests cannot run\",\"recommended_next_actions\":[\"inspect dependencies\"]}]}
                                ```"""
                            }
                        ]
                    }
                }
            }

    judge = BedrockJudge(client=FakeBedrockClient(), model="google.gemma-3-4b-it")
    result = judge.evaluate(["RUN_TESTS"], ["RUN_TESTS"], "success")
    assert result.passed is True
    assert result.metrics["reliability_score"] == 93
    assert result.negative_case_analysis[0]["likely_cause"] == "dependency missing"


def test_bedrock_judge_reports_truncated_structured_output_cleanly():
    class TruncatedBedrockClient:
        def converse(self, **kwargs):
            return {"output": {"message": {"content": [{"text": '{"passed": true'}]}}}

    judge = BedrockJudge(client=TruncatedBedrockClient(), model="google.gemma-3-4b-it")
    with pytest.raises(RuntimeError, match="BEDROCK_MAX_OUTPUT_TOKENS"):
        judge.evaluate(["RUN_TESTS"], ["RUN_TESTS"], "success")


def test_kimi_judge_omits_unsupported_temperature_field():
    class FakeKimiClient:
        def converse(self, **kwargs):
            assert kwargs["inferenceConfig"] == {"maxTokens": 512}
            assert kwargs["additionalModelRequestFields"] == {"reasoning_effort": "low"}
            return {
                "output": {
                    "message": {
                        "content": [
                            {
                                "text": '{"passed":false,"metrics":{},"blockers":["failed"],"improvement_suggestions":[],"reliability_score":0,"user_action_requests":[]}'
                            }
                        ]
                    }
                }
            }

    judge = BedrockJudge(client=FakeKimiClient(), model="in.moonshotai.kimi-k3")
    assert judge.evaluate([], [], "failure").passed is False


def test_judge_parser_accepts_json_with_provider_prose():
    result = _parse_judge_output(
        'Assessment complete. {"passed":false,"metrics":{},"blockers":["failed"],'
        '"improvement_suggestions":[],"reliability_score":0,"user_action_requests":[]} End.'
    )
    assert result.blockers == ["failed"]


def test_kimi_chat_judge_uses_structured_final_content_only():
    def fake_requester(payload):
        assert payload["model"] == "in.moonshotai.kimi-k3"
        assert payload["reasoning_effort"] == "low"
        assert payload["max_tokens"] == 2048
        assert payload["response_format"]["type"] == "json_schema"
        assert payload["response_format"]["json_schema"]["strict"] is True
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"passed":false,"metrics":{"coverage":0.5},'
                            '"blockers":["network"],"improvement_suggestions":[],'
                            '"reliability_score":40,"user_action_requests":[]}'
                        ),
                        "reasoning_content": "This must never be persisted by ACIL.",
                    }
                }
            ]
        }

    judge = KimiK3ChatJudge(requester=fake_requester, model="in.moonshotai.kimi-k3")
    result = judge.evaluate(["CHECK_DEPENDENCIES"], ["RUN_TESTS"], "failure")
    assert result.passed is False
    assert result.metrics["reliability_score"] == 40
