from __future__ import annotations

from robot_platform.application import AuthenticatedPrincipal
from robot_platform.backends.zmotion_adapter import ZMotionOperatorRequest, _is_confirmed
from robot_platform.execution import ExecutionPermitStore, ExecutionScope
from robot_platform.models import RobotState


def _state() -> RobotState:
    return RobotState(
        mode="idle",
        axes_mm={"x": 900.0, "y": 0.0, "z": 1000.0, "rx": 0.0, "ry": 0.0, "rz": 0.0},
        alarms=[],
        connected_real_device=True,
    )


def _parameters() -> dict:
    return {
        "target_pose": {"x": 900.0, "y": 0.0, "z": 999.0, "rx": 0.0, "ry": 0.0, "rz": 0.0},
        "speed_pct": 5.0,
        "acceleration_pct": 5.0,
        "deceleration_pct": 5.0,
        "r_min": 800.0,
        "r_max": 1000.0,
        "z_min": 900.0,
        "z_max": 1100.0,
    }


def _authorized_request() -> tuple[ZMotionOperatorRequest, ExecutionPermitStore, ExecutionScope]:
    parameters = _parameters()
    payload = {"command": "linear_move", "parameters": parameters}
    scope = ExecutionScope.for_payload(
        principal=AuthenticatedPrincipal("operator", "operator", "session", "test"),
        robot_id="robot-1",
        controller_id="controller-1",
        operation_type="linear_move",
        payload=payload,
        payload_schema_version="1",
        product_profile_version="1",
        capability_version="1",
        deployment_instance_id="deployment-1",
        core_version="1",
        plan_id="plan-1",
        plan_version="1",
    )
    store = ExecutionPermitStore()
    permit = store.issue(scope, operation_id="operation-1", idempotency_key="plan-1")
    assert store.reserve(permit.handle, scope)
    assert store.mark_executing(permit.handle)
    request = ZMotionOperatorRequest(
        command="linear_move",
        parameters=parameters,
        execute_real=True,
        confirm_work_area_clear=True,
        confirm_estop_ready=True,
        execution_permit_handle=permit.handle,
        execution_scope=scope,
        execution_operation_type="linear_move",
        execution_payload=payload,
        execution_dispatch_id="plan-1:0",
    )
    return request, store, scope


def test_backend_accepts_only_live_server_side_permit() -> None:
    request, store, _scope = _authorized_request()
    assert _is_confirmed(request, _state(), permit_verifier=store) is True


def test_static_legacy_confirmation_never_authorizes_write() -> None:
    request = ZMotionOperatorRequest(
        command="linear_move",
        parameters=_parameters(),
        execute_real=True,
        confirm_work_area_clear=True,
        confirm_estop_ready=True,
        confirmation_code="EXECUTE_ZMOTION_REAL",
        pending_plan_id="plan-1",
        confirm_code="RC-forged",
    )
    assert _is_confirmed(request, _state()) is False


def test_tampered_payload_is_rejected_at_backend_boundary() -> None:
    request, store, _scope = _authorized_request()
    request.execution_payload["parameters"]["target_pose"]["z"] = 950.0
    assert _is_confirmed(request, _state(), permit_verifier=store) is False


def test_consumed_permit_cannot_authorize_another_dispatch() -> None:
    request, store, _scope = _authorized_request()
    assert _is_confirmed(request, _state(), permit_verifier=store) is True
    assert store.complete(request.execution_permit_handle, {"ok": True})
    assert _is_confirmed(request, _state(), permit_verifier=store) is False
