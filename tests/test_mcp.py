from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from acil.auth import hash_api_key
from acil.db import Base, build_engine
from acil.main import app
from acil.mcp_server import (
    evaluate_action_risk,
    get_judge_run_status,
    get_known_failures,
    report_execution_outcome,
    report_failure_for_review,
)
from acil.models import ApiKey, Tenant


def setup_mcp(tmp_path, monkeypatch):
    engine = build_engine(f"sqlite:///{tmp_path}/mcp.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        tenant = Tenant(name="MCP Tenant")
        db.add(tenant)
        db.flush()
        db.add(ApiKey(tenant_id=tenant.id, key_hash=hash_api_key("mcp-key")))
        db.commit()
    monkeypatch.setattr("acil.db.SessionLocal", Session)
    monkeypatch.setattr("acil.mcp_server.SessionLocal", Session)
    return TestClient(app)


def test_mcp_tool_enforces_tenant_and_reports_failures(tmp_path, monkeypatch):
    client = setup_mcp(tmp_path, monkeypatch)
    project = client.post(
        "/v1/projects",
        headers={"Authorization": "Bearer mcp-key"},
        json={"name": "MCP project", "slug": "mcp-project"},
    ).json()
    event = {
        "event_id": "mcp-failure",
        "project_id": project["id"],
        "session_id": str(uuid4()),
        "trace_id": "mcp-trace",
        "span_id": "mcp-span",
        "agent_type": "generic",
        "event_type": "tool.failed",
        "canonical_action": "RUN_TESTS",
        "native_tool_name": "shell",
        "status": "failed",
        "timestamp": "2026-10-26T14:00:00Z",
        "error_type": "missing_dependency",
        "attributes": {},
    }
    result = report_execution_outcome(event, "mcp-key")
    assert result["status"] == "failed"
    failures = get_known_failures(project["id"], "mcp-key")
    assert len(failures) == 1
    assert failures[0]["error_type"] == "missing_dependency"
    try:
        get_known_failures(project["id"], "wrong-key")
    except ValueError as exc:
        assert "Unauthorized" in str(exc)
    else:
        raise AssertionError("unauthorized MCP request was accepted")


def test_mcp_failure_review_persists_evidence_without_automatic_model_call(tmp_path, monkeypatch):
    client = setup_mcp(tmp_path, monkeypatch)
    project = client.post(
        "/v1/projects",
        headers={"Authorization": "Bearer mcp-key"},
        json={"name": "Review project", "slug": "review-project"},
    ).json()
    event = {
        "event_id": "mcp-review-failure",
        "project_id": project["id"],
        "session_id": str(uuid4()),
        "trace_id": "mcp-review-trace",
        "span_id": "mcp-review-span",
        "agent_type": "codex",
        "event_type": "tool.failed",
        "canonical_action": "RUN_TESTS",
        "native_tool_name": "shell",
        "status": "failed",
        "timestamp": "2026-10-26T14:00:00Z",
        "error_type": "missing_dependency",
        "attributes": {},
    }
    result = report_failure_for_review(
        event,
        "pytest exited because the declared dependency is not installed",
        ["READ_RESOURCE", "RUN_TESTS"],
        False,
        "mcp-key",
    )
    assert result["bedrock_judgment"]["status"] == "not_requested"
    assert result["error_type"] == "missing_dependency"
    assert result["api_target"] is None
    assert get_known_failures(project["id"], "mcp-key")[0]["occurrence_count"] == 1


def test_mcp_failure_review_returns_safe_api_target_and_reason(tmp_path, monkeypatch):
    client = setup_mcp(tmp_path, monkeypatch)
    project = client.post(
        "/v1/projects",
        headers={"Authorization": "Bearer mcp-key"},
        json={"name": "API review", "slug": "api-review"},
    ).json()
    event = {
        "event_id": "mcp-api-failure",
        "project_id": project["id"],
        "session_id": str(uuid4()),
        "trace_id": "mcp-api-trace",
        "span_id": "mcp-api-span",
        "agent_type": "codex",
        "event_type": "tool.failed",
        "canonical_action": "CALL_API",
        "status": "failed",
        "timestamp": "2026-10-26T14:30:00Z",
        "error_type": "http_404",
        "api_url": "https://api.example.test/v1/items/123?token=secret",
    }
    result = report_failure_for_review(
        event, "The API returned HTTP 404 for the requested resource.", [], False, "mcp-key"
    )
    assert result["canonical_action"] == "CALL_API"
    assert result["error_type"] == "http_404"
    assert result["api_target"]["host"] == "api.example.test"
    assert result["api_target"]["path_template"] == "/v1/items/{id}"
    assert "secret" not in str(result)


def test_mcp_failure_review_queues_bedrock_without_waiting(tmp_path, monkeypatch):
    client = setup_mcp(tmp_path, monkeypatch)
    from acil.db import SessionLocal

    with SessionLocal() as db:
        tenant = db.query(Tenant).filter_by(name="MCP Tenant").one()
        tenant.global_learning_enabled = True
        db.commit()
    project = client.post(
        "/v1/projects",
        headers={"Authorization": "Bearer mcp-key"},
        json={"name": "Async judge", "slug": "async-judge"},
    ).json()
    submitted = []
    monkeypatch.setattr(
        "acil.mcp_server.enqueue_global_evaluation", lambda run_id: submitted.append(run_id)
    )
    result = report_failure_for_review(
        {
            "event_id": "async-judge-failure",
            "project_id": project["id"],
            "session_id": str(uuid4()),
            "trace_id": "async-judge-trace",
            "span_id": "async-judge-span",
            "agent_type": "codex",
            "event_type": "tool.failed",
            "canonical_action": "CALL_API",
            "status": "failed",
            "timestamp": "2026-10-27T15:00:00Z",
            "error_type": "http_500",
            "api_url": "https://api.example.test/v1/items/123",
        },
        "The API returned HTTP 500.",
        ["CALL_API"],
        True,
        "mcp-key",
    )
    judgment = result["bedrock_judgment"]
    assert judgment["status"] == "queued"
    assert judgment["run_id"] == str(submitted[0])
    status = get_judge_run_status(judgment["run_id"], "mcp-key")
    assert status["status"] == "QUEUED"
    assert status["passed"] is None


def test_mcp_preflight_risk_returns_allow_without_shared_pattern(tmp_path, monkeypatch):
    client = setup_mcp(tmp_path, monkeypatch)
    project = client.post(
        "/v1/projects",
        headers={"Authorization": "Bearer mcp-key"},
        json={"name": "Risk project", "slug": "risk-project"},
    ).json()
    result = evaluate_action_risk(
        project["id"], "CALL_API", "api_call", None, None, "mcp-key"
    )
    assert result["decision"] == "ALLOW"
