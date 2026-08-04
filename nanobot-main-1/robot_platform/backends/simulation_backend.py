from __future__ import annotations

from typing import Any

from robot_platform.models import (
    AXIS_NAMES,
    DEFAULT_SIX_AXIS_MODEL,
    ControllerCapabilities,
    RobotModel,
    RobotState,
    ToolResult,
)
from robot_platform.safety.policy import SafetyPolicy
from robot_platform.simulation.catalog import SimulationModelError, load_simulation_model
from robot_platform.simulation.engine import SimulationEngine, SimulationOperationResult
from robot_platform.simulation.pybullet_engine import PyBulletSimulationEngine


class SimulationRobotBackend:
    """Legacy deterministic backend retained for minimal controller-free deployments."""

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
        return ControllerCapabilities(vendor="simulation", supports_real_writes=False, motion_primitives=("axis_move", "home", "stop"))

    def get_state(self) -> RobotState:
        return RobotState(mode=self._mode, axes_mm=dict(self._axes_mm), alarms=list(self._alarms), connected_real_device=False)

    def move_axis(self, axis: str, delta: float) -> ToolResult:
        if axis not in self._axes_mm:
            return ToolResult.failure(state="motion_rejected", message=f"Unknown robot axis: {axis}", errors=[{"code": "unknown_axis", "axis": axis}])
        target = self._axes_mm[axis] + float(delta)
        safety = self._safety_policy.validate_axis_target(axis, target)
        if not safety.ok:
            return safety
        self._axes_mm[axis] = target
        self._mode = "idle"
        return ToolResult.success(state="simulated_motion_completed", message=f"Simulated axis {axis} move completed.", data={"axis": axis, "delta": float(delta), "position": target, "robot_state": self.get_state().to_dict()})

    def home(self) -> ToolResult:
        self._axes_mm = {axis: 0.0 for axis in AXIS_NAMES}
        self._mode = "idle"
        return ToolResult.success(state="home_completed", message="Simulated robot home completed.", data={"robot_state": self.get_state().to_dict()})

    def stop(self) -> ToolResult:
        self._mode = "stopped"
        return ToolResult.success(state="stopped", message="Simulated robot stopped.", data={"robot_state": self.get_state().to_dict()})

    def execute_system_action(self, request: Any) -> dict[str, Any]:
        action = str(getattr(request, "parameters", {}).get("action", ""))
        supported = {"emergency_stop", "release_emergency_stop", "pause", "resume", "alarm_reset", "release_cancel", "stop_current"}
        if getattr(request, "command", "") != "system" or action not in supported:
            return ToolResult.failure(state="simulation_operation_unsupported", message="Simulation supports only known system actions through this operator path.", errors=[{"code": "simulation_operation_unsupported", "command": getattr(request, "command", ""), "action": action}]).to_dict()
        return ToolResult.success(state="simulated_system_action_completed", message=f"Simulated system action {action} completed.", data={"action": action, "simulation": True}).to_dict()

    def execute_io(self, request: Any) -> dict[str, Any]:
        parameters = getattr(request, "parameters", {})
        channel = parameters.get("io_number") if isinstance(parameters, dict) else None
        enabled = parameters.get("enabled") if isinstance(parameters, dict) else None
        if getattr(request, "command", "") != "io" or isinstance(channel, bool) or not isinstance(channel, int) or not isinstance(enabled, bool):
            return ToolResult.failure(state="simulation_io_invalid", message="Simulation IO request is invalid.", errors=[{"code": "simulation_io_invalid"}]).to_dict()
        return ToolResult.success(state="simulated_io_completed", message="Simulated IO completed.", data={"io_number": channel, "enabled": enabled, "simulation": True}).to_dict()


