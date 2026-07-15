from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from robot_ai.models import ToolResult
from robot_ai.positions.registry import NamedPosition, PositionRegistry

_DEFAULT_PATH = os.environ.get(
    "ROBOT_AI_POSITIONS_PATH",
    str(Path.home() / ".nanobot" / "robot_ai" / "positions.json"),
)


def _commands_positions() -> list[NamedPosition]:
    """Read published linear_move commands from commands.json as NamedPositions."""
    import os
    from pathlib import Path

    cpath = os.environ.get(
        "ROBOT_AI_COMMANDS_PATH",
        str(Path.home() / ".nanobot" / "robot_ai" / "commands.json"),
    )
    result: list[NamedPosition] = []
    try:
        from robot_ai.library.versioned_registry import VersionedCommandRegistry
        reg = VersionedCommandRegistry(cpath)
        for cid, entity in reg._data.get("commands", {}).items():
            pv = entity.get("published_version")
            if pv is None:
                continue
            pub = entity.get("versions", {}).get(str(pv), {})
            if pub.get("component_id") != "linear_move":
                continue
            params = pub.get("parameters", {})
            result.append(NamedPosition(
                name=pub.get("name", cid),
                pose=[
                    float(params.get("target_x", 0)),
                    float(params.get("target_y", 0)),
                    float(params.get("target_z", 0)),
                    float(params.get("target_rx", 0)),
                    float(params.get("target_ry", 0)),
                    float(params.get("target_rz", 0)),
                ],
                spd=float(params.get("spd_pct", 50)),
            ))
    except Exception:
        pass
    return result


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
        self._path = path or _DEFAULT_PATH

    @property
    def name(self) -> str:
        return "robot_position"

    @property
    def description(self) -> str:
        return (
            "Read-only named-position lookup. Checks positions.json first, then "
            "commands.json. Returns pose x/y/z/rx/ry/rz. Never writes."
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
            items: list[dict[str, Any]] = [
                {"name": n.name, "pose": n.pose, "spd": n.spd, "source": "positions"}
                for n in reg.list_all()
            ]
            # Merge commands.json positions not already in registry
            existing = {n["name"].casefold() for n in items}
            for np in _commands_positions():
                if np.name.casefold() not in existing:
                    items.append({"name": np.name, "pose": np.pose, "spd": np.spd, "source": "commands"})
                    existing.add(np.name.casefold())
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
                for npc in _commands_positions():
                    if _name_fuzzy_match(name, npc.name):
                        np = npc
                        break
            if np is None:
                return _err("position_not_found", f"Position '{name}' not found.")
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
                for npc in _commands_positions():
                    if _name_fuzzy_match(name, npc.name):
                        pose = {
                            "x": npc.pose[0], "y": npc.pose[1], "z": npc.pose[2],
                            "rx": npc.pose[3], "ry": npc.pose[4], "rz": npc.pose[5],
                        }
                        break
            if pose is None:
                return _err("position_not_found", f"Position '{name}' not found.")
            return json.dumps(
                ToolResult.success(
                    state="position_resolved",
                    message=f"Resolved '{name}'.",
                    data={"name": name, "pose": pose},
                ).to_dict(),
                ensure_ascii=False,
            )

        return _err("unknown_position_action", f"Unknown: {action}")


def _name_fuzzy_match(query: str, full_name: str) -> bool:
    q = query.strip().casefold()
    fn = full_name.casefold()
    if q == fn:
        return True
    if fn.endswith(q) or q.endswith(fn):
        return True
    return False


def _err(code: str, message: str) -> str:
    return json.dumps(
        ToolResult.failure(
            state=code,
            message=message,
            errors=[{"code": code}],
        ).to_dict(),
        ensure_ascii=False,
    )
