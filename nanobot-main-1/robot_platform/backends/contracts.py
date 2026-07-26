"""Vendor-neutral contracts shared by robot backend implementations."""

from __future__ import annotations

from typing import Protocol

from robot_platform.models import ControllerCapabilities, RobotModel, RobotState, ToolResult


class RobotBackend(Protocol):
    @property
    def model(self) -> RobotModel:
        ...

    @property
    def capabilities(self) -> ControllerCapabilities:
        ...

    def get_state(self) -> RobotState:
        ...

    def move_axis(self, axis: str, delta: float) -> ToolResult:
        ...

    def home(self) -> ToolResult:
        ...

    def stop(self) -> ToolResult:
        ...
