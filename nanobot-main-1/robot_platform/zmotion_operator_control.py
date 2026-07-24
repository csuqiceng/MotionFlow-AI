from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import dataclass, replace
from typing import Any, Callable, Protocol

from robot_platform.backends.factory import RobotBackendConfig, resolve_sdk_config
from robot_platform.backends.zmotion_backend import (
    CANCEL_LATCH_BIT,
    SYSTEM_STATE_START,
    ModbusReadRequest,
    ZMotionReadOnlyBackend,
)
from robot_platform.backends.zmotion_sdk import ZMotionSdkClient, ZMotionSdkError
from robot_platform.backends.zmotion_sequence import ZMotionSequenceRunner
from robot_platform.backends.zmotion_shared_client import shared_client_enabled
from robot_platform.backends.zmotion_write_executor import ZMotionWriteExecutor
from robot_platform.backends.zmotion_write_plan import ZMotionCommandPlan, ZMotionWritePlanner
from robot_platform.execution import (
    PendingPlanStore,
    SessionGateStore,
    verify_confirm_code,
)
from robot_platform.models import AXIS_NAMES, RobotState, ToolResult
from robot_platform.safety import (
    ExecutionGateInput,
    SafetyServices,
    build_controller_snapshot,
    build_l1_plan,
    evaluate_execution_gate,
)

REAL_EXECUTION_CONFIRMATION_CODE = "EXECUTE_ZMOTION_REAL"
# First-test motion envelope. Overridable via env so a simulated controller
# (or a validated real controller) can exercise larger moves without code edits.
FIRST_TEST_MAX_DELTA = float(os.environ.get("ROBOT_AI_FIRST_TEST_MAX_DELTA", "5.0"))
FIRST_TEST_MAX_PERCENT = float(os.environ.get("ROBOT_AI_FIRST_TEST_MAX_PERCENT", "5.0"))


def _default_safety_services() -> SafetyServices:
    return SafetyServices.from_limits()


# Tests may override this to inject custom limits or services.
_safety_services_factory: Callable[[], SafetyServices] = _default_safety_services

# POC process-wide pending-plan / session-gate stores. Tests may monkeypatch
# these module attributes to inject fresh instances.
_PENDING_PLAN_STORE = PendingPlanStore()
_SESSION_GATE_STORE = SessionGateStore()


def _is_confirmed(
    request: ZMotionOperatorRequest,
    state: RobotState,  # noqa: ARG001 - reserved for future state-based checks
    *,
    session_key: str | None = None,
) -> bool:
    """Decide whether the execution gate's ``confirmed`` flag is satisfied.

    Three paths:
      * WebUI (pending plan + RC- confirm code): all of verify_confirm_code,
        PendingPlanStore.verify (params match + plan confirmed) and
        SessionGateStore.is_confirmed must pass.
      * CLI (EXECUTE_ZMOTION_REAL confirmation_code): unchanged, human operator.
      * Otherwise: not confirmed.
    """
    if request.confirm_code and request.pending_plan_id:
        if session_key is None:
            from robot_platform.runtime import current_robot_request_session_key

            session_key = current_robot_request_session_key()
        key = session_key
        if not verify_confirm_code(request.pending_plan_id, request.confirm_code):
            return False
        if not _PENDING_PLAN_STORE.verify(request.pending_plan_id, request.parameters):
            return False
        return _SESSION_GATE_STORE.is_confirmed(key, request.pending_plan_id)
    if request.confirmation_code == REAL_EXECUTION_CONFIRMATION_CODE:
        return True
    return False


