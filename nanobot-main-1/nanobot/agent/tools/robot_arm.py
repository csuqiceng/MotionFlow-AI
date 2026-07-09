from __future__ import annotations

import json
from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from robot_ai.execution.mode import AUTO_EXECUTE
from robot_ai.models import ToolResult
from robot_ai.safety.config import (
    DEFAULT_WORKSPACE_R_MAX,
    DEFAULT_WORKSPACE_R_MIN,
    DEFAULT_WORKSPACE_Z_MAX,
    DEFAULT_WORKSPACE_Z_MIN,
)
from robot_ai.tools.robot_tools import RobotToolFacade
from robot_ai.zmotion_operator_control import (
    REAL_EXECUTION_CONFIRMATION_CODE,
    ZMotionOperatorRequest,
    run_zmotion_operator_command,
)

_PARAMETERS = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": [
                "status",
                "emergency_stop",
                "release_emergency_stop",
                "pause",
                "resume",
                "stop_current",
                "release_cancel",
                "delay",
                "io",
                "linear_move",
                "linear_path",
            ],
            "description": (
                "Restricted ZMotion operator action exposed to the LLM. Motion uses "
                "Func108 linear interpolation only. alarm_reset is intentionally NOT "
                "exposed (alarm clearing is a human/operator action via the CLI, not AI)."
            ),
        },
        "target_pose": {
            "type": "object",
            "description": "Absolute x/y/z/rx/ry/rz pose for linear_move.",
        },
        "position": {
            "type": "string",
            "description": (
                "Optional named position (e.g. 'A'); resolves to target_pose via the "
                "positions registry. Unknown name -> position_not_found."
            ),
        },
        "target_poses": {
            "type": "array",
            "description": "Absolute pose list for continuous linear_path.",
        },
        "seconds": {
            "type": "number",
            "description": "Delay seconds for delay.",
        },
        "io_number": {
            "type": "integer",
            "description": "IO channel number for io.",
        },
        "enabled": {
            "type": "boolean",
            "description": "IO state for io.",
        },
    },
    "required": ["action"],
    "additionalProperties": True,
}


@tool_parameters(_PARAMETERS)
class RobotArmTool(Tool):
    def __init__(
        self,
        facade: RobotToolFacade | None = None,
        operator_runner=run_zmotion_operator_command,
        positions_path: str | None = None,
    ) -> None:
        self._facade = facade or RobotToolFacade()
        self._operator_runner = operator_runner
        import os
        from pathlib import Path

        from robot_ai.positions.registry import PositionRegistry

        self._positions = PositionRegistry(
            positions_path
            or os.environ.get(
                "ROBOT_AI_POSITIONS_PATH",
                str(Path.home() / ".nanobot" / "robot_ai" / "positions.json"),
            )
        )

    @property
    def name(self) -> str:
        return "robot_arm"

    @property
    def description(self) -> str:
        if AUTO_EXECUTE:
            return (
                "Control the robot (system/delay/IO/Func108). Auto-execute mode: motion runs "
                "immediately, L1 safety applies. One tool call per request — don't check status "
                "before/after. If the phrase matches a flow name, use robot_flow run instead."
            )
        return (
            "Inspect or control the factory robot via the restricted ZMotion operator set (system "
            "controls, delay, IO, Func108 linear / linear_path). This tool is DRY-RUN by design: it "
            "returns a structured plan + safety check with ok=true and state=zmotion_operator_dry_run, "
            "and NEVER writes to the controller. The plan's 'blockers' field "
            "(operator_confirmation_missing, real_motion_writes_disabled) is NOT an error — it lists "
            "what REAL execution would require, which is operator-only via the CLI/bridge or the WebUI "
            "Robot Control Panel (floating button, bottom-right). When you call this tool for a motion "
            "request, report the result to the user as 'plan ready, no motion executed (dry-run)' and "
            "read back the target pose / safety items; do NOT call it a failure and do NOT invent "
            "status codes."
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
        elif action in {
            "emergency_stop",
            "release_emergency_stop",
            "pause",
            "resume",
            "stop_current",
            "release_cancel",
        }:
            result = self._operator("system", {"action": action})
        elif action == "delay":
            result = self._operator("delay", {"seconds": kwargs.get("seconds")})
        elif action == "io":
            result = self._operator(
                "io",
                {
                    "io_number": kwargs.get("io_number"),
                    "enabled": kwargs.get("enabled"),
                    "allowed_io_channels": kwargs.get("allowed_io_channels", []),
                },
            )
        elif action == "linear_move":
            position = kwargs.get("position")
            if position:
                pose = self._positions.resolve(str(position))
                if pose is None:
                    result = ToolResult.failure(
                        state="position_not_found",
                        message=f"Position '{position}' not found in registry.",
                        errors=[{"code": "position_not_found", "name": str(position)}],
                    ).to_dict()
                else:
                    result = self._operator(
                        "linear_move",
                        self._motion_kwargs(
                            {**kwargs, "target_pose": pose}, "target_pose"
                        ),
                    )
            else:
                result = self._operator(
                    "linear_move", self._motion_kwargs(kwargs, "target_pose")
                )
        elif action == "linear_path":
            result = self._operator("linear_path", self._motion_kwargs(kwargs, "target_poses"))
        else:
            result = ToolResult.failure(
                state="unknown_robot_action",
                message=f"Unknown robot action: {action}",
                errors=[{"code": "unknown_robot_action", "action": action}],
            ).to_dict()

        return json.dumps(result, ensure_ascii=False)

    def _operator(self, command: str, parameters: dict[str, Any]) -> dict:
        request = ZMotionOperatorRequest(
            command=command,
            parameters=parameters,
            execute_real=AUTO_EXECUTE,
            confirm_work_area_clear=AUTO_EXECUTE,
            confirm_estop_ready=AUTO_EXECUTE,
            confirmation_code=REAL_EXECUTION_CONFIRMATION_CODE if AUTO_EXECUTE else "",
        )
        return self._operator_runner(request=request)

    @staticmethod
    def _motion_kwargs(kwargs: dict[str, Any], pose_key: str) -> dict[str, Any]:
        speed = kwargs.get("speed_pct", 50.0)
        return {
            pose_key: kwargs.get(pose_key),
            "speed_pct": speed,
            "acceleration_pct": kwargs.get("acceleration_pct", speed),
            "deceleration_pct": kwargs.get("deceleration_pct", speed),
            "r_min": kwargs.get("r_min", DEFAULT_WORKSPACE_R_MIN),
            "r_max": kwargs.get("r_max", DEFAULT_WORKSPACE_R_MAX),
            "z_min": kwargs.get("z_min", DEFAULT_WORKSPACE_Z_MIN),
            "z_max": kwargs.get("z_max", DEFAULT_WORKSPACE_Z_MAX),
        }
