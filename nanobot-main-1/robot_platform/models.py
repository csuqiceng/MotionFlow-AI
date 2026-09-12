from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


AXIS_NAMES: tuple[str, ...] = ("x", "y", "z", "rx", "ry", "rz")


@dataclass(frozen=True)
class RobotModel:
    """A mechanical model profile; it is not a controller-vendor contract."""

    name: str
    axes: tuple[str, ...]
    coordinate_frame: str = "cartesian"
    position_unit: str = "mm"
    orientation_unit: str = "deg"


@dataclass(frozen=True)
class ControllerCapabilities:
    """Explicit controller abilities used by service/AI planning boundaries."""

    vendor: str
    supports_state_read: bool = True
    supports_real_writes: bool = False
    motion_primitives: tuple[str, ...] = ()

    def to_public_dict(self) -> dict[str, object]:
        """Return the versioned, vendor-neutral capability contract.

        ``vendor`` is intentionally excluded: product code must select behavior
        from declared abilities rather than a backend identity.
        """
        return {
            "protocol_version": 1,
            "supports_state_read": self.supports_state_read,
            "supports_real_writes": self.supports_real_writes,
            "motion_primitives": list(self.motion_primitives),
        }


DEFAULT_SIX_AXIS_MODEL = RobotModel(name="legacy-six-axis", axes=AXIS_NAMES)


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
    # Actual J1..J6 feedback. Backends without joint telemetry leave this
    # empty so the UI renders an honest unavailable value rather than zero.
    joints_deg: list[float] = field(default_factory=list)
    alarms: list[str] = field(default_factory=list)
    connected_real_device: bool = False
    cancel_latch: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "axes_mm": dict(self.axes_mm),
            "joints_deg": list(self.joints_deg),
            "alarms": list(self.alarms),
            "connected_real_device": self.connected_real_device,
            "cancel_latch": self.cancel_latch,
        }
