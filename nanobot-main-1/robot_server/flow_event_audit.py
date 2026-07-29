"""Durable Server adapter for typed Flow execution events."""

from __future__ import annotations

from pathlib import Path

from robot_platform import _audit_append
from robot_platform.flow.events import FlowExecutionEvent


class JsonlFlowEventSink:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def append(self, event: FlowExecutionEvent) -> None:
        payload = event.to_contract_dict()
        payload["action"] = "flow_execution_event"
        _audit_append(self._path, payload)