def _run_safety_gate(request: ZMotionOperatorRequest, state: RobotState) -> dict[str, Any] | None:
    """Run the L1 safety check + execution gate before plan building.

    Returns a failure dict (ToolResult.to_dict) when the command is blocked,
    or None when it may proceed. Motion commands (linear_move / linear_path)
    additionally get the L1 position/space/speed precheck; non-motion commands
    only run the execution gate (confirmation flow), since their L1 estop/alarm
    items would wrongly block e.g. ``release_emergency_stop``.
    """
    if request.command == "system":
        action = str(request.parameters.get("action", ""))
        if action == "stop_current" and state.mode == "idle":
            return ToolResult.failure(
                state="stop_current_not_allowed_when_idle",
                message=(
                    "stop_current is rejected when the controller is idle "
                    "(no active function to cancel)."
                ),
                errors=[{"code": "stop_current_not_allowed_when_idle"}],
            ).to_dict()
        if action == "release_cancel" and not state.cancel_latch:
            return ToolResult.failure(
                state="release_cancel_no_latch",
                message="release_cancel is rejected when no cancel latch is set.",
                errors=[{"code": "release_cancel_no_latch"}],
            ).to_dict()

    services = _safety_services_factory()
    snapshot = build_controller_snapshot(state)

    if request.command in {"linear_move", "linear_path"}:
        motion_failure = _check_motion_safety(services, request, snapshot)
        if motion_failure is not None:
            return motion_failure

    gate = evaluate_execution_gate(
        ExecutionGateInput(
            action_type=request.command,
            is_execution=request.execute_real,
            has_wake_word=True,
            permission_ok=True,
            missing_fields=(),
            bounds_ok=True,
            safety_ok=True,
            requires_confirmation=request.execute_real,
            has_pending_confirm=request.confirm_work_area_clear and request.confirm_estop_ready,
            confirmed=_is_confirmed(request, state),
        )
    )
    if not gate.ok:
        return gate.to_dict()
    return None


def _check_motion_safety(
    services: SafetyServices,
    request: ZMotionOperatorRequest,
    snapshot: dict[str, Any],
) -> dict[str, Any] | None:
    """Run the L1 checker against every motion target. None = params deferred."""
    targets = _extract_motion_targets(request)
    if not targets:
        # Malformed/missing params: skip and let downstream validation report.
        return None
    speed = _extract_motion_speed(request)
    func_id = 108
    for target in targets:
        plan = build_l1_plan(func_id=func_id, target=target, speed=speed, action_type="move")
        verdict = services.checker.check_target(
            target_pose=[target[axis] for axis in AXIS_NAMES],
            snapshot=snapshot,
            speed=speed,
            func_id=func_id,
        )
        if not verdict["safe"]:
            return ToolResult.failure(
                state="zmotion_operator_safety_blocked",
                message=str(verdict.get("detail_zh") or "Safety precheck blocked the command."),
                data={
                    "blocking_level": verdict.get("blocking_level"),
                    "suggestion_zh": verdict.get("suggestion_zh"),
                    "items": verdict.get("items"),
                    "target_pose": target,
                    "plan": plan,
                },
                errors=[
                    {
                        "code": "safety_precheck_failed",
                        "blocking_level": verdict.get("blocking_level"),
                    }
                ],
            ).to_dict()
    return None


def _extract_motion_targets(request: ZMotionOperatorRequest) -> list[dict[str, float]] | None:
    parameters = request.parameters
    try:
        if request.command == "linear_move":
            return [_coerce_pose(parameters["target_pose"])]
        if request.command == "linear_path":
            return [_coerce_pose(item) for item in parameters["target_poses"]]
    except (KeyError, TypeError, ValueError):
        return None
    return None


def _extract_motion_speed(request: ZMotionOperatorRequest) -> dict[str, float]:
    parameters = request.parameters
    try:
        return {
            "spd_pct": float(parameters["speed_pct"]),
            "acc_pct": float(parameters["acceleration_pct"]),
            "dec_pct": float(parameters["deceleration_pct"]),
        }
    except (KeyError, TypeError, ValueError):
        return {}


class ZMotionOperatorClient(Protocol):
    connected: bool

    def connect(self) -> None: ...

    def disconnect(self) -> None: ...

    def read_modbus_float(self, request: ModbusReadRequest) -> list[float]: ...

    def read_modbus_long(self, request: ModbusReadRequest) -> list[int]: ...


class ZMotionOperatorExecutor(Protocol):
    def execute(
        self,
        plan: ZMotionCommandPlan,
        *,
        allow_real_motion_writes: bool = False,
        confirmed_real_motion: bool = False,
    ) -> dict: ...


@dataclass(frozen=True)
class ZMotionOperatorRequest:
    command: str
    parameters: dict[str, Any]
    execute_real: bool = False
    confirm_work_area_clear: bool = False
    confirm_estop_ready: bool = False
    confirmation_code: str = ""
    # WebUI pending-plan confirmation path (distinct from the CLI's
    # ``confirmation_code`` == EXECUTE_ZMOTION_REAL). When ``pending_plan_id``
    # and ``confirm_code`` are both set, ``_is_confirmed`` verifies them via the
    # PendingPlanStore / SessionGateStore / verify_confirm_code.
    pending_plan_id: str = ""
    confirm_code: str = ""


