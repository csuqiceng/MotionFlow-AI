from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest

from robot_platform.application import (
    AuthenticatedPrincipal,
    RobotMotionApplicationService,
    RobotMotionError,
    RobotMotionExecutionCommand,
    RobotMotionResponse,
)
from robot_platform.execution import (
    ExecutionPermitState,
    ExecutionPermitStore,
    ExecutionScope,
    PendingPlanStore,
    SessionGateStore,
)


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal("operator-1", "operator", "session-1", "test")


def _prepared(*, command="linear_move", parameters=None, platform=None):
    parameters = parameters or {"target_pose": {"x": 1.0}}
    plans = PendingPlanStore()
    gates = SessionGateStore()
    permits = ExecutionPermitStore()
    plan = plans.create(
        command=command, parameters=parameters,
        dry_run_result={"ok": True, "state": "planned"},
    )
    plans.confirm(plan.plan_id)
    gates.set_pending_plan("robot-server:session-1", plan.plan_id)
    gates.confirm("robot-server:session-1", plan.plan_id)
    scope = ExecutionScope.for_payload(
        principal=_principal(), robot_id="robot-1", controller_id="controller-1",
        operation_type=command,
        payload={"command": command, "parameters": plan.parameters},
        payload_schema_version="1", product_profile_version="profile-1",
        capability_version="cap-1", deployment_instance_id="deployment-1",
        core_version="core-1", plan_id=plan.plan_id, plan_version=plan.plan_version,
    )
    permit = permits.issue(
        scope, operation_id=f"motion:{plan.plan_id}", idempotency_key=plan.plan_id,
    )
    receipt = plans.authorize(plan.plan_id, permit_handle=permit.handle)
    service = RobotMotionApplicationService(
        platform or MagicMock(), plans, gates, permits,
        robot_id="robot-1", controller_id="controller-1",
        product_profile_version="profile-1", capability_version="cap-1",
        deployment_instance_id="deployment-1", core_version="core-1",
    )
    request = RobotMotionExecutionCommand(_principal(), plan.plan_id, receipt)
    return service, request, plans, gates, permits, permit, scope


_DEFAULT_RESULT = object()


def _claiming_platform(result=_DEFAULT_RESULT):
    platform = MagicMock()

    def execute(command, parameters, **kwargs):
        verifier = kwargs["permit_verifier"]
        assert verifier.claim_dispatch(
            kwargs["execution_permit_handle"], kwargs["execution_scope"],
            dispatch_id=kwargs["execution_dispatch_id"],
            operation_type=kwargs["execution_operation_type"],
            payload=kwargs["execution_payload"],
        )
        return ({
            "ok": True, "state": "real_motion_command_completed",
            "message": "vendor message", "data": {"trigger_submitted": True},
        } if result is _DEFAULT_RESULT else result)

    platform.execute_confirmed_plan.side_effect = execute
    return platform


def test_confirmed_motion_executes_immutable_plan_and_consumes_permit() -> None:
    source = {"target_pose": {"x": 1.0}}
    platform = _claiming_platform()
    service, request, _plans, _gates, permits, permit, _scope = _prepared(
        parameters=source, platform=platform,
    )
    source["target_pose"]["x"] = 999.0

    response = service.execute(request)

    assert response.payload["ok"] is True
    assert response.payload["message"] == "Robot motion completed."
    assert permits.get(permit.handle).state is ExecutionPermitState.CONSUMED
    args, kwargs = platform.execute_confirmed_plan.call_args
    assert args == ("linear_move", {"target_pose": {"x": 1.0}})
    assert kwargs["execution_payload"] == {
        "command": "linear_move", "parameters": {"target_pose": {"x": 1.0}},
    }


def test_linear_path_uses_the_same_motion_application_boundary() -> None:
    platform = _claiming_platform()
    service, request, *_ = _prepared(
        command="linear_path",
        parameters={"target_poses": [{"x": 1.0}, {"x": 2.0}]},
        platform=platform,
    )

    response = service.execute(request)

    assert response.payload["ok"] is True
    assert platform.execute_confirmed_plan.call_args.args[0] == "linear_path"


def test_role_is_rejected_before_motion_plan_lookup() -> None:
    platform = _claiming_platform()
    service, request, plans, *_ = _prepared(platform=platform)
    plans.get = MagicMock(side_effect=AssertionError("forbidden role must not read plan"))
    viewer = AuthenticatedPrincipal("viewer", "viewer", "session-1", "test")

    response = service.execute(RobotMotionExecutionCommand(
        viewer, request.plan_id, request.confirmation_receipt,
    ))

    assert response.error.code == "motion_forbidden"
    plans.get.assert_not_called()


