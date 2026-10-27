from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from acil.auth import hash_api_key
from acil.db import Base, build_engine
from acil.main import app
from acil.models import ApiKey, GlobalEvaluationRun, Tenant


def setup_client(tmp_path, monkeypatch):
    engine = build_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        tenant = Tenant(name="Tenant A")
        db.add(tenant)
        db.flush()
        db.add(ApiKey(tenant_id=tenant.id, key_hash=hash_api_key("key-a")))
        other = Tenant(name="Tenant B")
        db.add(other)
        db.flush()
        db.add(ApiKey(tenant_id=other.id, key_hash=hash_api_key("key-b")))
        db.commit()
    monkeypatch.setattr("acil.db.SessionLocal", Session)
    return TestClient(app)


def test_health():
    assert TestClient(app).get("/health").json()["status"] == "ok"


def test_openapi_declares_bearer_auth_for_docs():
    schema = TestClient(app).get("/openapi.json").json()
    assert schema["components"]["securitySchemes"]["ACILBearerAuth"]["scheme"] == "bearer"


def test_console_is_public_but_project_events_remain_tenant_scoped(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    assert client.get("/").status_code == 200
    headers = {"Authorization": "Bearer key-a"}
    project = client.post(
        "/v1/projects", headers=headers, json={"name": "Console", "slug": "console"}
    ).json()
    event = {
        "event_id": "console-event",
        "project_id": project["id"],
        "session_id": str(uuid4()),
        "trace_id": "console-trace",
        "span_id": "console-span",
        "agent_type": "test-agent",
        "event_type": "tool.completed",
        "canonical_action": "READ_RESOURCE",
        "status": "ok",
        "timestamp": "2026-10-26T10:00:00Z",
    }
    assert client.post("/v1/events", headers=headers, json=event).status_code == 201
    visible = client.get(f"/v1/projects/{project['id']}/events", headers=headers)
    assert visible.status_code == 200
    assert visible.json()[0]["event_id"] == "console-event"
    assert (
        client.get(
            f"/v1/projects/{project['id']}/events", headers={"Authorization": "Bearer key-b"}
        ).status_code
        == 404
    )


def test_judge_status_requires_tenant_authentication(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    assert client.get("/v1/judge/status").status_code == 401
    status = client.get(
        "/v1/judge/status", headers={"Authorization": "Bearer key-a"}
    )
    assert status.status_code == 200
    assert "google_application_credentials" not in status.text
    assert status.json()["provider"] == "amazon_bedrock"
    assert "credential_source" in status.json()


def test_negative_case_analysis_is_visible_only_to_owning_tenant(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    headers_a = {"Authorization": "Bearer key-a"}
    client.post("/v1/tenant/learning", headers=headers_a, json={"enabled": True})
    project = client.post(
        "/v1/projects", headers=headers_a, json={"name": "Negative case", "slug": "negative-case"}
    ).json()
    client.post(
        "/v1/events",
        headers=headers_a,
        json={
            "event_id": "negative-case-event",
            "project_id": project["id"],
            "session_id": str(uuid4()),
            "trace_id": "negative-case-trace",
            "span_id": "negative-case-span",
            "agent_type": "generic",
            "event_type": "tool.failed",
            "canonical_action": "RUN_TESTS",
            "status": "failed",
            "timestamp": "2026-10-26T17:00:00Z",
            "error_type": "missing_dependency",
        },
    )
    definition = client.get("/v1/global/evaluations", headers=headers_a).json()[0]
    from acil.db import SessionLocal

    with SessionLocal() as db:
        tenant_a = db.query(Tenant).filter_by(name="Tenant A").one()
        db.add(
            GlobalEvaluationRun(
                definition_id=UUID(definition["id"]),
                tenant_id=tenant_a.id,
                judge_provider="bedrock",
                status="FAILED",
                passed=False,
                metrics={
                    "negative_case_analysis": [
                        {
                            "failure_case": "test environment unavailable",
                            "likely_cause": "dependency missing",
                            "confidence": 80,
                            "observed_facts": ["RUN_TESTS failed"],
                            "impact": "test execution blocked",
                            "recommended_next_actions": ["inspect dependencies"],
                        }
                    ]
                },
                blockers=["journey_outcome_not_success"],
            )
        )
        db.commit()
    own = client.get("/v1/negative-cases", headers=headers_a)
    assert own.status_code == 200
    assert own.json()[0]["analysis"][0]["likely_cause"] == "dependency missing"
    other = client.get("/v1/negative-cases", headers={"Authorization": "Bearer key-b"})
    assert other.status_code == 200
    assert other.json() == []


def test_project_auth_and_tenant_scope(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    assert client.get("/v1/projects").status_code == 401
    response = client.post(
        "/v1/projects",
        headers={"Authorization": "Bearer key-a"},
        json={"name": "Demo", "slug": "demo"},
    )
    assert response.status_code == 201
    assert (
        client.get("/v1/projects", headers={"Authorization": "Bearer key-a"}).json()[0]["slug"]
        == "demo"
    )
    project_id = response.json()["id"]
    assert (
        client.get(
            f"/v1/projects/{project_id}", headers={"Authorization": "Bearer key-b"}
        ).status_code
        == 404
    )


def test_event_batch_is_idempotent_and_trace_is_ordered(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    headers = {"Authorization": "Bearer key-a"}
    project = client.post(
        "/v1/projects", headers=headers, json={"name": "Trace", "slug": "trace"}
    ).json()
    session_id = str(uuid4())
    base = {
        "project_id": project["id"],
        "session_id": session_id,
        "trace_id": "trace-1",
        "agent_type": "generic",
        "event_type": "tool.failed",
        "canonical_action": "RUN_TESTS",
        "native_tool_name": "shell",
        "status": "failed",
        "duration_ms": 10,
        "error_type": "missing_dependency",
        "attributes": {"api_token": "do-not-store"},
    }
    events = [
        {**base, "event_id": "e-2", "span_id": "s-2", "timestamp": "2026-10-26T10:00:02Z"},
        {
            **base,
            "event_id": "e-1",
            "span_id": "s-1",
            "timestamp": "2026-10-26T10:00:01Z",
            "status": "ok",
            "event_type": "tool.completed",
        },
    ]
    response = client.post("/v1/events/batch", headers=headers, json={"events": events})
    assert response.status_code == 201
    assert response.json()[0]["attributes"]["api_token"] == "[REDACTED]"
    duplicate = client.post("/v1/events", headers=headers, json=events[0])
    assert duplicate.status_code == 201
    trace = client.get(f"/v1/sessions/{session_id}/trace", headers=headers)
    assert [item["event_id"] for item in trace.json()] == ["e-1", "e-2"]


def test_failures_group_by_observed_fingerprint_and_are_tenant_scoped(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    headers = {"Authorization": "Bearer key-a"}
    project = client.post(
        "/v1/projects", headers=headers, json={"name": "Failures", "slug": "failures"}
    ).json()
    common = {
        "project_id": project["id"],
        "trace_id": "trace-failure",
        "agent_type": "codex",
        "event_type": "tool.failed",
        "canonical_action": "RUN_TESTS",
        "native_tool_name": "shell",
        "status": "failed",
        "error_type": "missing_dependency",
        "attributes": {
            "environment_fingerprint": "python-3.12",
            "tool_capabilities": ["shell", "filesystem"],
        },
    }
    first = {
        **common,
        "event_id": "failure-1",
        "session_id": str(uuid4()),
        "span_id": "span-1",
        "timestamp": "2026-10-26T11:00:00Z",
    }
    second = {
        **common,
        "event_id": "failure-2",
        "session_id": str(uuid4()),
        "span_id": "span-2",
        "timestamp": "2026-10-26T11:01:00Z",
    }
    assert client.post("/v1/events", headers=headers, json=first).status_code == 201
    assert client.post("/v1/events", headers=headers, json=second).status_code == 201
    failures = client.get("/v1/failures", headers=headers)
    assert failures.status_code == 200
    assert len(failures.json()) == 1
    pattern = failures.json()[0]
    assert pattern["occurrence_count"] == 2
    assert len(pattern["occurrences"]) == 2
    assert pattern["error_type"] == "missing_dependency"
    assert client.get("/v1/failures", headers={"Authorization": "Bearer key-b"}).json() == []


def test_evaluation_controls_strategy_promotion(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    headers = {"Authorization": "Bearer key-a"}
    project = client.post(
        "/v1/projects", headers=headers, json={"name": "Learning", "slug": "learning"}
    ).json()
    event = {
        "event_id": "learning-failure",
        "project_id": project["id"],
        "session_id": str(uuid4()),
        "trace_id": "learning-trace",
        "span_id": "learning-span",
        "agent_type": "claude_code",
        "event_type": "tool.failed",
        "canonical_action": "RUN_TESTS",
        "native_tool_name": "shell",
        "status": "failed",
        "timestamp": "2026-10-26T12:00:00Z",
        "error_type": "missing_dependency",
        "attributes": {"environment_fingerprint": "python-3.12"},
    }
    assert client.post("/v1/events", headers=headers, json=event).status_code == 201
    evaluation = client.get("/v1/evaluations", headers=headers).json()[0]
    strategy = client.get("/v1/strategies", headers=headers).json()[0]
    assert strategy["status"] == "CANDIDATE"
    failed = client.post(
        f"/v1/evaluations/{evaluation['id']}/run",
        headers=headers,
        json={
            "observed_actions": ["RUN_TESTS"],
            "outcome": "failure",
            "evidence": {"kind": "test"},
        },
    )
    assert failed.status_code == 201
    assert failed.json()["passed"] is False
    assert (
        client.get(f"/v1/strategies/{strategy['id']}", headers=headers).json()["status"]
        == "CANDIDATE"
    )
    passed = client.post(
        f"/v1/evaluations/{evaluation['id']}/run",
        headers=headers,
        json={
            "observed_actions": ["CHECK_DEPENDENCIES", "PREPARE_ENVIRONMENT", "RUN_TESTS"],
            "outcome": "success",
            "evidence": {"kind": "controlled-evaluation"},
        },
    )
    assert passed.status_code == 201
    assert passed.json()["passed"] is True
    validated = client.get(f"/v1/strategies/{strategy['id']}", headers=headers).json()
    assert validated["status"] == "VALIDATED"
    assert validated["validation_status"] == "VALIDATED"
    activated = client.post(f"/v1/strategies/{strategy['id']}/activate", headers=headers)
    assert activated.status_code == 200
    assert activated.json()["status"] == "ACTIVE"


def test_context_compiler_returns_only_applicable_active_knowledge(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    headers = {"Authorization": "Bearer key-a"}
    project = client.post(
        "/v1/projects", headers=headers, json={"name": "Context", "slug": "context"}
    ).json()
    event = {
        "event_id": "context-failure",
        "project_id": project["id"],
        "session_id": str(uuid4()),
        "trace_id": "context-trace",
        "span_id": "context-span",
        "agent_type": "codex",
        "event_type": "tool.failed",
        "canonical_action": "RUN_TESTS",
        "native_tool_name": "shell",
        "status": "failed",
        "timestamp": "2026-10-26T13:00:00Z",
        "error_type": "missing_dependency",
        "attributes": {"environment_fingerprint": "python-3.12"},
    }
    client.post("/v1/events", headers=headers, json=event)
    evaluation = client.get("/v1/evaluations", headers=headers).json()[0]
    strategy = client.get("/v1/strategies", headers=headers).json()[0]
    client.post(
        f"/v1/evaluations/{evaluation['id']}/run",
        headers=headers,
        json={
            "observed_actions": ["CHECK_DEPENDENCIES", "PREPARE_ENVIRONMENT", "RUN_TESTS"],
            "outcome": "success",
            "evidence": {"source": "test"},
        },
    )
    client.post(f"/v1/strategies/{strategy['id']}/activate", headers=headers)
    context = client.post(
        "/v1/context/compile",
        headers=headers,
        json={
            "project_id": project["id"],
            "task_type": "fix_tests",
            "agent_type": "codex",
            "failure_type": "missing_dependency",
            "canonical_action": "RUN_TESTS",
            "environment_fingerprint": "python-3.12",
            "render_markdown": True,
        },
    )
    assert context.status_code == 200
    package = context.json()
    assert len(package["recommended_strategies"]) == 1
    assert package["recommended_strategies"][0]["validation_status"] == "ACTIVE"
    assert "verify_test_environment" in package["markdown"]
    mismatch = client.post(
        "/v1/context/compile",
        headers=headers,
        json={
            "project_id": project["id"],
            "task_type": "fix_tests",
            "agent_type": "codex",
            "failure_type": "missing_dependency",
            "environment_fingerprint": "python-3.13",
        },
    )
    assert mismatch.json()["recommended_strategies"] == []
    assert (
        client.post(
            "/v1/context/compile",
            headers={"Authorization": "Bearer key-b"},
            json={"project_id": project["id"], "task_type": "fix_tests", "agent_type": "codex"},
        ).status_code
        == 404
    )


def test_opt_in_global_recurrence_shares_only_deidentified_aggregates(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    key_a = {"Authorization": "Bearer key-a"}
    key_b = {"Authorization": "Bearer key-b"}
    client.post("/v1/tenant/learning", headers=key_a, json={"enabled": True})
    project_a = client.post("/v1/projects", headers=key_a, json={"name": "A", "slug": "a"}).json()
    event_base = {
        "trace_id": "global-trace",
        "agent_type": "generic",
        "event_type": "tool.failed",
        "canonical_action": "RUN_TESTS",
        "native_tool_name": "shell",
        "status": "failed",
        "timestamp": "2026-10-26T16:00:00Z",
        "error_type": "missing_dependency",
        "attributes": {"secret_token": "must-not-cross-tenant"},
    }
    event_a = {
        **event_base,
        "event_id": "global-a",
        "project_id": project_a["id"],
        "session_id": str(uuid4()),
        "span_id": "a",
    }
    client.post("/v1/events", headers=key_a, json=event_a)
    first = client.get("/v1/global/failures", headers=key_b).json()
    assert len(first) == 1
    assert first[0]["source_tenant_count"] == 1
    assert "secret_token" not in first[0]
    project_b = client.post("/v1/projects", headers=key_b, json={"name": "B", "slug": "b"}).json()
    client.post("/v1/tenant/learning", headers=key_b, json={"enabled": True})
    event_b = {
        **event_base,
        "event_id": "global-b",
        "project_id": project_b["id"],
        "session_id": str(uuid4()),
        "span_id": "b",
    }
    client.post("/v1/events", headers=key_b, json=event_b)
    second = client.get("/v1/global/failures", headers=key_a).json()
    assert second[0]["recurrence_count"] == 2
    assert second[0]["source_tenant_count"] == 2


def test_global_judge_reports_blockers_and_promotes_shared_strategy(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    headers = {"Authorization": "Bearer key-a"}
    client.post("/v1/tenant/learning", headers=headers, json={"enabled": True})
    project = client.post(
        "/v1/projects", headers=headers, json={"name": "Global Eval", "slug": "global-eval"}
    ).json()
    event = {
        "event_id": "global-eval-failure",
        "project_id": project["id"],
        "session_id": str(uuid4()),
        "trace_id": "global-eval-trace",
        "span_id": "global-eval-span",
        "agent_type": "generic",
        "event_type": "tool.failed",
        "canonical_action": "RUN_TESTS",
        "native_tool_name": "shell",
        "status": "failed",
        "timestamp": "2026-10-26T17:00:00Z",
        "error_type": "missing_dependency",
        "attributes": {"environment_fingerprint": "python-3.12"},
    }
    client.post("/v1/events", headers=headers, json=event)
    evaluation = client.get("/v1/global/evaluations", headers=headers).json()[0]
    failed = client.post(
        f"/v1/global/evaluations/{evaluation['id']}/run",
        headers=headers,
        json={"observed_actions": ["RUN_TESTS"], "outcome": "failure", "evidence": {}},
    ).json()
    assert failed["passed"] is False
    assert failed["blockers"]
    passed = client.post(
        f"/v1/global/evaluations/{evaluation['id']}/run",
        headers=headers,
        json={
            "observed_actions": ["CHECK_DEPENDENCIES", "PREPARE_ENVIRONMENT", "RUN_TESTS"],
            "outcome": "success",
            "evidence": {"fixture": "controlled"},
        },
    ).json()
    assert passed["passed"] is True
    strategy = client.get("/v1/global/strategies", headers=headers).json()[0]
    assert strategy["validation_status"] == "VALIDATED"
    activated = client.post(
        f"/v1/global/strategies/{strategy['id']}/activate", headers=headers
    ).json()
    assert activated["validation_status"] == "ACTIVE"


def test_preflight_risk_requires_confirmation_for_recurrent_shared_failure(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    headers_a = {"Authorization": "Bearer key-a"}
    headers_b = {"Authorization": "Bearer key-b"}
    client.post("/v1/tenant/learning", headers=headers_a, json={"enabled": True})
    client.post("/v1/tenant/learning", headers=headers_b, json={"enabled": True})
    project_a = client.post(
        "/v1/projects", headers=headers_a, json={"name": "A risk", "slug": "a-risk"}
    ).json()
    project_b = client.post(
        "/v1/projects", headers=headers_b, json={"name": "B risk", "slug": "b-risk"}
    ).json()
    for index in range(3):
        response = client.post(
            "/v1/events",
            headers=headers_a,
            json={
                "event_id": f"shared-risk-{index}",
                "project_id": project_a["id"],
                "session_id": str(uuid4()),
                "trace_id": f"shared-risk-trace-{index}",
                "span_id": f"shared-risk-span-{index}",
                "agent_type": "generic",
                "event_type": "tool.failed",
                "canonical_action": "CALL_WEATHER_API",
                "native_tool_name": "http",
                "status": "failed",
                "timestamp": f"2026-10-26T17:00:0{index}Z",
                "error_type": "dns_resolution",
                "attributes": {
                    "api_url": "https://weather.example.test/v1/forecast?token=not-stored"
                },
            },
        )
        assert response.status_code == 201
    risk = client.post(
        "/v1/risk/evaluate",
        headers=headers_b,
        json={
            "project_id": project_b["id"],
            "canonical_action": "API_REQUEST",
            "error_type": "dns_resolution",
            "api_url": "https://weather.example.test/v1/forecast?token=not-exposed",
        },
    )
    assert risk.status_code == 200
    result = risk.json()
    assert result["decision"] == "REQUIRE_CONFIRMATION"
    assert result["requires_user_confirmation"] is True
    assert result["matched_patterns"][0]["recurrence_count"] == 3
    assert result["matched_patterns"][0]["api_target_matched"] is True
    assert "project_id" not in str(result)
    assert "weather.example.test" not in str(result)
