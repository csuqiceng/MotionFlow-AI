from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


AXIS_NAMES: tuple[str, ...] = ("x", "y", "z", "rx", "ry", "rz")


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    state: str
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def success(cls, *, state: str, message: str = "", data: dict[str, Any] | None = None) -> "ToolResult":
        return cls(ok=True, state=state, message=message, data=dict(data or {}))

    @classmethod
    def failure(
        cls,
        *,
        state: str,
        message: str,
        errors: list[dict[str, Any]] | None = None,
        data: dict[str, Any] | None = None,
    ) -> "ToolResult":
        return cls(
            ok=False,
            state=state,
            message=message,
            data=dict(data or {}),
            errors=list(errors or []),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "state": self.state,
            "message": self.message,
            "data": self.data,
            "errors": self.errors,
        }


@dataclass(frozen=True)
class RobotState:
    mode: str = "idle"
    axes_mm: dict[str, float] = field(default_factory=lambda: {axis: 0.0 for axis in AXIS_NAMES})
    alarms: list[str] = field(default_factory=list)
    connected_real_device: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "axes_mm": dict(self.axes_mm),
            "alarms": list(self.alarms),
            "connected_real_device": self.connected_real_device,
        }