@dataclass(frozen=True)
class CartesianWorkspaceLimits:
    r_min: float
    r_max: float
    z_min: float
    z_max: float

    def is_valid(self) -> bool:
        values = (self.r_min, self.r_max, self.z_min, self.z_max)
        return (
            all(math.isfinite(value) for value in values)
            and self.r_min >= 0.0
            and self.r_max > self.r_min
            and self.z_max > self.z_min
        )

    def contains(self, pose: dict[str, float]) -> bool:
        radius = math.hypot(float(pose["x"]), float(pose["y"]))
        z_value = float(pose["z"])
        return (
            self.r_min <= radius <= self.r_max
            and self.z_min <= z_value <= self.z_max
        )


ClientFactory = Callable[[RobotBackendConfig], ZMotionOperatorClient]
ExecutorFactory = Callable[[ZMotionOperatorClient], ZMotionOperatorExecutor]


def run_zmotion_operator_command(
    *,
    request: ZMotionOperatorRequest,
    config: RobotBackendConfig | None = None,
    client_factory: ClientFactory | None = None,
    executor_factory: ExecutorFactory | None = None,
) -> dict[str, Any]:
    resolved_config = config or RobotBackendConfig.from_env()
    missing = _missing_config(resolved_config)
    if missing:
        return ToolResult.failure(
            state="zmotion_operator_configuration_missing",
            message="ZMotion operator control requires host, wrapper, and DLL configuration.",
            data={"missing": missing},
            errors=[{"code": "zmotion_operator_configuration_missing"}],
        ).to_dict()

    if _confirmation_attempted(request) and not _fully_confirmed(request):
        return ToolResult.failure(
            state="zmotion_operator_confirmation_required",
            message="All real-controller execution confirmations are required.",
            data={"required_code": REAL_EXECUTION_CONFIRMATION_CODE},
            errors=[{"code": "zmotion_operator_confirmation_required"}],
        ).to_dict()

    create_client = client_factory or _create_sdk_client
    create_executor = executor_factory or ZMotionWriteExecutor
    use_shared = client_factory is None and shared_client_enabled()
    client = None
    try:
        if use_shared:
            from robot_platform.backends import zmotion_shared_client as shared

            # Status backend configures once at gateway startup; only (re)configure
            # if this is the first consumer (e.g. operator runs before any status poll).
            if not shared.is_configured():
                shared.configure(
                    resolved_config.controller_host,
                    resolve_sdk_config(resolved_config),
                )
            client = shared.get()
        else:
            client = create_client(resolved_config)
            client.connect()
        state = _read_robot_state(client, resolved_config.controller_host)
        if not state.connected_real_device:
            return ToolResult.failure(
                state="zmotion_operator_state_read_failed",
                message="Unable to confirm a connected real controller.",
                data={"robot_state": state.to_dict()},
                errors=[{"code": "real_device_not_connected"}],
            ).to_dict()

        plan_or_error = _build_plan(request, state)
        if isinstance(plan_or_error, dict):
            return plan_or_error
        plan = plan_or_error

        if not request.execute_real:
            if isinstance(plan_or_error, list):
                plan_data: dict[str, Any] = {
                    "plans": [plan.to_dict() for plan in plan_or_error],
                    "segment_count": len(plan_or_error),
                }
            else:
                plan_data = {"plan": plan_or_error.to_dict()}
            return ToolResult.success(
                state="zmotion_operator_dry_run",
                message=(
                    "Dry-run plan generated successfully (ok=true, no controller write issued). "
                    "plan.blockers lists the requirements for REAL execution (operator confirmation "
                    "+ write-enable), which is operator-only via the CLI/bridge — they are NOT errors. "
                    "Report this to the user as 'plan ready, no motion executed'."
                ),
                data={
                    "robot_state": state.to_dict(),
                    **plan_data,
                    "real_execution": False,
                },
            ).to_dict()

        if isinstance(plan_or_error, list):
            blocked = [plan for plan in plan_or_error if not plan.executable or plan.blockers]
            if blocked:
                return ToolResult.failure(
                    state="zmotion_operator_plan_blocked",
                    message="The operator command plan is blocked.",
                    data={
                        "blockers": list(blocked[0].blockers),
                        "plans": [plan.to_dict() for plan in plan_or_error],
                    },
                ).to_dict()

            executor = create_executor(client)
            return ZMotionSequenceRunner(executor).execute(
                plan_or_error,
                allow_real_motion_writes=True,
                confirmed_real_motion=True,
            )

        plan = plan_or_error
        if not plan.executable or plan.blockers:
            return ToolResult.failure(
                state="zmotion_operator_plan_blocked",
                message="The operator command plan is blocked.",
                data={
                    "blockers": list(plan.blockers),
                    "plan": plan.to_dict(),
                },
            ).to_dict()

        executor = create_executor(client)
        return executor.execute(
            plan,
            allow_real_motion_writes=True,
            confirmed_real_motion=True,
        )
    except Exception as exc:
        # Only drop the shared connection when the failure is actually controller/SDK
        # related — a planning/build error (KeyError, ValueError, ...) leaves the
        # connection healthy, and resetting it would blip the status poller.
        if use_shared and isinstance(exc, ZMotionSdkError):
            from robot_platform.backends import zmotion_shared_client as shared

            shared.reset()
        return ToolResult.failure(
            state="zmotion_operator_failed",
            message=str(exc),
            errors=[{"type": exc.__class__.__name__, "message": str(exc)}],
        ).to_dict()
    finally:
        if not use_shared and client is not None:
            client.disconnect()


