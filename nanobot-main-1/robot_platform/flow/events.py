"""Typed, transport-neutral Flow execution events."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from time import time
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class FlowExecutionEvent:
    execution_id: str
    snapshot_hash: str
    kind: str
    step_index: int = 0
    state: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: uuid4().hex)
    timestamp: float = field(default_factory=time)
    protocol_version: int = 1

    def __post_init__(self) -> None:
        if not str(self.execution_id).strip() or not str(self.kind).strip():
            raise ValueError("Flow event requires execution_id and kind")
        if self.step_index < 0:
            raise ValueError("Flow event step_index cannot be negative")
        if not isinstance(self.payload, dict):
            raise TypeError("Flow event payload must be an object")
        object.__setattr__(self, "payload", deepcopy(self.payload))

    def to_contract_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "event_id": self.event_id,
            "execution_id": self.execution_id,
            "snapshot_hash": self.snapshot_hash,
            "kind": self.kind,
            "step_index": self.step_index,
            "state": self.state,
            "payload": deepcopy(self.payload),
            "timestamp": self.timestamp,
        }
