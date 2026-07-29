from __future__ import annotations

from typing import Any

from robot_platform.models import (
    AXIS_NAMES,
    ControllerCapabilities,
    DEFAULT_SIX_AXIS_MODEL,
    RobotModel,
    RobotState,
    ToolResult,
)
from robot_platform.safety.policy import SafetyPolicy


class SimulationRobotBackend:
    """In-memory robot backend used until a real controller protocol is provided."""

    def __init__(self, safety_policy: SafetyPolicy | None = None) -> None:
        self._safety_policy = safety_policy or SafetyPolicy()
        self._mode = "idle"
        self._axes_mm = {axis: 0.0 for axis in AXIS_NAMES}
        self._alarms: list[str] = []

    @property
    def model(self) -> RobotModel:
        return DEFAULT_SIX_AXIS_MODEL

    @property
    def capabilities(self) -> ControllerCapabilities:
        return ControllerCapabilities(
            vendor="simulation",
            supports_real_writes=False,
            motion_primitives=("axis_move", "home", "stop"),
        )

    def get_state(self) -> RobotState:
        return RobotState(
            mode=self._mode,
            axes_mm=dict(self._axes_mm),
            alarms=list(self._alarms),
            connected_real_device=False,
        )

    def move_axis(self, axis: str, delta: float) -> ToolResult:
        if axis not in self._axes_mm:
            return ToolResult.failure(
                state="motion_rejected",
                message=f"Unknown robot axis: {axis}",
                errors=[{"code": "unknown_axis", "axis": axis}],
            )

        target = self._axes_mm[axis] + float(delta)
        safety = self._safety_policy.validate_axis_target(axis, target)
        if not safety.ok:
            return safety

        self._axes_mm[axis] = target
        self._mode = "idle"
        return ToolResult.success(
            state="simulated_motion_completed",
            message=f"Simulated axis {axis} move completed.",
            data={"axis": axis, "delta": float(delta), "position": target, "robot_state": self.get_state().to_dict()},
        )

    def home(self) -> ToolResult:
        self._axes_mm = {axis: 0.0 for axis in AXIS_NAMES}
        self._mode = "idle"
        return ToolResult.success(
            state="home_completed",
            message="Simulated robot home completed.",
            data={"robot_state": self.get_state().to_dict()},
        )

    def stop(self) -> ToolResult:
        self._mode = "stopped"
        return ToolResult.success(
            state="stopped",
            message="Simulated robot stopped.",
            data={"robot_state": self.get_state().to_dict()},
        )

    def execute_system_action(self, request: Any) -> dict[str, Any]:
        """Reference implementation of the vendor-neutral safety-action port."""
        action = str(getattr(request, "parameters", {}).get("action", ""))
        supported = {
            "emergency_stop",
            "release_emergency_stop",
            "pause",
            "resume",
            "alarm_reset",
            "release_cancel",
            "stop_current",
        }
        if getattr(request, "command", "") != "system" or action not in supported:
            return ToolResult.failure(
                state="simulation_operation_unsupported",
                message="Simulation supports only known system actions through this operator path.",
                errors=[{
                    "code": "simulation_operation_unsupported",
                    "command": getattr(request, "command", ""),
                    "action": action,
                }],
            ).to_dict()
        return ToolResult.success(
            state="simulated_system_action_completed",
            message=f"Simulated system action {action} completed.",
            data={"action": action, "simulation": True},
        ).to_dict()

    def execute_io(self, request: Any) -> dict[str, Any]:
        parameters = getattr(request, "parameters", {})
        channel = parameters.get("io_number") if isinstance(parameters, dict) else None
        enabled = parameters.get("enabled") if isinstance(parameters, dict) else None
        if (
            getattr(request, "command", "") != "io"
            or isinstance(channel, bool) or not isinstance(channel, int)
            or not isinstance(enabled, bool)
        ):
            return ToolResult.failure(
                state="simulation_io_invalid", message="Simulation IO request is invalid.",
                errors=[{"code": "simulation_io_invalid"}],
            ).to_dict()
        return ToolResult.success(
            state="simulated_io_completed", message="Simulated IO completed.",
            data={"io_number": channel, "enabled": enabled, "simulation": True},
        ).to_dict()
