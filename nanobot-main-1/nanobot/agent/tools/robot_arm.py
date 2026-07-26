from __future__ import annotations

import json
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.context import ContextAware, RequestContext
from robot_platform.execution.mode import AUTO_EXECUTE
from robot_platform.models import ToolResult
from robot_platform.platform import RobotPlatform, auto_execution_confirmation
from robot_platform.runtime import get_robot_data_dir
from robot_platform.safety.config import (
    DEFAULT_WORKSPACE_R_MAX,
    DEFAULT_WORKSPACE_R_MIN,
    DEFAULT_WORKSPACE_Z_MAX,
    DEFAULT_WORKSPACE_Z_MIN,
)
from robot_platform.tools.robot_tools import RobotToolFacade

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
class RobotArmTool(Tool, ContextAware):
    def __init__(
        self,
        facade: RobotToolFacade | None = None,
        operator_runner: Callable[..., dict[str, Any]] | None = None,
        positions_path: str | None = None,
    ) -> None:
        self._facade = facade or RobotToolFacade()
        platform_args: dict[str, Any] = {"facade": self._facade}
        if operator_runner is not None:
            platform_args["operator_runner"] = operator_runner
        self._platform = RobotPlatform(**platform_args)
        import os

        from robot_platform.positions.registry import PositionRegistry

        self._positions = PositionRegistry(
            positions_path
            or os.environ.get(
                "ROBOT_AI_POSITIONS_PATH",
                str(get_robot_data_dir() / "positions.json"),
            )
        )
        # Per-request routing context (for on_progress). Each tool instance
        # gets its own ContextVar so concurrent tool calls don't interfere.
        self._request_ctx: ContextVar[RequestContext | None] = ContextVar(
            "robot_arm_request_ctx", default=None
        )

    def set_context(self, ctx: RequestContext) -> None:
        self._request_ctx.set(ctx)

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
            "what REAL execution would require. When you call this tool for a motion request, report "
            "the result to the user as 'plan ready, no motion executed (dry-run)' and read back the "
            "target pose / safety items; do NOT call it a failure and do NOT invent status codes."
        )

    @property
    def read_only(self) -> bool:
        return False

    @property
    def exclusive(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        action = str(kwargs.get("action") or "").strip()

        # Emit a user-visible "开始执行" hint before any motion-class action.
        # Status queries are silent (no side effects, no need to notify).
        hint = self._progress_hint(action, kwargs)
        if hint is not None:
            await self._emit_progress(hint)

        if action == "status":
            result = self._platform.get_status()
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

    @staticmethod
    def _progress_hint(action: str, kwargs: dict[str, Any]) -> str | None:
        """Build a user-visible progress hint for motion-class actions.

        Returns None for status queries (silent) and unknown actions.
        """
        if action == "linear_move":
            position = kwargs.get("position")
            pose = kwargs.get("target_pose")
            if position:
                return f"机械臂开始移动到位置 {position}"
            if isinstance(pose, dict):
                x = pose.get("x", "?")
                y = pose.get("y", "?")
                z = pose.get("z", "?")
                return f"机械臂开始移动到坐标 (x={x}, y={y}, z={z})"
            return "机械臂开始执行直线移动"
        if action == "linear_path":
            return "机械臂开始执行路径移动"
        if action == "io":
            io_number = kwargs.get("io_number", "?")
            enabled = kwargs.get("enabled")
            target = "开启" if enabled else "关闭"
            return f"机械臂开始{target} IO {io_number}"
        if action == "delay":
            seconds = kwargs.get("seconds", "?")
            return f"机械臂开始等待 {seconds} 秒"
        if action == "emergency_stop":
            return "机械臂紧急停止中"
        if action == "release_emergency_stop":
            return "机械臂解除紧急停止"
        if action in {"pause", "resume", "stop_current", "release_cancel"}:
            action_map = {
                "pause": "暂停",
                "resume": "恢复",
                "stop_current": "停止当前动作",
                "release_cancel": "解除取消",
            }
            return f"机械臂{action_map.get(action, action)}"
        return None

    async def _emit_progress(self, text: str) -> None:
        """Send a user-visible progress hint through the request's on_progress.

        Silently skips when no request context is bound (e.g. background jobs,
        CLI runs without progress sink). The hint is delivered as a tool_hint
        frame so the WebUI renders it in the activity line.
        """
        rc = self._request_ctx.get()
        if rc is None or rc.on_progress is None:
            return
        import inspect

        try:
            result = rc.on_progress(text, tool_hint=True)
            if inspect.isawaitable(result):
                await result
        except Exception:
            # Progress hint is best-effort; never fail the tool call.
            pass

    def _operator(self, command: str, parameters: dict[str, Any]) -> dict:
        if not AUTO_EXECUTE:
            return self._platform.plan_motion(command, parameters)
        confirmation_code, work_area_clear, estop_ready = auto_execution_confirmation()
        return self._platform.execute_confirmed_plan(
            command,
            parameters,
            confirmation_code=confirmation_code,
            confirm_work_area_clear=work_area_clear,
            confirm_estop_ready=estop_ready,
        )

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
