from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ai_runtime.robot_tools.base import Tool, tool_parameters
from robot_platform import get_robot_data_dir
from robot_platform.library.published import PublishedRobotLibrary
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
    def __init__(self, path: str | None = None, *, data_dir: str | None = None) -> None:
        self._path = path or _default_path()
        self._data_dir = data_dir or (str(get_robot_data_dir()) if path is None else str(Path(path).parent))

    @property
    def name(self) -> str:
        return "robot_position"

    @property
    def description(self) -> str:
        return (
            "Read-only robot-library lookup (list/get/resolve). Lists named positions, published "
            "Func108 position commands, and flow summaries. resolve returns a pose only; flows "
            "cannot be resolved as a single position. Never writes."
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
        library = PublishedRobotLibrary(self._data_dir)
        if action == "list":
            items = [
                {"name": n.name, "pose": n.pose, "spd": n.spd} for n in reg.list_all()
            ]
            commands = library.position_commands()
            flows = library.flows()
            return json.dumps(
                ToolResult.success(
                    state="position_list",
                    message=f"{len(items)} position(s), {len(commands)} position command(s), {len(flows)} flow(s).",
                    data={"positions": items, "position_commands": commands, "flows": flows,
                          "count": len(items) + len(commands) + len(flows)},
                ).to_dict(),
                ensure_ascii=False,
            )
        name = str(kwargs.get("name") or "")
        if action == "get":
            np = reg.get(name)
            if np is not None:
                return json.dumps(ToolResult.success(state="position_found", message=f"Position '{np.name}'.", data={"resource_type": "position", "position": np.to_dict()}).to_dict(), ensure_ascii=False)
            found = library.find(name)
            if found is not None:
                resource_type, resource = found
                return json.dumps(ToolResult.success(state=f"{resource_type}_found", message=f"{resource_type} '{resource.get('name', name)}'.", data={"resource_type": resource_type, resource_type: resource}).to_dict(), ensure_ascii=False)
            return json.dumps(ToolResult.failure(state="position_not_found", message=f"Position or library resource '{name}' not found.", errors=[{"code": "position_not_found", "name": name}]).to_dict(), ensure_ascii=False)
        if action == "resolve":
            pose = reg.resolve(name)
            if pose is None:
                found = library.find(name)
                if found is not None and found[0] == "position_command":
                    pose = found[1]["pose"]
                elif found is not None and found[0] == "flow":
                    return json.dumps(ToolResult.failure(state="position_not_single_pose", message=f"Flow '{name}' cannot be resolved as one position.", errors=[{"code": "position_not_single_pose", "name": name}]).to_dict(), ensure_ascii=False)
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
