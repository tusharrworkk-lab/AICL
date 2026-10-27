"""Provider-neutral normalization for observable coding-agent event streams."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from acil.schemas import EventIn


@dataclass(frozen=True)
class AdapterContext:
    project_id: UUID
    session_id: UUID
    trace_id: str
    agent_type: str


class EventAdapter(Protocol):
    def normalize(self, raw: dict[str, Any], context: AdapterContext) -> EventIn: ...


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return datetime.now(UTC)


def _event_id(raw: dict[str, Any], context: AdapterContext) -> str:
    value = raw.get("event_id") or raw.get("id") or raw.get("eventId")
    if value:
        return str(value)
    encoded = json.dumps(raw, sort_keys=True, default=str, separators=(",", ":")).encode()
    return hashlib.sha256(f"{context.session_id}:".encode() + encoded).hexdigest()


def _status(raw: dict[str, Any], failed: bool = False) -> str:
    if failed or raw.get("is_error") is True or raw.get("error"):
        return "failed"
    value = str(raw.get("status") or raw.get("state") or "completed").lower()
    return "failed" if value in {"error", "failed", "failure"} else "ok"


def _canonical_action(tool_name: str | None, event_type: str | None) -> str:
    value = f"{tool_name or ''} {event_type or ''}".lower()
    if any(item in value for item in ("test", "command_execution", "bash", "shell")):
        return "RUN_TESTS" if "test" in value else "RUN_COMMAND"
    if any(item in value for item in ("write", "edit", "patch", "modify")):
        return "MODIFY_RESOURCE"
    if any(item in value for item in ("read", "cat", "file")):
        return "READ_RESOURCE"
    return "OBSERVE"


class GenericJsonAdapter:
    def normalize(self, raw: dict[str, Any], context: AdapterContext) -> EventIn:
        event_type = str(raw.get("event_type") or raw.get("type") or "agent.event")
        tool_name = raw.get("native_tool_name") or raw.get("tool_name") or raw.get("tool")
        return EventIn(
            event_id=_event_id(raw, context),
            project_id=context.project_id,
            session_id=context.session_id,
            trace_id=str(raw.get("trace_id") or context.trace_id),
            span_id=str(raw.get("span_id") or _event_id(raw, context)),
            parent_span_id=raw.get("parent_span_id"),
            agent_type=context.agent_type,
            event_type=event_type,
            canonical_action=str(
                raw.get("canonical_action") or _canonical_action(tool_name, event_type)
            ),
            native_tool_name=str(tool_name) if tool_name else None,
            status=_status(raw),
            timestamp=_timestamp(raw.get("timestamp") or raw.get("created_at")),
            duration_ms=raw.get("duration_ms"),
            error_type=raw.get("error_type"),
            attributes=raw.get("attributes") or {},
        )


class ClaudeCodeAdapter(GenericJsonAdapter):
    """Normalize observable Claude Code stream/hook JSON without model reasoning."""

    def normalize(self, raw: dict[str, Any], context: AdapterContext) -> EventIn:
        event = dict(raw)
        event_type = str(event.get("type") or event.get("event_type") or "claude.event")
        event["event_type"] = event_type
        event["tool_name"] = event.get("tool_name") or event.get("name") or event.get("tool")
        event["is_error"] = event.get("is_error", event_type in {"tool_error", "error"})
        event["attributes"] = {
            **(event.get("attributes") or {}),
            "provider_event_type": event_type,
        }
        return super().normalize(event, context)


class CodexAdapter(GenericJsonAdapter):
    """Normalize observable Codex CLI JSONL item events."""

    def normalize(self, raw: dict[str, Any], context: AdapterContext) -> EventIn:
        item = raw.get("item") if isinstance(raw.get("item"), dict) else raw
        event = dict(item)
        event_type = str(raw.get("type") or event.get("type") or "codex.event")
        item_type = str(event.get("type") or event_type)
        event["event_type"] = event_type
        event["tool_name"] = event.get("tool_name") or event.get("command") or item_type
        event["is_error"] = event.get("is_error", event.get("status") in {"failed", "error"})
        event["attributes"] = {
            **(event.get("attributes") or {}),
            "provider_event_type": event_type,
            "codex_item_type": item_type,
        }
        return super().normalize(event, context)


ADAPTERS: dict[str, EventAdapter] = {
    "generic": GenericJsonAdapter(),
    "claude_code": ClaudeCodeAdapter(),
    "codex": CodexAdapter(),
}


def normalize_event(adapter: str, raw: dict[str, Any], context: AdapterContext) -> EventIn:
    try:
        selected = ADAPTERS[adapter]
    except KeyError as exc:
        raise ValueError(f"Unsupported adapter: {adapter}") from exc
    return selected.normalize(raw, context)
