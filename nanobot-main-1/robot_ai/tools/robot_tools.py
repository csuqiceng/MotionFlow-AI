from __future__ import annotations

from robot_ai.backends.simulation_backend import SimulationRobotBackend
from robot_ai.models import ToolResult
from robot_ai.safety.policy import SafetyPolicy


class RobotToolFacade:
    def __init__(
        self,
        backend: SimulationRobotBackend | None = None,
        safety_policy: SafetyPolicy | None = None,
    ) -> None:
        self._safety_policy = safety_policy or SafetyPolicy()
        self._backend = backend or SimulationRobotBackend(self._safety_policy)

    def robot_get_status(self) -> dict:
        return ToolResult.success(
            state="status_report",
            message="Robot state retrieved.",
            data={"robot_state": self._backend.get_state().to_dict()},
        ).to_dict()

    def robot_move_axis(self, *, axis: str, delta: float) -> dict:
        return self._backend.move_axis(axis, delta).to_dict()

    def robot_home(self) -> dict:
        return self._backend.home().to_dict()

    def robot_stop(self) -> dict:
        return self._backend.stop().to_dict()

    def robot_explain_limits(self) -> dict:
        limits = {
            axis: {"minimum": limit.minimum, "maximum": limit.maximum}
            for axis, limit in self._safety_policy.axis_limits.items()
        }
        return ToolResult.success(
            state="limits_report",
            message="Robot simulation axis limits retrieved.",
            data={"axis_limits": limits},
        ).to_dict()


_DEFAULT_FACADE = RobotToolFacade()


def robot_get_status() -> dict:
    return _DEFAULT_FACADE.robot_get_status()


def robot_move_axis(*, axis: str, delta: float) -> dict:
    return _DEFAULT_FACADE.robot_move_axis(axis=axis, delta=delta)


def robot_home() -> dict:
    return _DEFAULT_FACADE.robot_home()


def robot_stop() -> dict:
    return _DEFAULT_FACADE.robot_stop()


def robot_explain_limits() -> dict:
    return _DEFAULT_FACADE.robot_explain_limits()
