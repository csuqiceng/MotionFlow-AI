from __future__ import annotations

import json
from collections.abc import Callable
from contextvars import ContextVar
from copy import deepcopy
from types import SimpleNamespace
from typing import Any

from ai_runtime.robot_tools.base import Tool, tool_parameters
from ai_runtime.robot_tools.context import ContextAware, RequestContext
from ai_runtime.robot_tools.principal import current_application_principal
from robot_platform.application import (
    RobotAutomaticMotionApplicationPort,
    RobotAutomaticMotionCommand,
    RobotDryRunApplicationPort,
    RobotPositionApplicationPort,
    RobotPositionQuery,
    RobotStatusApplicationPort,
)
from robot_platform.models import ToolResult
from robot_platform.runtime import get_robot_execution_mode
from robot_platform.safety.config import (
    DEFAULT_WORKSPACE_R_MAX,
    DEFAULT_WORKSPACE_R_MIN,
    DEFAULT_WORKSPACE_Z_MAX,
    DEFAULT_WORKSPACE_Z_MIN,
)

_PARAMETERS = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": [
                "status",
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
                "positions registry. Names accept common aliases; unknown name -> "
                "position_not_found with candidates. Do not move until resolved."
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


class _UnavailableStatusApplication:
    def query(self, *_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(
            ok=False, payload=None,
            error=SimpleNamespace(
                code="robot_status_unavailable",
                message="Robot status Application was not injected.",
            ),
        )


class _UnavailableDryRunApplication:
    def preview_command(self, *_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(
            ok=False, payload=None,
            error=SimpleNamespace(
                code="robot_operation_not_composed",
                message="Robot operation Application was not injected.",
            ),
        )


@tool_parameters(_PARAMETERS)
class RobotArmTool(Tool, ContextAware):
    def __init__(
        self,
        facade: Any = None,
        operator_runner: Callable[..., dict[str, Any]] | None = None,
        positions_path: str | None = None,
        *,
        platform: Any = None,
        status_application: RobotStatusApplicationPort | None = None,
        dry_run_application: RobotDryRunApplicationPort | None = None,
        automatic_motion_application: RobotAutomaticMotionApplicationPort | None = None,
        position_application: RobotPositionApplicationPort | None = None,
    ) -> None:
        if status_application is None or dry_run_application is None:
            legacy_status = _UnavailableStatusApplication()
            legacy_dry_run = _UnavailableDryRunApplication()
            status_application = status_application or legacy_status
            dry_run_application = dry_run_application or legacy_dry_run
        # Compatibility constructor parameters remain parseable for one
        # release, but can no longer create a hidden RobotPlatform graph.
        del facade, operator_runner
        self._platform = None
        del platform
        self._status_application = status_application
        self._dry_run_application = dry_run_application
        self._automatic_motion_application = automatic_motion_application
        del positions_path
        self._position_application = position_application
        # Per-request routing context (for on_progress). Each tool instance
        # gets its own ContextVar so concurrent tool calls don't interfere.
        self._request_ctx: ContextVar[RequestContext | None] = ContextVar(
            "robot_arm_request_ctx", default=None
        )

    def set_context(self, ctx: RequestContext) -> None:
        self._request_ctx.set(ctx)

    def canonical_effect_parameters(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Remove ignored caller fields before physical-effect fingerprinting."""
        action = str(parameters.get("action", "")).strip()
        if action == "delay":
            return {"action": action, "seconds": float(parameters.get("seconds") or 0)}
        if action == "io":
            return {
                "action": action, "io_number": int(parameters.get("io_number")),
                "enabled": bool(parameters.get("enabled")),
            }
        if action == "linear_move":
            normalized = deepcopy(parameters)
            position = str(normalized.get("position") or "").strip()
            if position:
                resolved = self._resolve_position(position)
                if resolved.get("ok"):
                    normalized["target_pose"] = resolved["data"]["pose"]
                    normalized.pop("position", None)
                else:
                    return {
                        "action": action,
                        "_position_resolution_error": deepcopy(resolved),
                    }
            return {"action": action, **_normalize_motion_effect(
                self._motion_kwargs(normalized, "target_pose"), "target_pose",
            )}
        if action == "linear_path":
            return {"action": action, **_normalize_motion_effect(
                self._motion_kwargs(parameters, "target_poses"), "target_poses",
            )}
        if action in {
            "status", "release_emergency_stop", "pause", "resume",
            "stop_current", "release_cancel",
        }:
            return {"action": action}
        return {key: deepcopy(parameters[key]) for key in sorted(parameters)}

    @property
    def name(self) -> str:
        return "robot_arm"

    @property
    def description(self) -> str:
        if self._auto_execute:
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
            status = self._status_application.query()
            if status.ok and isinstance(status.payload, dict):
                result = status.payload
            else:
                error = getattr(status, "error", None)
                code = getattr(error, "code", "robot_status_unavailable")
                message = getattr(error, "message", "robot status unavailable")
                result = ToolResult.failure(
                    state=code, message=message, errors=[{"code": code}],
                ).to_dict()
        elif action in {
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
                },
            )
        elif action == "linear_move":
            frozen_error = kwargs.get("_position_resolution_error")
            position = kwargs.get("position")
            if isinstance(frozen_error, dict):
                result = deepcopy(frozen_error)
            elif position:
                position_result = self._resolve_position(str(position))
                if not position_result.get("ok"):
                    result = position_result
                else:
                    pose = position_result["data"]["pose"]
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

    def _resolve_position(self, name: str) -> dict[str, Any]:
        if self._position_application is None:
            return ToolResult.failure(
                state="position_state_unavailable",
                message="Position service is unavailable.",
                errors=[{"code": "position_state_unavailable"}],
            ).to_dict()
        try:
            response = self._position_application.query(RobotPositionQuery(
                principal=current_application_principal(),
                action="resolve",
                name=name,
            ))
        except Exception:
            response = None
        if response is None or not response.ok or response.payload is None:
            error = getattr(response, "error", None)
            code = getattr(error, "code", "position_state_unavailable")
            message = getattr(error, "message", "Position service is unavailable.")
            return ToolResult.failure(
                state=code,
                message=message,
                errors=[{"code": code}],
                data=getattr(error, "details", None),
            ).to_dict()
        pose = response.payload.get("pose")
        if not isinstance(pose, dict):
            return ToolResult.failure(
                state="position_state_unavailable",
                message="Position service returned an invalid result.",
                errors=[{"code": "position_state_unavailable"}],
            ).to_dict()
        return ToolResult.success(
            state="position_resolved", message="Position resolved.", data={"pose": pose},
        ).to_dict()

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
        if not self._auto_execute:
            preview = self._dry_run_application.preview_command(command, parameters)
            if preview.ok and isinstance(preview.payload, dict):
                return preview.payload
            error = getattr(preview, "error", None)
            code = getattr(error, "code", "dry_run_unavailable")
            message = getattr(error, "message", "Robot dry-run is unavailable.")
            return ToolResult.failure(
                state=code, message=message, errors=[{"code": code}],
            ).to_dict()
        if (
            command in {"linear_move", "linear_path"}
            and self._automatic_motion_application is not None
        ):
            response = self._automatic_motion_application.execute(
                RobotAutomaticMotionCommand(
                    principal=current_application_principal(),
                    command=command,
                    parameters=parameters,
                )
            )
            if response.ok and isinstance(response.payload, dict):
                return response.payload
            error = getattr(response, "error", None)
            code = getattr(error, "code", "automatic_motion_unavailable")
            message = getattr(
                error, "message", "Automatic robot motion is unavailable."
            )
            return ToolResult.failure(
                state=code, message=message, errors=[{"code": code}],
            ).to_dict()
        return ToolResult.failure(
            state="staged_execution_required",
            message=(
                "AI tools cannot acquire real-execution credentials. Use the "
                "authenticated plan/confirm/execute operator workflow."
            ),
            errors=[{"code": "staged_execution_required"}],
        ).to_dict()

    @property
    def _auto_execute(self) -> bool:
        """Read the host setting at call time rather than caching import state."""
        return get_robot_execution_mode() == "auto_after_safety_check"

    @staticmethod
    def _motion_kwargs(kwargs: dict[str, Any], pose_key: str) -> dict[str, Any]:
        # Natural-language movement calls normally omit speed.  Preserve the
        # product default while the L1 gate enforces the configured <=100%
        # controller envelope.
        speed = kwargs.get("speed_pct")
        if speed is None:
            speed = 50.0
        acceleration = kwargs.get("acceleration_pct")
        if acceleration is None:
            acceleration = speed
        deceleration = kwargs.get("deceleration_pct")
        if deceleration is None:
            deceleration = speed
        return {
            pose_key: kwargs.get(pose_key),
            "speed_pct": speed,
            "acceleration_pct": acceleration,
            "deceleration_pct": deceleration,
            "r_min": kwargs.get("r_min", DEFAULT_WORKSPACE_R_MIN),
            "r_max": kwargs.get("r_max", DEFAULT_WORKSPACE_R_MAX),
            "z_min": kwargs.get("z_min", DEFAULT_WORKSPACE_Z_MIN),
            "z_max": kwargs.get("z_max", DEFAULT_WORKSPACE_Z_MAX),
        }


def _normalize_motion_effect(
    parameters: dict[str, Any], pose_key: str,
) -> dict[str, Any]:
    normalized = deepcopy(parameters)
    pose = normalized.get(pose_key)
    if pose_key == "target_pose" and isinstance(pose, dict):
        normalized[pose_key] = {
            axis: float(pose[axis]) for axis in ("x", "y", "z", "rx", "ry", "rz")
            if axis in pose
        }
    elif pose_key == "target_poses" and isinstance(pose, list):
        normalized[pose_key] = [
            {
                axis: float(item[axis])
                for axis in ("x", "y", "z", "rx", "ry", "rz")
                if isinstance(item, dict) and axis in item
            }
            for item in pose
        ]
    for key in (
        "speed_pct", "acceleration_pct", "deceleration_pct",
        "r_min", "r_max", "z_min", "z_max",
    ):
        normalized[key] = float(normalized[key])
    return normalized
