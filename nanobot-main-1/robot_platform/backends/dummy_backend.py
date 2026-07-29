"""Minimal non-product Backend used to prove the extension contract."""

from __future__ import annotations

from typing import Any

from robot_platform.models import (
    ControllerCapabilities,
    DEFAULT_SIX_AXIS_MODEL,
    RobotModel,
    RobotState,
    ToolResult,
)


class DummyRobotBackend:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True
        self.stopped = False

    def shutdown(self) -> None:
        self.stopped = True

    @property
    def model(self) -> RobotModel:
        return DEFAULT_SIX_AXIS_MODEL

    @property
    def capabilities(self) -> ControllerCapabilities:
        return ControllerCapabilities(
            vendor="dummy",
            supports_real_writes=False,
            motion_primitives=("state_read", "stop"),
        )

    def get_state(self) -> RobotState:
        return RobotState(
            mode="idle" if self.started and not self.stopped else "initializing",
            connected_real_device=False,
        )

    def move_axis(self, axis: str, delta: float) -> ToolResult:
        return ToolResult.failure(
            state="dummy_motion_unsupported",
            message="Dummy Backend does not execute motion.",
            data={"axis": axis, "delta": float(delta)},
            errors=[{"code": "dummy_motion_unsupported"}],
        )

    def home(self) -> ToolResult:
        return self.move_axis("home", 0)

    def stop(self) -> ToolResult:
        return ToolResult.success(
            state="dummy_stopped", message="Dummy Backend stopped.",
        )

    def execute_system_action(self, request: Any) -> dict[str, Any]:
        return ToolResult.failure(
            state="dummy_system_unsupported",
            message="Dummy Backend does not execute system actions.",
            errors=[{"code": "dummy_system_unsupported"}],
        ).to_dict()

    def execute_io(self, request: Any) -> dict[str, Any]:
        del request
        return ToolResult.failure(
            state="dummy_io_unsupported",
            message="Dummy Backend does not execute IO.",
            errors=[{"code": "dummy_io_unsupported"}],
        ).to_dict()
