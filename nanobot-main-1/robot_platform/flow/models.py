"""Flow data models: FlowState, FlowStep, FlowEntry.

Ported from the legacy Qt project (``robot_modbus_lite/flow_registry.py``).
Pure data — no Qt, no permission service. A flow is a named, ordered list of
steps; each step maps 1:1 to a restricted ZMotion operator command via its
``func_id`` (108 linear / 104 system / 110 delay / 120 io). Step ``params``
use the new operator's structured shape (``target_pose`` dict, ``speed_pct``
...), not the legacy free-text step descriptions (resolving those needs the
NLP layer, which is intentionally not ported).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class FlowState(Enum):
    IDLE = "idle"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"
    REHEARSAL = "rehearsal"


VALID_TRANSITIONS: dict[FlowState, frozenset[FlowState]] = {
    FlowState.IDLE: frozenset({FlowState.READY, FlowState.REHEARSAL}),
    FlowState.READY: frozenset({FlowState.RUNNING, FlowState.IDLE, FlowState.REHEARSAL}),
    FlowState.RUNNING: frozenset({FlowState.PAUSED, FlowState.COMPLETED, FlowState.ERROR}),
    FlowState.PAUSED: frozenset({FlowState.RUNNING, FlowState.IDLE}),
    FlowState.COMPLETED: frozenset({FlowState.IDLE}),
    FlowState.ERROR: frozenset({FlowState.IDLE}),
    FlowState.REHEARSAL: frozenset({FlowState.IDLE, FlowState.READY}),
}


@dataclass
class FlowStep:
    step_id: int
    action: str
    func_id: int
    params: dict[str, Any] = field(default_factory=dict)
    position_name: str | None = None
    spd_pct: int = 50
    description: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FlowStep":
        return cls(
            step_id=int(payload.get("step_id", 0)),
            action=str(payload.get("action", "")),
            func_id=int(payload.get("func_id", 0)),
            params=dict(payload.get("params", {})),
            position_name=payload.get("position_name"),
            spd_pct=int(payload.get("spd_pct", payload.get("speed_pct", 50))),
            description=str(payload.get("description", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FlowEntry:
    name: str
    flow_id: str = ""
    description: str = ""
    steps: list[FlowStep] = field(default_factory=list)
    node_graph: dict[str, Any] | None = None
    step_delay_ms: int = 1000
    rehearsal_spd: int = 20
    confirmed: bool = False
    created_by: str = "operator"
    version: int = 1
    state: str = FlowState.IDLE.value
    current_step: int = 0
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FlowEntry":
        steps = [FlowStep.from_dict(dict(item)) for item in payload.get("steps", [])]
        return cls(
            name=str(payload.get("name", "")),
            flow_id=str(payload.get("flow_id", "")),
            description=str(payload.get("description", "")),
            steps=steps,
            node_graph=(
                dict(payload["node_graph"])
                if isinstance(payload.get("node_graph"), dict) else None
            ),
            step_delay_ms=int(payload.get("step_delay_ms", 1000)),
            rehearsal_spd=int(payload.get("rehearsal_spd", 20)),
            confirmed=bool(payload.get("confirmed", False)),
            created_by=str(payload.get("created_by", "operator")),
            version=int(payload.get("version", 1)),
            state=str(payload.get("state", FlowState.IDLE.value)),
            current_step=int(payload.get("current_step", 0)),
            created_at=str(payload.get("created_at", "")),
            updated_at=str(payload.get("updated_at", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if not self.flow_id:
            payload.pop("flow_id")
        return payload
