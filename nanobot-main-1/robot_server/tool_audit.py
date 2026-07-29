"""Server-owned durable audit adapter for governed Tool execution."""

from __future__ import annotations

from pathlib import Path

from ai_runtime.tool_runtime import ToolAuditEvent
from robot_platform import _audit_append


class JsonlToolAudit:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def append(self, event: ToolAuditEvent) -> None:
        _audit_append(self._path, {
            "audit_id": event.audit_id,
            "action": event.event,
            "tool_id": event.tool_id,
            "invocation_id": event.invocation_id,
            "actor": event.actor,
            "session_key": event.session_key,
            "parameter_hash": event.parameter_hash,
            "timestamp": event.timestamp,
            "state": event.state,
            "target_device_id": event.target_device_id,
            "device_state_hash": event.device_state_hash,
        })
