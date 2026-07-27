"""Vendor-neutral contracts shared by robot backend implementations."""

from __future__ import annotations

from typing import Any, Protocol

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

    def execute_system_action(self, request: Any) -> dict[str, Any]:
        """Run a vendor-neutral emergency/pause/recovery request.

        ``request`` deliberately carries the application-layer confirmation
        proof.  WebUI and Agent callers must use this same backend boundary;
        they must never reach a vendor SDK through a side path.
        """
        ...
