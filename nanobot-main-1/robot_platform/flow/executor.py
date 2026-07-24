"""Run a named flow by mapping each step to a restricted operator command.

Each ``FlowStep`` becomes one ``ZMotionOperatorRequest`` and is submitted
through ``run_zmotion_operator_command`` — so every step independently passes
the Phase 1 safety gate (L1 precheck + execution gate) and the Phase 2 V5.0
write protocol. Execution is sequential and stops on the first failing step.

Step ``func_id`` → command mapping: 108=linear_move, 104=system, 110=delay,
120=io. Step ``params`` use the operator's structured shape (``target_pose``
dict, ``speed_pct`` ...); a legacy ``target_x``/``delay_sec`` fallback is
accepted for compatibility.

Note: each step connects/reads/executes independently. This is intentionally
correct over fast — every step is safety-checked against fresh controller
state. A shared-client optimisation can come later.
"""

from __future__ import annotations

from typing import Any, Callable

from robot_platform.backends.factory import RobotBackendConfig
from robot_platform.flow.models import FlowEntry, FlowStep
from robot_platform.models import ToolResult
from robot_platform.safety.config import (
    DEFAULT_WORKSPACE_R_MAX,
    DEFAULT_WORKSPACE_R_MIN,
    DEFAULT_WORKSPACE_Z_MAX,
    DEFAULT_WORKSPACE_Z_MIN,
)
from robot_platform.zmotion_operator_control import (
    ZMotionOperatorRequest,
    run_zmotion_operator_command,
)


_FUNC_TO_COMMAND: dict[int, str] = {
    108: "linear_move",
    104: "system",
    110: "delay",
    120: "io",
}


def run_flow(
    entry: FlowEntry,
    *,
    config: RobotBackendConfig | None = None,
    execute_real: bool = False,
    confirm_work_area_clear: bool = False,
    confirm_estop_ready: bool = False,
    confirmation_code: str = "",
    client_factory: Callable[..., Any] | None = None,
    executor_factory: Callable[..., Any] | None = None,
    on_step: Callable[[int, str, dict[str, Any] | None], None] | None = None,
    before_step: Callable[[int], bool] | None = None,
) -> dict[str, Any]:
    if not entry.steps:
        return ToolResult.failure(
            state="flow_empty",
            message="Flow has no steps.",
            data={"flow_name": entry.name},
            errors=[{"code": "flow_empty"}],
        ).to_dict()

    total = len(entry.steps)
    results: list[dict[str, Any]] = []
    for index, step in enumerate(entry.steps, start=1):
        if before_step is not None and not before_step(index):
            return ToolResult.failure(
                state="flow_stopped",
                message=f"Flow '{entry.name}' stopped before step {index}.",
                data={
                    "flow_name": entry.name,
                    "total_steps": total,
                    "completed_steps": index - 1,
                    "stopped_before_step_index": index,
                    "results": results,
                    "real_execution": execute_real,
                },
                errors=[{"code": "flow_stopped", "step_index": index}],
            ).to_dict()
        if on_step is not None:
            on_step(index, "running", None)
        request = _step_to_request(
            step,
            execute_real=execute_real,
            confirm_work_area_clear=confirm_work_area_clear,
            confirm_estop_ready=confirm_estop_ready,
            confirmation_code=confirmation_code,
        )
        step_result = run_zmotion_operator_command(
            request=request,
            config=config,
            client_factory=client_factory,
            executor_factory=executor_factory,
        )
        results.append(
            {
                "step_index": index,
                "step_id": step.step_id,
                "func_id": step.func_id,
                "description": step.description,
                "result": step_result,
            }
        )
        if on_step is not None:
            on_step(index, "succeeded" if step_result.get("ok") else "failed", step_result)
        if not step_result.get("ok"):
            return ToolResult.failure(
                state="flow_step_failed",
                message=f"Flow '{entry.name}' failed at step {index}.",
                data={
                    "flow_name": entry.name,
                    "total_steps": total,
                    "completed_steps": index - 1,
                    "failed_step_index": index,
                    "failed_step_result": step_result,
                    "results": results,
                    "real_execution": execute_real,
                },
                errors=[{"code": "flow_step_failed", "step_index": index}],
            ).to_dict()

    return ToolResult.success(
        state="flow_completed",
        message=f"Flow '{entry.name}' completed {total} step(s).",
        data={
            "flow_name": entry.name,
            "total_steps": total,
            "results": results,
            "real_execution": execute_real,
        },
    ).to_dict()


def _step_to_request(
    step: FlowStep,
    *,
    execute_real: bool,
    confirm_work_area_clear: bool,
    confirm_estop_ready: bool,
    confirmation_code: str,
) -> ZMotionOperatorRequest:
    command = _FUNC_TO_COMMAND.get(int(step.func_id), "unsupported")
    parameters = _step_parameters(command, step)
    return ZMotionOperatorRequest(
        command=command,
        parameters=parameters,
        execute_real=execute_real,
        confirm_work_area_clear=confirm_work_area_clear,
        confirm_estop_ready=confirm_estop_ready,
        confirmation_code=confirmation_code,
    )


def _step_parameters(command: str, step: FlowStep) -> dict[str, Any]:
    params = dict(step.params or {})
    if command == "linear_move":
        return _linear_move_parameters(params, step)
    if command == "system":
        return {"action": str(params.get("action", ""))}
    if command == "delay":
        seconds = params.get("seconds", params.get("delay_sec", 0))
        return {"seconds": float(seconds or 0)}
    if command == "io":
        allowed = [int(channel) for channel in params.get("allowed_io_channels", [])]
        return {
            "io_number": int(params.get("io_number", 0)),
            "enabled": bool(params.get("enabled", False)),
            "allowed_io_channels": allowed,
        }
    return {"func_id": int(step.func_id)}


def _linear_move_parameters(params: dict[str, Any], step: FlowStep) -> dict[str, Any]:
    target_pose = params.get("target_pose")
    if not isinstance(target_pose, dict):
        target_pose = {
            "x": float(params.get("target_x", params.get("x", 0.0)) or 0.0),
            "y": float(params.get("target_y", params.get("y", 0.0)) or 0.0),
            "z": float(params.get("target_z", params.get("z", 0.0)) or 0.0),
            "rx": float(params.get("target_rx", params.get("rx", 0.0)) or 0.0),
            "ry": float(params.get("target_ry", params.get("ry", 0.0)) or 0.0),
            "rz": float(params.get("target_rz", params.get("rz", 0.0)) or 0.0),
        }
    speed_pct = float(params.get("speed_pct", step.spd_pct))
    return {
        "target_pose": target_pose,
        "speed_pct": speed_pct,
        "acceleration_pct": float(params.get("acceleration_pct", speed_pct)),
        "deceleration_pct": float(params.get("deceleration_pct", speed_pct)),
        "r_min": float(params.get("r_min", DEFAULT_WORKSPACE_R_MIN)),
        "r_max": float(params.get("r_max", DEFAULT_WORKSPACE_R_MAX)),
        "z_min": float(params.get("z_min", DEFAULT_WORKSPACE_Z_MIN)),
        "z_max": float(params.get("z_max", DEFAULT_WORKSPACE_Z_MAX)),
    }