def _build_plan(
    request: ZMotionOperatorRequest,
    state: RobotState,
) -> ZMotionCommandPlan | list[ZMotionCommandPlan] | dict[str, Any]:
    safety_failure = _run_safety_gate(request, state)
    if safety_failure is not None:
        return safety_failure
    planner = ZMotionWritePlanner()
    gates = {
        "confirmed_real_motion": request.execute_real,
        "allow_real_motion_writes": request.execute_real,
    }
    parameters = request.parameters
    try:
        if request.command == "system":
            return planner.plan_system_control(
                action=str(parameters["action"]),
                robot_state=state,
                **gates,
            )
        if request.command == "delay":
            return planner.plan_delay(
                seconds=float(parameters["seconds"]),
                robot_state=state,
                **gates,
            )
        if request.command == "io":
            return planner.plan_io(
                io_number=int(parameters["io_number"]),
                enabled=bool(parameters["enabled"]),
                allowed_io_channels={
                    int(value) for value in parameters["allowed_io_channels"]
                },
                robot_state=state,
                **gates,
            )
        if request.command == "linear_move":
            validation = _validate_linear_motion(parameters, state)
            if validation is not None:
                return validation
            return planner.plan_linear_move(
                target_pose=_coerce_pose(parameters["target_pose"]),
                robot_state=state,
                speed_pct=float(parameters["speed_pct"]),
                acceleration_pct=float(parameters["acceleration_pct"]),
                deceleration_pct=float(parameters["deceleration_pct"]),
                motion_percent_limit=FIRST_TEST_MAX_PERCENT,
                **gates,
            )
        if request.command == "linear_path":
            validation = _validate_linear_path(parameters, state)
            if validation is not None:
                return validation
            return [
                planner.plan_linear_move(
                    target_pose=pose,
                    robot_state=state,
                    speed_pct=float(parameters["speed_pct"]),
                    acceleration_pct=float(parameters["acceleration_pct"]),
                    deceleration_pct=float(parameters["deceleration_pct"]),
                    motion_percent_limit=FIRST_TEST_MAX_PERCENT,
                    **gates,
                )
                for pose in [_coerce_pose(item) for item in parameters["target_poses"]]
            ]
    except (KeyError, TypeError, ValueError) as exc:
        return ToolResult.failure(
            state="zmotion_operator_invalid_request",
            message=f"Invalid operator command parameters: {exc}",
            errors=[{"code": "zmotion_operator_invalid_request"}],
        ).to_dict()

    return ToolResult.failure(
        state="zmotion_operator_unsupported_command",
        message=f"Unsupported operator command: {request.command}",
        errors=[{"code": "zmotion_operator_unsupported_command"}],
    ).to_dict()


