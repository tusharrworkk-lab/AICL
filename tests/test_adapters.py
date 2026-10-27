from uuid import uuid4

from acil.adapters import AdapterContext, normalize_event


def context(agent_type):
    return AdapterContext(uuid4(), uuid4(), "trace-adapter", agent_type)


def test_claude_code_adapter_normalizes_observable_tool_failure():
    event = normalize_event(
        "claude_code",
        {
            "id": "claude-event-1",
            "type": "tool_error",
            "tool_name": "Bash",
            "timestamp": "2026-10-26T15:00:00Z",
            "error_type": "missing_dependency",
        },
        context("claude_code"),
    )
    assert event.event_id == "claude-event-1"
    assert event.status == "failed"
    assert event.canonical_action == "RUN_COMMAND"
    assert event.attributes["provider_event_type"] == "tool_error"


def test_codex_jsonl_item_normalizes_command_execution():
    event = normalize_event(
        "codex",
        {
            "type": "item.completed",
            "item": {
                "id": "codex-item-1",
                "type": "command_execution",
                "command": "pytest",
                "status": "completed",
            },
        },
        context("codex"),
    )
    assert event.event_id == "codex-item-1"
    assert event.status == "ok"
    assert event.canonical_action == "RUN_TESTS"
    assert event.attributes["codex_item_type"] == "command_execution"


def test_generic_adapter_is_deterministic_without_private_reasoning():
    raw = {"type": "tool.completed", "tool_name": "Read", "status": "completed"}
    adapter_context = context("generic")
    first = normalize_event("generic", raw, adapter_context)
    second = normalize_event("generic", raw, adapter_context)
    assert first.event_id == second.event_id
    assert first.canonical_action == "READ_RESOURCE"
