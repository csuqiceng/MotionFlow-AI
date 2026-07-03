from __future__ import annotations

from robot_ai.models import AXIS_NAMES, RobotState, ToolResult
from robot_ai.safety.policy import SafetyPolicy


class SimulationRobotBackend:
    """In-memory robot backend used until a real controller protocol is provided."""

    def __init__(self, safety_policy: SafetyPolicy | None = None) -> None:
        self._safety_policy = safety_policy or SafetyPolicy()
        self._mode = "idle"
        self._axes_mm = {axis: 0.0 for axis in AXIS_NAMES}
        self._alarms: list[str] = []

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
