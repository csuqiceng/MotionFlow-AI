"""Run a named flow by mapping each step to a restricted operation command.

Each ``FlowStep`` becomes one vendor-neutral operation request and is submitted
through an injected operation adapter — so every step independently passes the
safety gate and write protocol supplied by the selected backend. Execution is
sequential and stops on the first failing step.

Step ``func_id`` → command mapping: 108=linear_move, 104=system, 110=delay,
120=io. Step ``params`` use the operator's structured shape (``target_pose``
dict, ``speed_pct`` ...); a legacy ``target_x``/``delay_sec`` fallback is
accepted for compatibility.

Note: each step connects/reads/executes independently. This is intentionally
correct over fast — every step is safety-checked against fresh controller
state. A shared-client optimisation can come later.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Any, Callable

from robot_platform.application.operations import RobotOperationRequest
from robot_platform.backends.factory import RobotBackendConfig
from robot_platform.execution.permit import (
    ExecutionPermitVerifierPort,
    ExecutionScope,
    FlowStepExecutionGrant,
)
from robot_platform.flow.models import FlowEntry, FlowStep
from robot_platform.flow.events import FlowExecutionEvent
from robot_platform.flow.snapshot import FlowExecutionSnapshot, FlowSnapshotStep
from robot_platform.flow.schema import require_strict_io_parameters
from robot_platform.flow.nodes import (
    ActionNode, FlowNodeExecutionContext, FlowOutcomeUnknown, FlowStopped,
    HumanApprovalNode, execute_node_sync,
)
from robot_platform.models import ToolResult
from robot_platform.safety.config import (
    DEFAULT_WORKSPACE_R_MAX,
    DEFAULT_WORKSPACE_R_MIN,
    DEFAULT_WORKSPACE_Z_MAX,
    DEFAULT_WORKSPACE_Z_MIN,
)

_FUNC_TO_COMMAND: dict[int, str] = {
    108: "linear_move",
    104: "system",
    110: "delay",
    120: "io",
}


def run_flow(
    entry: FlowEntry | FlowExecutionSnapshot,
    *,
    config: RobotBackendConfig | None = None,
    execute_real: bool = False,
    confirm_work_area_clear: bool = False,
    confirm_estop_ready: bool = False,
    confirmation_code: str = "",
    execution_permit_handle: str = "",
    execution_scope: ExecutionScope | None = None,
    permit_verifier: ExecutionPermitVerifierPort | None = None,
    execution_operation_type: str = "",
    execution_payload: dict[str, Any] | None = None,
    execution_dispatch_id: str = "",
    flow_step_grants: tuple[FlowStepExecutionGrant, ...] = (),
    client_factory: Callable[..., Any] | None = None,
    executor_factory: Callable[..., Any] | None = None,
    operator_runner: Callable[..., dict[str, Any]] | None = None,
    on_step: Callable[[int, str, dict[str, Any] | None], None] | None = None,
    before_step: Callable[[int], bool] | None = None,
    allowed_io_output_channels: Collection[int] = (),
    execution_id: str = "flow-execution",
    on_event: Callable[[FlowExecutionEvent], None] | None = None,
    node_inputs: dict[str, Any] | None = None,
    approval_checker: Callable[[HumanApprovalNode], bool] | None = None,
) -> dict[str, Any]:
    flow_name = entry.flow_name if isinstance(entry, FlowExecutionSnapshot) else entry.name
    if not entry.steps:
        return ToolResult.failure(
            state="flow_empty",
            message="Flow has no steps.",
            data={"flow_name": flow_name},
            errors=[{"code": "flow_empty"}],
        ).to_dict()
    if execute_real and len(flow_step_grants) != len(entry.steps):
        return ToolResult.failure(
            state="flow_step_permits_required",
            message="Real Flow execution requires one child permit per immutable step.",
            errors=[{"code": "flow_step_permits_required"}],
        ).to_dict()

    runner = operator_runner or run_operator_command
    total = len(entry.steps)
    snapshot_hash = (
        entry.content_hash if isinstance(entry, FlowExecutionSnapshot) else ""
    )

    def emit(kind: str, *, index: int = 0, state: str = "") -> None:
        if on_event is not None:
            on_event(FlowExecutionEvent(
                execution_id=execution_id,
                snapshot_hash=snapshot_hash,
                kind=kind,
                step_index=index,
                state=state,
            ))

    emit("flow_started", state="running")
    results: list[dict[str, Any]] = []

    if isinstance(entry, FlowExecutionSnapshot):
        steps_by_index = {step.index: step for step in entry.steps}

        def run_action(action: ActionNode) -> dict[str, Any]:
            index = action.step_index
            if index is None or index not in steps_by_index:
                raise ValueError(f"Flow ActionNode '{action.node_id}' has no immutable step")
            step = steps_by_index[index]
            if before_step is not None and not before_step(index):
                raise FlowStopped(index)
            if on_step is not None:
                on_step(index, "running", None)
            emit("node_started", index=index, state="running")
            grant = flow_step_grants[index - 1] if execute_real else None
            request = _step_to_request(
                step, execute_real=execute_real,
                confirm_work_area_clear=confirm_work_area_clear,
                confirm_estop_ready=confirm_estop_ready,
                confirmation_code=confirmation_code,
                execution_permit_handle=(grant.permit_handle if grant else execution_permit_handle),
                execution_scope=(grant.scope if grant else execution_scope),
                execution_operation_type=execution_operation_type,
                execution_payload=execution_payload,
                execution_dispatch_id=(grant.dispatch_id if grant else execution_dispatch_id),
                allowed_io_output_channels=allowed_io_output_channels,
            )
            runner_kwargs: dict[str, Any] = dict(
                request=request, config=config, client_factory=client_factory,
                executor_factory=executor_factory,
            )
            if permit_verifier is not None:
                runner_kwargs["permit_verifier"] = permit_verifier
            step_result = runner(**runner_kwargs)
            results.append({
                "step_index": index, "step_id": step.step_id, "func_id": step.func_id,
                "description": step.description, "result": step_result,
            })
            succeeded = bool(step_result.get("ok"))
            if on_step is not None:
                on_step(index, "succeeded" if succeeded else "failed", step_result)
            emit("node_succeeded" if succeeded else "node_failed", index=index,
                 state="succeeded" if succeeded else "failed")
            if not succeeded:
                if "unknown" in str(step_result.get("state", "")):
                    raise FlowOutcomeUnknown("Flow action outcome is unknown")
                raise _FlowStepFailed(index, step_result)
            return step_result

        try:
            execute_node_sync(entry.root_node, FlowNodeExecutionContext(
                action_runner=run_action,
                inputs=(
                    dict(entry.inputs) if node_inputs is None else dict(node_inputs)
                ),
                approval_checker=approval_checker,
            ))
        except FlowStopped as exc:
            emit("flow_cancelled", index=exc.index, state="stopped")
            return ToolResult.failure(
                state="flow_stopped",
                message=f"Flow '{flow_name}' stopped before step {exc.index}.",
                data={"flow_name": flow_name, "total_steps": total,
                      "completed_steps": len(results),
                      "stopped_before_step_index": exc.index, "results": results,
                      "real_execution": execute_real},
                errors=[{"code": "flow_stopped", "step_index": exc.index}],
            ).to_dict()
        except _FlowStepFailed as exc:
            emit("flow_failed", index=exc.index, state="failed")
            return ToolResult.failure(
                state="flow_step_failed",
                message=f"Flow '{flow_name}' failed at step {exc.index}.",
                data={"flow_name": flow_name, "total_steps": total,
                      "completed_steps": max(len(results) - 1, 0),
                      "failed_step_index": exc.index,
                      "failed_step_result": exc.result, "results": results,
                      "real_execution": execute_real},
                errors=[{"code": "flow_step_failed", "step_index": exc.index}],
            ).to_dict()
        except Exception as exc:
            emit("flow_failed", state="failed")
            return ToolResult.failure(
                state="flow_node_failed",
                message=f"Flow '{flow_name}' node graph failed.",
                data={"flow_name": flow_name, "total_steps": total,
                      "completed_steps": len(results), "results": results,
                      "real_execution": execute_real},
                errors=[{"code": "flow_node_failed", "type": type(exc).__name__}],
            ).to_dict()
        emit("flow_completed", state="completed")
        return ToolResult.success(
            state="flow_completed",
            message=f"Flow '{flow_name}' completed {len(results)} action(s).",
            data={"flow_name": flow_name, "total_steps": total,
                  "results": results, "real_execution": execute_real},
        ).to_dict()

    for index, step in enumerate(entry.steps, start=1):
        if before_step is not None and not before_step(index):
            emit("flow_cancelled", index=index, state="stopped")
            return ToolResult.failure(
                state="flow_stopped",
                message=f"Flow '{flow_name}' stopped before step {index}.",
                data={
                    "flow_name": flow_name,
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
        emit("node_started", index=index, state="running")
        grant = flow_step_grants[index - 1] if execute_real else None
        request = _step_to_request(
            step,
            execute_real=execute_real,
            confirm_work_area_clear=confirm_work_area_clear,
            confirm_estop_ready=confirm_estop_ready,
            confirmation_code=confirmation_code,
            execution_permit_handle=(grant.permit_handle if grant else execution_permit_handle),
            execution_scope=(grant.scope if grant else execution_scope),
            execution_operation_type=execution_operation_type,
            execution_payload=execution_payload,
            execution_dispatch_id=(grant.dispatch_id if grant else execution_dispatch_id),
            allowed_io_output_channels=allowed_io_output_channels,
        )
        runner_kwargs: dict[str, Any] = dict(
            request=request,
            config=config,
            client_factory=client_factory,
            executor_factory=executor_factory,
        )
        if permit_verifier is not None:
            runner_kwargs["permit_verifier"] = permit_verifier
        step_result = runner(**runner_kwargs)
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
            emit("node_failed", index=index, state="failed")
            emit("flow_failed", index=index, state="failed")
            return ToolResult.failure(
                state="flow_step_failed",
                message=f"Flow '{flow_name}' failed at step {index}.",
                data={
                    "flow_name": flow_name,
                    "total_steps": total,
                    "completed_steps": index - 1,
                    "failed_step_index": index,
                    "failed_step_result": step_result,
                    "results": results,
                    "real_execution": execute_real,
                },
                errors=[{"code": "flow_step_failed", "step_index": index}],
            ).to_dict()

        emit("node_succeeded", index=index, state="succeeded")

    emit("flow_completed", state="completed")
    return ToolResult.success(
        state="flow_completed",
        message=f"Flow '{flow_name}' completed {total} step(s).",
        data={
            "flow_name": flow_name,
            "total_steps": total,
            "results": results,
            "real_execution": execute_real,
        },
    ).to_dict()


def _step_to_request(
    step: FlowStep | FlowSnapshotStep,
    *,
    execute_real: bool,
    confirm_work_area_clear: bool,
    confirm_estop_ready: bool,
    confirmation_code: str,
    execution_permit_handle: str = "",
    execution_scope: ExecutionScope | None = None,
    execution_operation_type: str = "",
    execution_payload: dict[str, Any] | None = None,
    execution_dispatch_id: str = "",
    allowed_io_output_channels: Collection[int] = (),
) -> RobotOperationRequest:
    if isinstance(step, FlowSnapshotStep):
        command = step.command
        parameters = dict(step.parameters)
    else:
        command = _FUNC_TO_COMMAND.get(int(step.func_id), "unsupported")
        parameters = _step_parameters(command, step)
    if command == "io":
        parameters["allowed_io_channels"] = list(allowed_io_output_channels)
    return RobotOperationRequest(
        command=command,
        parameters=parameters,
        execute_real=execute_real,
        confirm_work_area_clear=confirm_work_area_clear,
        confirm_estop_ready=confirm_estop_ready,
        confirmation_code=confirmation_code,
        execution_permit_handle=execution_permit_handle,
        execution_scope=execution_scope,
        execution_operation_type=execution_operation_type,
        execution_payload=execution_payload,
        execution_dispatch_id=execution_dispatch_id,
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
        return require_strict_io_parameters(params)
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


def run_operator_command(**kwargs: Any) -> dict[str, Any]:
    del kwargs
    return ToolResult.failure(
        state="robot_operation_not_composed",
        message="Flow execution requires an injected operation adapter.",
        errors=[{"code": "robot_operation_not_composed"}],
    ).to_dict()


class _FlowStepFailed(RuntimeError):
    def __init__(self, index: int, result: dict[str, Any]) -> None:
        self.index = index
        self.result = result
