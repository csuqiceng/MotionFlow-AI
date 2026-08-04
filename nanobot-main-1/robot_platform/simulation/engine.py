"""Backend-neutral types for an offline robot simulation engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class SimulationSnapshot:
    mode: str
    joints_deg: tuple[float, ...]
    pose_mm_deg: tuple[float, float, float, float, float, float]
    alarms: tuple[str, ...] = ()


@dataclass(frozen=True)
class SimulationOperationResult:
    ok: bool
    state: str
    message: str
    data: dict[str, object] = field(default_factory=dict)
    errors: tuple[dict[str, object], ...] = ()


class SimulationEngine(Protocol):
    """Physics implementation port; it has no controller or permit access."""

    def start(self) -> None: ...
    def close(self) -> None: ...
    def snapshot(self) -> SimulationSnapshot: ...
    def move_joint(self, index: int, delta_deg: float) -> SimulationOperationResult: ...
    def home(self) -> SimulationOperationResult: ...
    def execute(self, command: str, parameters: dict[str, object]) -> SimulationOperationResult: ...
    def stop(self) -> SimulationOperationResult: ...