class PyBulletSimulationBackend:
    """Offline PyBullet adapter.  It never owns a real controller connection."""

    def __init__(
        self,
        safety_policy: SafetyPolicy | None = None,
        *,
        model_id: str = "generic-six-axis",
        engine: SimulationEngine | None = None,
    ) -> None:
        self._safety_policy = safety_policy or SafetyPolicy()
        self._mode = "idle"
        self._axes_mm = {axis: 0.0 for axis in AXIS_NAMES}
        self._alarms: list[str] = []
        self._model_id = model_id
        self._engine = engine
        self._engine_failure = ""

    @property
    def model(self) -> RobotModel:
        return RobotModel(name=self._model_id or DEFAULT_SIX_AXIS_MODEL.name, axes=AXIS_NAMES)

    @property
    def capabilities(self) -> ControllerCapabilities:
        return ControllerCapabilities(
            vendor="simulation",
            supports_real_writes=False,
            motion_primitives=("axis_move", "home", "stop"),
        )

    def get_state(self) -> RobotState:
        snapshot = self._snapshot()
        if snapshot is not None:
            pose = snapshot.pose_mm_deg
            self._mode = snapshot.mode
            self._axes_mm = dict(zip(AXIS_NAMES, pose, strict=True))
            return RobotState(
                mode=self._mode, axes_mm=dict(self._axes_mm), joints_deg=list(snapshot.joints_deg),
                alarms=list(self._alarms), connected_real_device=False,
            )
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

        del delta
        return ToolResult.failure(
            state="simulation_cartesian_axis_unsupported",
            message="PyBullet simulation requires a full Cartesian target pose, not a single axis delta.",
            errors=[{"code": "simulation_cartesian_axis_unsupported", "axis": axis}],
        )

    def home(self) -> ToolResult:
        engine = self._ensure_engine()
        if engine is None:
            return self._engine_error()
        result = engine.home()
        return _tool_result(result, success_state="home_completed")

    def stop(self) -> ToolResult:
        engine = self._ensure_engine()
        if engine is None:
            return self._engine_error()
        return _tool_result(engine.stop(), success_state="stopped")

    def start(self) -> None:
        engine = self._ensure_engine()
        if engine is None:
            raise RuntimeError(self._engine_failure or "simulation_engine_start_failed")

    def shutdown(self) -> None:
        if self._engine is not None:
            self._engine.close()

    def close(self) -> None:
        self.shutdown()

    def execute_operation(self, request: Any) -> dict[str, Any]:
        """Run an offline flow operation with no permit or controller access."""
        if bool(getattr(request, "execute_real", False)):
            return ToolResult.failure(
                state="simulation_real_execution_rejected",
                message="PyBullet simulation cannot execute a real operation.",
                errors=[{"code": "simulation_real_execution_rejected"}],
            ).to_dict()
        engine = self._ensure_engine()
        if engine is None:
            return self._engine_error().to_dict()
        command = str(getattr(request, "command", ""))
        if command == "system":
            return self.execute_system_action(request)
        if command == "io":
            return self.execute_io(request)
        if command not in {"linear_move", "delay"}:
            return ToolResult.failure(
                state="simulation_operation_unsupported", message="Simulation command is not supported.",
                errors=[{"code": "simulation_operation_unsupported", "command": command}],
            ).to_dict()
        parameters = getattr(request, "parameters", {})
        if not isinstance(parameters, dict):
            return ToolResult.failure(
                state="simulation_parameters_invalid", message="Simulation parameters are invalid.",
                errors=[{"code": "simulation_parameters_invalid"}],
            ).to_dict()
        return _tool_result(engine.execute(command, parameters)).to_dict()

    def _ensure_engine(self) -> SimulationEngine | None:
        if self._engine is not None:
            try:
                self._engine.start()
                return self._engine
            except RuntimeError as exc:
                self._engine_failure = str(exc)
                return None
        try:
            model = load_simulation_model(self._model_id)
            engine = PyBulletSimulationEngine(model)
            engine.start()
            self._engine = engine
            return engine
        except (SimulationModelError, RuntimeError) as exc:
            self._engine_failure = str(exc)
            return None

    def _snapshot(self):
        engine = self._ensure_engine()
        if engine is None:
            if self._engine_failure:
                self._alarms = [self._engine_failure]
            return None
        return engine.snapshot()

    def _engine_error(self) -> ToolResult:
        code = self._engine_failure.split(":", 1)[0] or "simulation_engine_unavailable"
        return ToolResult.failure(
            state=code, message="PyBullet simulation engine is unavailable.",
            errors=[{"code": code}],
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


def _tool_result(result: SimulationOperationResult, *, success_state: str | None = None) -> ToolResult:
    if result.ok:
        return ToolResult.success(state=success_state or result.state, message=result.message, data=result.data)
    return ToolResult.failure(state=result.state, message=result.message, data=result.data, errors=list(result.errors))