def _validate_linear_motion(
    parameters: dict[str, Any],
    state: RobotState,
) -> dict[str, Any] | None:
    try:
        target = _coerce_pose(parameters["target_pose"])
        percentages = (
            float(parameters["speed_pct"]),
            float(parameters["acceleration_pct"]),
            float(parameters["deceleration_pct"]),
        )
        limits = CartesianWorkspaceLimits(
            r_min=float(parameters["r_min"]),
            r_max=float(parameters["r_max"]),
            z_min=float(parameters["z_min"]),
            z_max=float(parameters["z_max"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return ToolResult.failure(
            state="zmotion_operator_invalid_request",
            message=f"Invalid motion parameters: {exc}",
        ).to_dict()

    if not limits.is_valid():
        return ToolResult.failure(
            state="zmotion_operator_workspace_invalid",
            message="Software workspace limits are invalid.",
            data={"workspace": limits.__dict__},
        ).to_dict()

    if any(
        not math.isfinite(value)
        or value <= 0.0
        or value > FIRST_TEST_MAX_PERCENT
        for value in percentages
    ):
        return ToolResult.failure(
            state="zmotion_operator_first_test_limit_exceeded",
            message="First-test motion is limited to 5 units and 5 percent.",
            data={
                "max_delta": FIRST_TEST_MAX_DELTA,
                "max_percent": FIRST_TEST_MAX_PERCENT,
            },
        ).to_dict()

    delta_error = _validate_segment_delta(dict(state.axes_mm), target)
    if delta_error is not None:
        return delta_error

    if not limits.contains(target):
        return ToolResult.failure(
            state="zmotion_operator_target_outside_workspace",
            message="The requested target is outside the supplied software workspace.",
            data={"target_pose": target, "workspace": limits.__dict__},
        ).to_dict()
    return None


def _validate_linear_path(
    parameters: dict[str, Any],
    state: RobotState,
) -> dict[str, Any] | None:
    try:
        raw_targets = parameters["target_poses"]
        if not isinstance(raw_targets, list):
            raise TypeError("target_poses must be a list")
        targets = [_coerce_pose(item) for item in raw_targets]
    except (KeyError, TypeError, ValueError) as exc:
        return ToolResult.failure(
            state="zmotion_operator_invalid_request",
            message=f"Invalid linear path parameters: {exc}",
        ).to_dict()

    if not targets:
        return ToolResult.failure(
            state="zmotion_operator_invalid_request",
            message="linear_path requires at least one target pose.",
        ).to_dict()

    motion_parameters = dict(parameters)
    current_pose = dict(state.axes_mm)
    for target in targets:
        single_parameters = {**motion_parameters, "target_pose": target}
        single_validation = _validate_linear_motion(single_parameters, replace_state_pose(state, current_pose))
        if single_validation is not None:
            return single_validation
        current_pose = target
    return None


def _validate_segment_delta(
    current_pose: dict[str, float],
    target_pose: dict[str, float],
) -> dict[str, Any] | None:
    if set(current_pose) != set(AXIS_NAMES):
        return ToolResult.failure(
            state="zmotion_operator_invalid_request",
            message="Current controller pose is incomplete.",
            errors=[{"code": "invalid_current_pose"}],
        ).to_dict()

    for axis in AXIS_NAMES:
        current = float(current_pose[axis])
        target = float(target_pose[axis])
        if not math.isfinite(current) or not math.isfinite(target):
            return ToolResult.failure(
                state="zmotion_operator_invalid_request",
                message="Current or target pose contains a non-finite value.",
                errors=[{"code": "invalid_pose"}],
            ).to_dict()
        if abs(target - current) > FIRST_TEST_MAX_DELTA:
            return ToolResult.failure(
                state="zmotion_operator_first_test_limit_exceeded",
                message="First-test motion is limited to 5 units and 5 percent.",
                data={
                    "max_delta": FIRST_TEST_MAX_DELTA,
                    "max_percent": FIRST_TEST_MAX_PERCENT,
                    "axis": axis,
                    "delta": target - current,
                },
            ).to_dict()
    return None


def _coerce_pose(raw_pose: Any) -> dict[str, float]:
    if not isinstance(raw_pose, dict):
        raise TypeError("target pose must be an object")
    if set(raw_pose) != set(AXIS_NAMES):
        raise ValueError("target pose must include x, y, z, rx, ry, rz")
    pose = {axis: float(raw_pose[axis]) for axis in AXIS_NAMES}
    if any(not math.isfinite(value) for value in pose.values()):
        raise ValueError("target pose values must be finite")
    return pose


def replace_state_pose(state: RobotState, axes_mm: dict[str, float]) -> RobotState:
    return RobotState(
        mode=state.mode,
        axes_mm=dict(axes_mm),
        alarms=list(state.alarms),
        connected_real_device=state.connected_real_device,
    )


def _confirmation_attempted(request: ZMotionOperatorRequest) -> bool:
    return (
        request.execute_real
        or request.confirm_work_area_clear
        or request.confirm_estop_ready
        or bool(request.confirmation_code)
        or bool(request.pending_plan_id)
        or bool(request.confirm_code)
    )


def _fully_confirmed(request: ZMotionOperatorRequest) -> bool:
    # CLI path: EXECUTE_ZMOTION_REAL confirmation code.
    cli_confirmed = (
        request.execute_real
        and request.confirm_work_area_clear
        and request.confirm_estop_ready
        and request.confirmation_code == REAL_EXECUTION_CONFIRMATION_CODE
    )
    if cli_confirmed:
        return True
    # WebUI path: pending_plan_id + confirm_code present. The actual verification
    # (verify_confirm_code + plan params + session gate) is performed in
    # ``_is_confirmed`` inside ``_run_safety_gate``; here we only check that the
    # operator supplied both confirm flags so the gate's has_pending_confirm
    # passes. Param/code validity is enforced downstream.
    if (
        request.execute_real
        and request.confirm_work_area_clear
        and request.confirm_estop_ready
        and request.pending_plan_id
        and request.confirm_code
    ):
        return True
    return False


def _missing_config(config: RobotBackendConfig) -> list[str]:
    missing: list[str] = []
    if not config.controller_host.strip():
        missing.append("ROBOT_CONTROLLER_HOST")
    if not config.zmotion_wrapper_path.strip():
        missing.append("ROBOT_ZMOTION_WRAPPER_PATH")
    if not config.zmotion_dll_dir.strip():
        missing.append("ROBOT_ZMOTION_DLL_DIR")
    return missing


def _read_robot_state(
    client: ZMotionOperatorClient,
    host: str,
) -> RobotState:
    del host
    pose = client.read_modbus_float(ModbusReadRequest(start_vr=1612, count=6))
    status_values = client.read_modbus_long(ModbusReadRequest(start_vr=34, count=1))
    alarm_values = client.read_modbus_long(ModbusReadRequest(start_vr=38, count=1))
    system_state_values = client.read_modbus_long(
        ModbusReadRequest(start_vr=SYSTEM_STATE_START, count=1)
    )
    motion_values = client.read_modbus_float(ModbusReadRequest(start_vr=56, count=1))
    if (
        len(pose) < 6
        or not status_values
        or not alarm_values
        or not system_state_values
        or not motion_values
    ):
        raise RuntimeError("Incomplete ZMotion state read.")

    status = int(status_values[0])
    alarm = int(alarm_values[0])
    motion = float(motion_values[0])
    axes = ("x", "y", "z", "rx", "ry", "rz")
    return RobotState(
        mode=ZMotionReadOnlyBackend._mode_from_status(
            status_raw=status,
            alarm_detail=alarm,
            motion_state=motion,
        ),
        axes_mm={axis: float(pose[index]) for index, axis in enumerate(axes)},
        alarms=ZMotionReadOnlyBackend._alarms_from_status(
            status_raw=status,
            alarm_detail=alarm,
        ),
        connected_real_device=True,
        cancel_latch=bool((int(system_state_values[0]) >> CANCEL_LATCH_BIT) & 1),
    )


def _create_sdk_client(config: RobotBackendConfig) -> ZMotionSdkClient:
    sdk_config = resolve_sdk_config(config)
    if sdk_config is None:
        raise ZMotionSdkError(
            f"ZMotion SDK paths not configured for {config.controller_host}."
        )
    return ZMotionSdkClient(host=config.controller_host, sdk_config=sdk_config)


def main(
    argv: list[str] | None = None,
    *,
    runner: Callable[..., dict[str, Any]] = run_zmotion_operator_command,
) -> int:
    parser = argparse.ArgumentParser(
        description="Dry-run or explicitly execute restricted ZMotion commands."
    )
    parser.add_argument("--host", help="Override ROBOT_CONTROLLER_HOST.")
    parser.add_argument("--wrapper-path", help="Override ROBOT_ZMOTION_WRAPPER_PATH.")
    parser.add_argument("--dll-dir", help="Override ROBOT_ZMOTION_DLL_DIR.")
    parser.add_argument("--execute-real", action="store_true")
    parser.add_argument("--confirm-work-area-clear", action="store_true")
    parser.add_argument("--confirm-estop-ready", action="store_true")
    parser.add_argument("--confirmation-code", default="")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    system = subparsers.add_parser("system")
    system.add_argument(
        "--action",
        required=True,
        choices=[
            "emergency_stop",
            "release_emergency_stop",
            "pause",
            "resume",
            "stop_current",
            "release_cancel",
            "alarm_reset",
        ],
    )

    linear = subparsers.add_parser("linear-move")
    for axis in AXIS_NAMES:
        linear.add_argument(f"--{axis}", required=True, type=float)
    _add_motion_common_args(linear)

    path = subparsers.add_parser("linear-path")
    path.add_argument("--points-json", required=True)
    _add_motion_common_args(path)

    delay = subparsers.add_parser("delay")
    delay.add_argument("--seconds", required=True, type=float)

    io_parser = subparsers.add_parser("io")
    io_parser.add_argument("--io-number", required=True, type=int)
    io_parser.add_argument("--state", required=True, choices=["on", "off"])
    io_parser.add_argument("--allowed-io", required=True, type=_parse_allowed_io)

    args = parser.parse_args(argv)
    request = ZMotionOperatorRequest(
        command=args.command.replace("-", "_"),
        parameters=_parameters_from_args(args),
        execute_real=bool(args.execute_real),
        confirm_work_area_clear=bool(args.confirm_work_area_clear),
        confirm_estop_ready=bool(args.confirm_estop_ready),
        confirmation_code=str(args.confirmation_code),
    )
    env_config = RobotBackendConfig.from_env()
    config = replace(
        env_config,
        controller_host=args.host or env_config.controller_host,
        zmotion_wrapper_path=args.wrapper_path or env_config.zmotion_wrapper_path,
        zmotion_dll_dir=args.dll_dir or env_config.zmotion_dll_dir,
    )
    result = runner(request=request, config=config)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result.get("message", ""))
    return 0 if result.get("ok") else 1


def _parameters_from_args(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "system":
        return {"action": args.action}
    if args.command == "linear-move":
        return {
            "target_pose": {axis: float(getattr(args, axis)) for axis in AXIS_NAMES},
            "speed_pct": args.speed_pct,
            "acceleration_pct": args.acceleration_pct,
            "deceleration_pct": args.deceleration_pct,
            "r_min": args.r_min,
            "r_max": args.r_max,
            "z_min": args.z_min,
            "z_max": args.z_max,
        }
    if args.command == "linear-path":
        raw_points = json.loads(args.points_json)
        if not isinstance(raw_points, list):
            raise argparse.ArgumentTypeError("--points-json must be a JSON list.")
        return {
            "target_poses": [_coerce_pose(point) for point in raw_points],
            "speed_pct": args.speed_pct,
            "acceleration_pct": args.acceleration_pct,
            "deceleration_pct": args.deceleration_pct,
            "r_min": args.r_min,
            "r_max": args.r_max,
            "z_min": args.z_min,
            "z_max": args.z_max,
        }
    if args.command == "delay":
        return {"seconds": args.seconds}
    return {
        "io_number": args.io_number,
        "enabled": args.state == "on",
        "allowed_io_channels": args.allowed_io,
    }


def _parse_allowed_io(value: str) -> list[int]:
    try:
        channels = [int(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "--allowed-io must be a comma-separated integer list."
        ) from exc
    if not channels:
        raise argparse.ArgumentTypeError("--allowed-io must contain at least one channel.")
    return channels


def _add_motion_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--speed-pct", required=True, type=float)
    parser.add_argument("--acceleration-pct", required=True, type=float)
    parser.add_argument("--deceleration-pct", required=True, type=float)
    parser.add_argument("--r-min", required=True, type=float)
    parser.add_argument("--r-max", required=True, type=float)
    parser.add_argument("--z-min", required=True, type=float)
    parser.add_argument("--z-max", required=True, type=float)
