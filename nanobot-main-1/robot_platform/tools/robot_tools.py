from __future__ import annotations

from robot_platform.backends.factory import RobotBackend
from robot_platform.models import ToolResult
from robot_platform.feature_policy import ProductFeaturePolicy
from robot_platform.safety.policy import SafetyPolicy


class RobotToolFacade:
    def __init__(
        self,
        backend: RobotBackend | None = None,
        safety_policy: SafetyPolicy | None = None,
        feature_policy: ProductFeaturePolicy | None = None,
    ) -> None:
        self._safety_policy = safety_policy or SafetyPolicy()
        if backend is None:
            raise RuntimeError("RobotToolFacade requires composition-root Backend injection")
        self._backend = backend
        self._feature_policy = feature_policy or ProductFeaturePolicy()

    def robot_get_status(self) -> dict:
        self._feature_policy.require("robot_arm")
        capabilities = getattr(self._backend, "capabilities", None)
        model = getattr(self._backend, "model", None)
        health = getattr(self._backend, "health", None)
        return ToolResult.success(
            state="status_report",
            message="Robot state retrieved.",
            data={
                "robot_state": self._backend.get_state().to_dict(),
                **(
                    {
                        "backend_health": {
                            "state": str(
                                getattr(getattr(health, "state", ""), "value", "")
                            ),
                            "message": str(getattr(health, "message", "")),
                        },
                    }
                    if health is not None
                    else {}
                ),
                **(
                    {
                        "controller_capabilities": {
                            "vendor": capabilities.vendor,
                            "supports_state_read": capabilities.supports_state_read,
                            "supports_real_writes": capabilities.supports_real_writes,
                            "motion_primitives": list(capabilities.motion_primitives),
                        },
                        "capabilities": capabilities.to_public_dict(),
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

    @property
    def controller_capabilities(self) -> dict[str, object]:
        capabilities = getattr(self._backend, "capabilities", None)
        if capabilities is None:
            return {}
        return dict(capabilities.to_public_dict())

    def robot_move_axis(self, *, axis: str, delta: float) -> dict:
        self._feature_policy.require("robot_arm")
        return self._backend.move_axis(axis, delta).to_dict()

    def robot_home(self) -> dict:
        self._feature_policy.require("robot_arm")
        return self._backend.home().to_dict()

    def robot_stop(self) -> dict:
        self._feature_policy.require("robot_arm")
        return self._backend.stop().to_dict()

    def close(self) -> None:
        close = getattr(self._backend, "close", None)
        if callable(close):
            close()

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


def robot_get_status(*, facade: RobotToolFacade | None = None) -> dict:
    return _injected(facade).robot_get_status()


def robot_move_axis(*, axis: str, delta: float, facade: RobotToolFacade | None = None) -> dict:
    return _injected(facade).robot_move_axis(axis=axis, delta=delta)


def robot_home(*, facade: RobotToolFacade | None = None) -> dict:
    return _injected(facade).robot_home()


def robot_stop(*, facade: RobotToolFacade | None = None) -> dict:
    return _injected(facade).robot_stop()


def _injected(facade: RobotToolFacade | None) -> RobotToolFacade:
    if facade is None:
        raise RuntimeError("Robot tools require composition-root facade injection")
    return facade


def robot_explain_limits(*, facade: RobotToolFacade | None = None) -> dict:
    return _injected(facade).robot_explain_limits()
