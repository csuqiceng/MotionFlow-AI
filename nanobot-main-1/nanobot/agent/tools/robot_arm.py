from __future__ import annotations

import json
from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from robot_ai.models import ToolResult
from robot_ai.tools.robot_tools import RobotToolFacade


_PARAMETERS = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["status", "move_axis", "home", "stop", "explain_limits"],
            "description": "Robot action to perform. Motion actions are simulated until a real controller is configured.",
        },
        "axis": {
            "type": "string",
            "enum": ["x", "y", "z", "rx", "ry", "rz"],
            "description": "Axis to move when action is move_axis.",
        },
        "delta": {
            "type": "number",
            "description": "Relative movement amount for move_axis.",
        },
    },
    "required": ["action"],
    "additionalProperties": False,
}


@tool_parameters(_PARAMETERS)
class RobotArmTool(Tool):
    def __init__(self, facade: RobotToolFacade | None = None) -> None:
        self._facade = facade or RobotToolFacade()

    @property
    def name(self) -> str:
        return "robot_arm"

    @property
    def description(self) -> str:
        return (
            "Control or inspect the simulated factory robot arm. "
            "Use status/explain_limits for read operations, and move_axis/home/stop for simulated actions. "
            "Safety refusals are returned as structured JSON."
        )

    @property
    def read_only(self) -> bool:
        return False

    @property
    def exclusive(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        action = str(kwargs.get("action") or "").strip()

        if action == "status":
            result = self._facade.robot_get_status()
        elif action == "move_axis":
            result = self._move_axis(kwargs)
        elif action == "home":
            result = self._facade.robot_home()
        elif action == "stop":
            result = self._facade.robot_stop()
        elif action == "explain_limits":
            result = self._facade.robot_explain_limits()
        else:
            result = ToolResult.failure(
                state="unknown_robot_action",
                message=f"Unknown robot action: {action}",
                errors=[{"code": "unknown_robot_action", "action": action}],
            ).to_dict()

        return json.dumps(result, ensure_ascii=False)

    def _move_axis(self, kwargs: dict[str, Any]) -> dict:
        axis = kwargs.get("axis")
        delta = kwargs.get("delta")
        if not isinstance(axis, str) or axis.strip() == "":
            return ToolResult.failure(
                state="tool_args_invalid",
                message="move_axis requires axis.",
                errors=[{"code": "missing_axis"}],
            ).to_dict()
        if not isinstance(delta, (int, float)) or isinstance(delta, bool):
            return ToolResult.failure(
                state="tool_args_invalid",
                message="move_axis requires numeric delta.",
                errors=[{"code": "missing_delta"}],
            ).to_dict()
        return self._facade.robot_move_axis(axis=axis, delta=float(delta))
