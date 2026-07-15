from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from robot_ai.models import ToolResult

_DEFAULT_COMMANDS_PATH = str(Path.home() / ".nanobot" / "robot_ai" / "commands.json")

_PARAMETERS = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["list", "get", "execute"],
            "description": (
                "What to do with the robot command library. "
                "'list' shows all available commands. "
                "'get' returns full details (parameters, aliases) for one command. "
                "'execute' runs a named command through the operator safety pipeline."
            ),
        },
        "name": {
            "type": "string",
            "description": "Command name or command_id (case-insensitive). Required for get/execute.",
        },
        "speed_pct": {
            "type": "number",
            "description": "Optional override speed percentage for linear_move commands.",
        },
    },
    "required": ["action"],
    "additionalProperties": True,
}


def _load_registry() -> Any:
    """Load the shared VersionedCommandRegistry (lazy, cached per-interpreter)."""
    import os
    from pathlib import Path

    from robot_ai.library.versioned_registry import VersionedCommandRegistry

    cpath = os.environ.get(
        "ROBOT_AI_COMMANDS_PATH",
        str(Path.home() / ".nanobot" / "robot_ai" / "commands.json"),
    )
    apath = os.environ.get(
        "ROBOT_AI_COMMANDS_AUDIT_PATH",
        str(Path.home() / ".nanobot" / "robot_ai" / "audit.jsonl"),
    )
    return VersionedCommandRegistry(cpath, audit_path=apath)


def _find_published(entity: dict[str, Any]) -> dict[str, Any] | None:
    """Return the published version dict for a command entity, or None."""
    pv = entity.get("published_version")
    if pv is None:
        return None
    return entity.get("versions", {}).get(str(pv))


def _simple_params(pub: dict[str, Any]) -> dict[str, Any]:
    """Flatten non-motion parameters into human-readable simple form."""
    fid = pub.get("component_id", "")
    params = dict(pub.get("parameters", {}))

    if fid == "io_write":
        io_no = params.get("io_no", 0)
        io_action = params.get("io_action", 0)
        return {"io_number": int(io_no), "state": "ON" if int(io_action) == 1 else "OFF"}

    if fid == "system_action":
        out: dict[str, Any] = {}
        if params.get("estop_ctrl") == 1:
            out["type"] = "紧急停止"
        elif params.get("cancel_ctrl") == 1:
            out["type"] = "结束按下"
        elif params.get("cancel_ctrl") == 2:
            out["type"] = "结束解除"
        elif params.get("pause_ctrl") == 1:
            out["type"] = "暂停"
        elif params.get("pause_ctrl") == 2:
            out["type"] = "继续/恢复"
        elif params.get("reset_ctrl") == 1:
            out["type"] = "复位"
        return out

    if fid == "linear_move":
        return {
            "target_x": params.get("target_x"),
            "target_y": params.get("target_y"),
            "target_z": params.get("target_z"),
            "target_rx": params.get("target_rx"),
            "target_ry": params.get("target_ry"),
            "target_rz": params.get("target_rz"),
            "speed_pct": params.get("spd_pct", 50),
        }

    if fid == "delay":
        return {"seconds": params.get("seconds", 0)}

    return params


