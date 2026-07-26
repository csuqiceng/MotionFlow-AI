from __future__ import annotations

from robot_platform.backends.factory import RobotBackend
from robot_platform.backends.product_wiring import create_product_robot_backend
from robot_platform.models import ToolResult
from robot_platform.safety.policy import SafetyPolicy


class RobotToolFacade:
    def __init__(
        self,
        backend: RobotBackend | None = None,
        safety_policy: SafetyPolicy | None = None,
    ) -> None:
        self._safety_policy = safety_policy or SafetyPolicy()
        # When no backend is injected, honour ROBOT_AI_BACKEND so the WebUI/tool
        # path can read the real controller (zmotion_readonly) instead of always
        # falling back to simulation.
        self._backend = backend or create_product_robot_backend()

    def robot_get_status(self) -> dict:
        capabilities = getattr(self._backend, "capabilities", None)
        model = getattr(self._backend, "model", None)
        return ToolResult.success(
            state="status_report",
            message="Robot state retrieved.",
            data={
                "robot_state": self._backend.get_state().to_dict(),
                **(
                    {
                        "controller_capabilities": {
                            "vendor": capabilities.vendor,
                            "supports_state_read": capabilities.supports_state_read,
                            "supports_real_writes": capabilities.supports_real_writes,
                            "motion_primitives": list(capabilities.motion_primitives),
                        }
                    }
                    if capabilities is not None
                    else {}
                ),
                **(
                    {
                        "robot_model": {
                            "name": model.name,
                            "axes": list(model.axes),
                            "coordinate_frame": model.coordinate_frame,
                            "position_unit": model.position_unit,
                            "orientation_unit": model.orientation_unit,
                        }
                    }
                    if model is not None
                    else {}
                ),
            },
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


_DEFAULT_FACADE: RobotToolFacade | None = None


def _default_facade() -> RobotToolFacade:
    global _DEFAULT_FACADE
    if _DEFAULT_FACADE is None:
        _DEFAULT_FACADE = RobotToolFacade()
    return _DEFAULT_FACADE


def robot_get_status() -> dict:
    return _default_facade().robot_get_status()


def robot_move_axis(*, axis: str, delta: float) -> dict:
    return _default_facade().robot_move_axis(axis=axis, delta=delta)


def robot_home() -> dict:
    return _default_facade().robot_home()


def robot_stop() -> dict:
    return _default_facade().robot_stop()


def robot_explain_limits() -> dict:
    return _default_facade().robot_explain_limits()