@pytest.mark.parametrize(
    "mutate, code",
    [
        (lambda request, plans, gates: gates.clear_pending_plan(
            "robot-server:session-1", request.plan_id
        ), "motion_session_not_confirmed"),
        (lambda request, plans, gates: object(), "motion_confirmation_invalid"),
    ],
)
def test_motion_gate_failures_never_reach_platform(mutate, code) -> None:
    platform = _claiming_platform()
    service, request, plans, gates, _permits, _permit, _scope = _prepared(platform=platform)
    if code == "motion_confirmation_invalid":
        request = RobotMotionExecutionCommand(_principal(), request.plan_id, "wrong")
    else:
        mutate(request, plans, gates)

    response = service.execute(request)

    assert response.error.code == code
    platform.execute_confirmed_plan.assert_not_called()


def test_non_motion_plan_is_rejected_without_platform_dispatch() -> None:
    platform = _claiming_platform()
    service, request, *_ = _prepared(command="delay", platform=platform)

    response = service.execute(request)

    assert response.error.code == "unsupported_motion_plan"
    platform.execute_confirmed_plan.assert_not_called()


def test_malformed_plan_port_result_is_sanitized() -> None:
    platform = _claiming_platform()
    service, request, *_ = _prepared(platform=platform)
    service._pending_plans = MagicMock()
    service._pending_plans.get.return_value = type(
        "MalformedPlan", (), {"command": ["linear_move"]},
    )()

    response = service.execute(request)

    assert response.error.code == "motion_state_unavailable"
    platform.execute_confirmed_plan.assert_not_called()


def test_platform_exception_is_sanitized_and_marks_outcome_unknown() -> None:
    platform = MagicMock()
    platform.execute_confirmed_plan.side_effect = RuntimeError(
        "secret-host C:/vendor/sdk.dll"
    )
    service, request, _plans, _gates, permits, permit, _scope = _prepared(platform=platform)

    response = service.execute(request)

    assert response.error.code == "motion_dispatch_outcome_unknown"
    assert "secret-host" not in repr(response)
    assert permits.get(permit.handle).state is ExecutionPermitState.OUTCOME_UNKNOWN


@pytest.mark.parametrize("raw", [None, {}, {"ok": True}, {"ok": True, "state": "bad path"}])
def test_malformed_platform_result_is_unknown_and_never_leaks(raw) -> None:
    platform = _claiming_platform(raw)
    service, request, _plans, _gates, permits, permit, _scope = _prepared(platform=platform)

    response = service.execute(request)

    assert response.error.code == "motion_dispatch_outcome_unknown"
    assert permits.get(permit.handle).state is ExecutionPermitState.OUTCOME_UNKNOWN


def test_non_definite_failure_is_sanitized_and_marks_outcome_unknown() -> None:
    platform = _claiming_platform({
        "ok": False, "state": "vendor_write_failed",
        "message": "secret-host", "errors": [{"message": "sdk.dll"}],
        "data": {"controller_host": "secret-host", "path": "sdk.dll"},
    })
    service, request, _plans, _gates, permits, permit, _scope = _prepared(platform=platform)

    response = service.execute(request)

    assert response.payload["message"] == (
        "Robot motion did not complete; reconcile controller state."
    )
    assert response.payload["errors"] == [{"code": "vendor_write_failed"}]
    assert "secret-host" not in repr(response)
    record = permits.get(permit.handle)
    assert record is not None and record.state is ExecutionPermitState.OUTCOME_UNKNOWN
    assert record.result == {
        "reason": "platform_returned_non_definite_failure",
        "diagnostic": {"result_state": "vendor_write_failed", "error_codes": []},
    }


def test_success_without_backend_dispatch_claim_is_never_committed() -> None:
    platform = MagicMock()
    platform.execute_confirmed_plan.return_value = {
        "ok": True, "state": "real_motion_command_completed",
    }
    service, request, _plans, _gates, permits, permit, _scope = _prepared(platform=platform)

    response = service.execute(request)

    assert response.error.code == "motion_commit_failed"
    assert permits.get(permit.handle).state is ExecutionPermitState.OUTCOME_UNKNOWN


def test_definite_success_is_replayed_without_second_platform_dispatch() -> None:
    platform = _claiming_platform()
    service, request, *_ = _prepared(platform=platform)

    first = service.execute(request)
    second = service.execute(request)

    assert first.payload == second.payload
    assert second.replayed is True
    platform.execute_confirmed_plan.assert_called_once()


def test_replay_rejects_changed_actor_with_same_session_and_receipt() -> None:
    platform = _claiming_platform()
    service, request, *_ = _prepared(platform=platform)
    assert service.execute(request).ok
    other_actor = AuthenticatedPrincipal("operator-2", "operator", "session-1", "test")

    replay = service.execute(RobotMotionExecutionCommand(
        other_actor, request.plan_id, request.confirmation_receipt,
    ))

    assert replay.error.code == "motion_permit_scope_mismatch"
    platform.execute_confirmed_plan.assert_called_once()


