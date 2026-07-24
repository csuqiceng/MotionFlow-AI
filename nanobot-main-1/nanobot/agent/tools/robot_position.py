from __future__ import annotations

import json
import os
from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from robot_platform import get_robot_data_dir
from robot_platform.models import ToolResult
from robot_platform.positions.registry import PositionRegistry

def _default_path() -> str:
    """Resolve at construction time so ``--config`` selects the same library."""
    return os.environ.get("ROBOT_AI_POSITIONS_PATH", str(get_robot_data_dir() / "positions.json"))

_PARAMETERS = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["list", "get", "resolve"]},
        "name": {
            "type": "string",
            "description": "Position name (case-insensitive).",
        },
    },
    "required": ["action"],
    "additionalProperties": True,
}


@tool_parameters(_PARAMETERS)
class RobotPositionTool(Tool):
    def __init__(self, path: str | None = None) -> None:
        self._path = path or _default_path()

    @property
    def name(self) -> str:
        return "robot_position"

    @property
    def description(self) -> str:
        return (
            "Read-only named-position lookup (list/get/resolve). Returns pose x/y/z/rx/ry/rz. "
            "Never writes; unknown names return position_not_found (no fabrication)."
        )

    @property
    def read_only(self) -> bool:
        return True

    @property
    def exclusive(self) -> bool:
        return False

    async def execute(self, **kwargs: Any) -> str:
        action = str(kwargs.get("action") or "").strip()
        reg = PositionRegistry(self._path)
        if action == "list":
            items = [
                {"name": n.name, "pose": n.pose, "spd": n.spd} for n in reg.list_all()
            ]
            return json.dumps(
                ToolResult.success(
                    state="position_list",
                    message=f"{len(items)} position(s).",
                    data={"positions": items, "count": len(items)},
                ).to_dict(),
                ensure_ascii=False,
            )
        name = str(kwargs.get("name") or "")
        if action == "get":
            np = reg.get(name)
            if np is None:
                return json.dumps(
                    ToolResult.failure(
                        state="position_not_found",
                        message=f"Position '{name}' not found.",
                        errors=[{"code": "position_not_found", "name": name}],
                    ).to_dict(),
                    ensure_ascii=False,
                )
            return json.dumps(
                ToolResult.success(
                    state="position_found",
                    message=f"Position '{np.name}'.",
                    data={"position": np.to_dict()},
                ).to_dict(),
                ensure_ascii=False,
            )
        if action == "resolve":
            pose = reg.resolve(name)
            if pose is None:
                return json.dumps(
                    ToolResult.failure(
                        state="position_not_found",
                        message=f"Position '{name}' not found.",
                        errors=[{"code": "position_not_found", "name": name}],
                    ).to_dict(),
                    ensure_ascii=False,
                )
            return json.dumps(
                ToolResult.success(
                    state="position_resolved",
                    message=f"Resolved '{name}'.",
                    data={"name": name, "pose": pose},
                ).to_dict(),
                ensure_ascii=False,
            )
        return json.dumps(
            ToolResult.failure(
                state="unknown_position_action",
                message=f"Unknown: {action}",
                errors=[{"code": "unknown_position_action"}],
            ).to_dict(),
            ensure_ascii=False,
        )