@tool_parameters(_PARAMETERS)
class RobotCommandTool(Tool):
    """Expose the robot command library (commands.json) to the LLM."""

    def __init__(self, commands_path: str | None = None) -> None:
        self._path = commands_path or _DEFAULT_COMMANDS_PATH

    @property
    def name(self) -> str:
        return "robot_command"

    @property
    def description(self) -> str:
        return (
            "THE robot command library (commands.json). Contains ALL predefined commands "
            "including named positions (home, 位置A/B/C, 休息姿态), IO controls, system "
            "actions, etc. "
            "Use 'list' to see everything available. Use 'get' for full parameters/coordinates. "
            "Use 'execute' to run a command. "
            "CRITICAL: When the user mentions ANY position name (e.g. 'A', 'home', 'Home位', "
            "'位置A', 'A点'), check HERE FIRST with 'get' or 'list' — NOT robot_position. "
            "This is the source of truth for all robot commands and named positions."
        )

    @property
    def read_only(self) -> bool:
        return False

    @property
    def exclusive(self) -> bool:
        return False

    async def execute(self, **kwargs: Any) -> str:
        action = str(kwargs.get("action") or "").strip()
        reg = _load_registry()

        # ── list ──────────────────────────────────────────────────────
        if action == "list":
            summaries = []
            for cid in sorted(reg._data.get("commands", {})):
                e = reg._data["commands"][cid]
                pub = _find_published(e)
                if pub is None:
                    continue
                summaries.append({
                    "command_id": cid,
                    "name": pub.get("name", ""),
                    "component_id": pub.get("component_id", ""),
                    "description": pub.get("description", ""),
                    "risk_level": pub.get("risk_level", ""),
                    "aliases": pub.get("aliases", []),
                    "simple_params": _simple_params(pub),
                })
            return json.dumps(
                ToolResult.success(
                    state="command_list",
                    message=f"{len(summaries)} command(s) in library.",
                    data={"commands": summaries, "count": len(summaries)},
                ).to_dict(),
                ensure_ascii=False,
            )

        # ── get / execute (need name) ─────────────────────────────────
        name_raw = str(kwargs.get("name") or "").strip().casefold()
        if not name_raw:
            return _err("missing_name", "The 'name' parameter is required for get/execute.")

        # Resolve command_id by name/alias lookup
        command_id_found: str | None = None
        for cid, entity in reg._data.get("commands", {}).items():
            pub = _find_published(entity)
            if pub is None:
                continue
            if pub["name"].strip().casefold() == name_raw:
                command_id_found = cid
                break
            if any(a.strip().casefold() == name_raw for a in pub.get("aliases", [])):
                command_id_found = cid
                break

        if command_id_found is None:
            return _err(
                "command_not_found",
                f"Command '{kwargs.get('name')}' not found. Use action='list' to see available commands.",
            )

        entity = reg._data["commands"][command_id_found]
        pub = _find_published(entity)

        # ── get ───────────────────────────────────────────────────────
        if action == "get":
            return json.dumps(
                ToolResult.success(
                    state="command_found",
                    message=f"Command '{pub['name']}' ({pub.get('component_id', '')}).",
                    data={
                        "command": {
                            "command_id": command_id_found,
                            "name": pub["name"],
                            "component_id": pub.get("component_id"),
                            "description": pub.get("description"),
                            "risk_level": pub.get("risk_level"),
                            "aliases": pub.get("aliases", []),
                            "parameters": _simple_params(pub),
                            "raw_parameters": pub.get("parameters", {}),
                        }
                    },
                ).to_dict(),
                ensure_ascii=False,
            )

        # ── execute ───────────────────────────────────────────────────
        if action == "execute":
            return await self._execute_command(command_id_found, pub, kwargs)

        return _err("unknown_action", f"Unknown action: {action}")

    async def _execute_command(
        self, command_id: str, pub: dict[str, Any], kwargs: dict[str, Any],
    ) -> str:
        """Translate command to robot_arm operator call + execute."""
        fid = pub.get("component_id", "")
        params = dict(pub.get("parameters", {}))
        speed = kwargs.get("speed_pct")

        from robot_ai.execution.mode import AUTO_EXECUTE
        from robot_ai.tools.robot_tools import RobotToolFacade
        from robot_ai.zmotion_operator_control import (
            REAL_EXECUTION_CONFIRMATION_CODE,
            ZMotionOperatorRequest,
            run_zmotion_operator_command,
        )

        facade = RobotToolFacade()

        # Map component_id → operator command
        if fid == "linear_move":
            from robot_ai.safety.config import (
                DEFAULT_WORKSPACE_R_MAX,
                DEFAULT_WORKSPACE_R_MIN,
                DEFAULT_WORKSPACE_Z_MAX,
                DEFAULT_WORKSPACE_Z_MIN,
            )

            spd = speed if speed is not None else params.get("spd_pct", 50.0)
            request = ZMotionOperatorRequest(
                command="linear_move",
                parameters={
                    "target_pose": {
                        "x": float(params.get("target_x", 0)),
                        "y": float(params.get("target_y", 0)),
                        "z": float(params.get("target_z", 0)),
                        "rx": float(params.get("target_rx", 0)),
                        "ry": float(params.get("target_ry", 0)),
                        "rz": float(params.get("target_rz", 0)),
                    },
                    "speed_pct": spd,
                    "acceleration_pct": params.get("acc_pct", spd),
                    "deceleration_pct": params.get("dec_pct", spd),
                    "r_min": DEFAULT_WORKSPACE_R_MIN,
                    "r_max": DEFAULT_WORKSPACE_R_MAX,
                    "z_min": DEFAULT_WORKSPACE_Z_MIN,
                    "z_max": DEFAULT_WORKSPACE_Z_MAX,
                },
                execute_real=AUTO_EXECUTE,
                confirm_work_area_clear=AUTO_EXECUTE,
                confirm_estop_ready=AUTO_EXECUTE,
                confirmation_code=REAL_EXECUTION_CONFIRMATION_CODE if AUTO_EXECUTE else "",
            )
            result = run_zmotion_operator_command(request=request)
        elif fid == "io_write":
            request = ZMotionOperatorRequest(
                command="io",
                parameters={
                    "io_number": int(params.get("io_no", 0)),
                    "enabled": bool(int(params.get("io_action", 0)) == 1),
                    "allowed_io_channels": [],
                },
                execute_real=AUTO_EXECUTE,
                confirm_work_area_clear=AUTO_EXECUTE,
                confirm_estop_ready=AUTO_EXECUTE,
                confirmation_code=REAL_EXECUTION_CONFIRMATION_CODE if AUTO_EXECUTE else "",
            )
            result = run_zmotion_operator_command(request=request)
        elif fid == "system_action":
            # Determine action from parameters
            system_action = ""
            if params.get("estop_ctrl") == 1:
                system_action = "emergency_stop"
            elif params.get("cancel_ctrl") == 1:
                system_action = "stop_current"
            elif params.get("cancel_ctrl") == 2:
                system_action = "release_cancel"
            elif params.get("pause_ctrl") == 1:
                system_action = "pause"
            elif params.get("pause_ctrl") == 2:
                system_action = "resume"
            elif params.get("reset_ctrl") == 1:
                system_action = "release_emergency_stop"

            if system_action:
                result = ZMotionOperatorRequest(
                    command="system",
                    parameters={"action": system_action},
                    execute_real=AUTO_EXECUTE,
                    confirm_work_area_clear=AUTO_EXECUTE,
                    confirm_estop_ready=AUTO_EXECUTE,
                    confirmation_code=REAL_EXECUTION_CONFIRMATION_CODE if AUTO_EXECUTE else "",
                )
                result = run_zmotion_operator_command(request=result)
            else:
                return _err(
                    "unsupported_system_action",
                    f"Command '{command_id}' has no executable system_action mapping.",
                )
        elif fid == "delay":
            result = ZMotionOperatorRequest(
                command="delay",
                parameters={"seconds": float(params.get("seconds", 0))},
                execute_real=AUTO_EXECUTE,
                confirm_work_area_clear=AUTO_EXECUTE,
                confirm_estop_ready=AUTO_EXECUTE,
                confirmation_code=REAL_EXECUTION_CONFIRMATION_CODE if AUTO_EXECUTE else "",
            )
            result = run_zmotion_operator_command(request=result)
        else:
            return _err(
                "unknown_component",
                f"Command '{command_id}' has unknown component_id '{fid}'. Use action='list' to see available commands.",
            )

        if isinstance(result, dict):
            return json.dumps(result, ensure_ascii=False)
        return json.dumps(result.to_dict(), ensure_ascii=False)


def _err(code: str, message: str) -> str:
    return json.dumps(
        ToolResult.failure(
            state=code,
            message=message,
            errors=[{"code": code}],
        ).to_dict(),
        ensure_ascii=False,
    )