@pytest.mark.parametrize(
    "field,value",
    [
        ("_controller_id", "controller-2"),
        ("_product_profile_version", "profile-2"),
        ("_capability_version", "cap-2"),
        ("_deployment_instance_id", "deployment-2"),
        ("_core_version", "core-2"),
    ],
)
def test_replay_rejects_changed_execution_identity(field: str, value: str) -> None:
    platform = _claiming_platform()
    service, request, *_ = _prepared(platform=platform)
    assert service.execute(request).ok
    setattr(service, field, value)

    replay = service.execute(request)

    assert replay.error.code == "motion_permit_scope_mismatch"
    platform.execute_confirmed_plan.assert_called_once()


def test_replay_rejects_tampered_permit_handle() -> None:
    platform = _claiming_platform()
    service, request, plans, *_ = _prepared(platform=platform)
    assert service.execute(request).ok
    plans._plans[request.plan_id].permit_handle = "different-handle"

    replay = service.execute(request)

    assert replay.error.code == "motion_permit_missing"
    platform.execute_confirmed_plan.assert_called_once()


def test_success_public_dto_and_persisted_replay_drop_backend_secrets() -> None:
    platform = _claiming_platform({
        "ok": True,
        "state": "real_motion_command_completed",
        "message": "secret host completed",
        "errors": [{"message": "C:/vendor/sdk.dll"}],
        "secret": "controller-password",
        "data": {
            "action": "linear_move",
            "trigger_submitted": True,
            "write_count": 7,
            "actual_pose": [1, 2, 3, 4, 5, 6],
            "controller_host": "secret-host",
            "sdk_path": "C:/vendor/sdk.dll",
            "nested": {"password": "secret"},
        },
    })
    service, request, _plans, _gates, permits, permit, _scope = _prepared(platform=platform)

    first = service.execute(request)
    stored = permits.get(permit.handle).result
    replay = service.execute(request)

    expected = {
        "ok": True,
        "state": "real_motion_command_completed",
        "message": "Robot motion completed.",
        "data": {
            "action": "linear_move", "trigger_submitted": True,
            "write_count": 7,
            "actual_pose": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        },
    }
    assert first.payload == expected
    assert stored == expected
    assert replay.payload == expected
    rendered = repr((first, stored, replay))
    assert "secret-host" not in rendered
    assert "sdk.dll" not in rendered
    assert "controller-password" not in rendered


def test_changed_execution_identity_cannot_use_existing_permit() -> None:
    platform = _claiming_platform()
    service, request, _plans, _gates, permits, permit, _scope = _prepared(platform=platform)
    service._capability_version = "cap-2"

    response = service.execute(request)

    assert response.error.code == "motion_permit_scope_mismatch"
    assert permits.get(permit.handle).state is ExecutionPermitState.ISSUED
    platform.execute_confirmed_plan.assert_not_called()


def test_concurrent_execute_dispatches_platform_once() -> None:
    entered = threading.Event()
    release = threading.Event()
    platform = _claiming_platform()
    original = platform.execute_confirmed_plan.side_effect

    def blocking(*args, **kwargs):
        result = original(*args, **kwargs)
        entered.set()
        assert release.wait(timeout=5)
        return result

    platform.execute_confirmed_plan.side_effect = blocking
    service, request, *_ = _prepared(platform=platform)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.execute, request)
        assert entered.wait(timeout=2)
        second = pool.submit(service.execute, request)
        second_result = second.result(timeout=2)
        release.set()
        first_result = first.result(timeout=2)

    assert first_result.payload["ok"] is True
    assert second_result.error.code == "motion_permit_not_reservable"
    platform.execute_confirmed_plan.assert_called_once()


def test_motion_response_enforces_exactly_one_payload_or_error() -> None:
    with pytest.raises(ValueError):
        RobotMotionResponse()
    with pytest.raises(ValueError):
        RobotMotionResponse(
            payload={"ok": True}, error=RobotMotionError("x", "y"),
        )


@pytest.mark.parametrize("persisted_executing", [False, True])
def test_mark_executing_exception_finishes_reserved_state_safely(
    persisted_executing: bool,
) -> None:
    platform = _claiming_platform()
    service, request, _plans, _gates, permits, permit, _scope = _prepared(platform=platform)

    class RaisingPermitProxy:
        def __getattr__(self, name):
            return getattr(permits, name)

        def mark_executing(self, handle):
            if persisted_executing:
                assert permits.mark_executing(handle)
            raise OSError("permit persistence failed")

    service._permits = RaisingPermitProxy()

    response = service.execute(request)

    assert response.error.code == "motion_state_unavailable"
    expected = (
        ExecutionPermitState.OUTCOME_UNKNOWN
        if persisted_executing else ExecutionPermitState.FAILED
    )
    assert permits.get(permit.handle).state is expected
    platform.execute_confirmed_plan.assert_not_called()
