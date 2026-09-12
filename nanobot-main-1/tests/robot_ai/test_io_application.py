from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest

from robot_platform.application import (
    AuthenticatedPrincipal,
    RobotIOApplicationService,
    RobotIOError,
    RobotIOExecutionCommand,
    RobotIOResponse,
)
from robot_platform.execution import (
    ExecutionPermitState,
    ExecutionPermitStore,
    ExecutionScope,
    PendingPlanStore,
    SessionGateStore,
)


def _principal(actor_id: str = "operator-1") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(actor_id, "operator", "session-1", "test")


def _prepared(
    *, command="io", parameters=None, platform=None, trusted_channels=(7, 8),
):
    if parameters is None:
        parameters = {
            "io_number": 7,
            "enabled": True,
            "allowed_io_channels": [7, 8],
        }
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
        scope, operation_id=f"io:{plan.plan_id}", idempotency_key=plan.plan_id,
    )
    receipt = plans.authorize(plan.plan_id, permit_handle=permit.handle)
    service = RobotIOApplicationService(
        platform or MagicMock(), plans, gates, permits,
        robot_id="robot-1", controller_id="controller-1",
        product_profile_version="profile-1", capability_version="cap-1",
        deployment_instance_id="deployment-1", core_version="core-1",
        allowed_io_output_channels=trusted_channels,
    )
    request = RobotIOExecutionCommand(_principal(), plan.plan_id, receipt)
    return service, request, plans, gates, permits, permit, scope


_DEFAULT_RESULT = object()


def _claiming_platform(result=_DEFAULT_RESULT):
    platform = MagicMock()

    def execute(command, parameters, **kwargs):
        assert kwargs["permit_verifier"].claim_dispatch(
            kwargs["execution_permit_handle"], kwargs["execution_scope"],
            dispatch_id=kwargs["execution_dispatch_id"],
            operation_type=kwargs["execution_operation_type"],
            payload=kwargs["execution_payload"],
        )
        return ({
            "ok": True,
            "state": "real_motion_command_completed",
            "message": "vendor message",
            "data": {
                "action": "io", "function_code": 120,
                "trigger_submitted": True,
            },
        } if result is _DEFAULT_RESULT else result)

    platform.execute_confirmed_plan.side_effect = execute
    return platform


def test_confirmed_io_executes_only_immutable_plan_and_consumes_permit() -> None:
    source = {
        "io_number": 7, "enabled": True, "allowed_io_channels": [7, 8],
    }
    platform = _claiming_platform()
    service, request, _plans, _gates, permits, permit, _scope = _prepared(
        parameters=source, platform=platform,
    )
    source["io_number"] = 999
    source["allowed_io_channels"].append(999)

    response = service.execute(request)

    assert response.payload == {
        "ok": True,
        "state": "real_motion_command_completed",
        "message": "Robot IO completed.",
        "data": {
            "action": "io", "function_code": 120,
            "trigger_submitted": True, "io_number": 7, "enabled": True,
        },
    }
    assert permits.get(permit.handle).state is ExecutionPermitState.CONSUMED
    args, kwargs = platform.execute_confirmed_plan.call_args
    assert args == ("io", {
        "io_number": 7, "enabled": True, "allowed_io_channels": [7, 8],
    })
    assert kwargs["execution_payload"] == {
        "command": "io",
        "parameters": {
            "io_number": 7, "enabled": True, "allowed_io_channels": [7, 8],
        },
    }


def test_role_is_rejected_before_io_plan_lookup() -> None:
    platform = _claiming_platform()
    service, request, plans, *_ = _prepared(platform=platform)
    service._engine.pending_plans = MagicMock(
        **{"get.side_effect": AssertionError("forbidden role must not read plan")},
    )
    viewer = AuthenticatedPrincipal("viewer", "viewer", "session-1", "test")

    response = service.execute(RobotIOExecutionCommand(
        viewer, request.plan_id, request.confirmation_receipt,
    ))

    assert response.error.code == "io_forbidden"
    service._engine.pending_plans.get.assert_not_called()


def test_non_io_plan_is_rejected_without_platform_dispatch() -> None:
    platform = _claiming_platform()
    service, request, *_ = _prepared(command="delay", platform=platform)

    response = service.execute(request)

    assert response.error.code == "unsupported_io_plan"
    platform.execute_confirmed_plan.assert_not_called()


@pytest.mark.parametrize(
    "parameters",
    [
        {"io_number": True, "enabled": True, "allowed_io_channels": [True]},
        {"io_number": 7, "enabled": 1, "allowed_io_channels": [7]},
        {"io_number": 7, "enabled": True, "allowed_io_channels": [8]},
        {"io_number": 7, "enabled": True, "allowed_io_channels": [7, 7]},
        {"io_number": 999, "enabled": True, "allowed_io_channels": [999]},
        {
            "io_number": 7, "enabled": True, "allowed_io_channels": [7],
            "controller_host": "secret-host",
        },
    ],
)
def test_invalid_frozen_io_plan_is_rejected_before_reservation(parameters) -> None:
    platform = _claiming_platform()
    service, request, _plans, _gates, permits, permit, _scope = _prepared(
        parameters=parameters, platform=platform,
    )

    response = service.execute(request)

    assert response.error.code == "io_plan_invalid"
    assert permits.get(permit.handle).state is ExecutionPermitState.ISSUED
    platform.execute_confirmed_plan.assert_not_called()


def test_io_confirmation_and_session_failures_never_dispatch() -> None:
    platform = _claiming_platform()
    service, request, _plans, gates, *_ = _prepared(platform=platform)
    gates.clear_pending_plan("robot-server:session-1", request.plan_id)
    missing_session = service.execute(request)

    service, request, *_ = _prepared(platform=platform)
    bad_receipt = service.execute(RobotIOExecutionCommand(
        _principal(), request.plan_id, "wrong-receipt",
    ))

    assert missing_session.error.code == "io_session_not_confirmed"
    assert bad_receipt.error.code == "io_confirmation_invalid"
    platform.execute_confirmed_plan.assert_not_called()


@pytest.mark.parametrize("raw", [None, {}, {"ok": True}, {"ok": True, "state": "bad path"}])
def test_malformed_io_result_is_unknown_and_sanitized(raw) -> None:
    platform = _claiming_platform(raw)
    service, request, _plans, _gates, permits, permit, _scope = _prepared(
        platform=platform,
    )

    response = service.execute(request)

    assert response.error.code == "io_dispatch_outcome_unknown"
    assert permits.get(permit.handle).state is ExecutionPermitState.OUTCOME_UNKNOWN


def test_io_platform_exception_is_sanitized_and_marks_unknown() -> None:
    platform = MagicMock()
    platform.execute_confirmed_plan.side_effect = RuntimeError(
        "secret-host C:/vendor/sdk.dll",
    )
    service, request, _plans, _gates, permits, permit, _scope = _prepared(
        platform=platform,
    )

    response = service.execute(request)

    assert response.error.code == "io_dispatch_outcome_unknown"
    assert "secret-host" not in repr(response)
    assert permits.get(permit.handle).state is ExecutionPermitState.OUTCOME_UNKNOWN


def test_io_failure_and_success_dtos_drop_secrets_and_backend_echo_mutation() -> None:
    platform = _claiming_platform({
        "ok": False,
        "state": "vendor_write_failed",
        "message": "secret-host",
        "errors": [{"message": "C:/vendor/sdk.dll"}],
        "data": {
            "action": "system", "io_number": 999, "enabled": False,
            "controller_host": "secret-host", "trigger_submitted": True,
        },
    })
    service, request, *_ = _prepared(platform=platform)

    response = service.execute(request)

    assert response.payload == {
        "ok": False,
        "state": "vendor_write_failed",
        "message": "Robot IO did not complete; reconcile controller state.",
        "data": {
            "action": "io", "trigger_submitted": True,
            "io_number": 7, "enabled": True,
        },
        "errors": [{"code": "vendor_write_failed"}],
    }
    assert "secret-host" not in repr(response)
    assert "sdk.dll" not in repr(response)
    assert "999" not in repr(response)


def test_io_success_requires_backend_dispatch_claim() -> None:
    platform = MagicMock()
    platform.execute_confirmed_plan.return_value = {
        "ok": True, "state": "real_motion_command_completed",
    }
    service, request, _plans, _gates, permits, permit, _scope = _prepared(
        platform=platform,
    )

    response = service.execute(request)

    assert response.error.code == "io_commit_failed"
    assert permits.get(permit.handle).state is ExecutionPermitState.OUTCOME_UNKNOWN


def test_exact_io_replay_does_not_dispatch_twice_but_changed_actor_is_rejected() -> None:
    platform = _claiming_platform()
    service, request, *_ = _prepared(platform=platform)

    first = service.execute(request)
    replay = service.execute(request)
    changed_actor = service.execute(RobotIOExecutionCommand(
        _principal("operator-2"), request.plan_id, request.confirmation_receipt,
    ))

    assert first.payload == replay.payload
    assert replay.replayed is True
    assert changed_actor.error.code == "io_permit_scope_mismatch"
    platform.execute_confirmed_plan.assert_called_once()


def test_changed_trusted_io_policy_cannot_replay_old_result() -> None:
    platform = _claiming_platform()
    service, request, *_ = _prepared(platform=platform)
    assert service.execute(request).ok
    changed_policy = RobotIOApplicationService(
        engine=service._engine,
        allowed_io_output_channels=(7, 9),
    )

    replay = changed_policy.execute(request)

    assert replay.error.code == "io_plan_invalid"
    platform.execute_confirmed_plan.assert_called_once()


def test_concurrent_io_execution_dispatches_platform_once() -> None:
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
    assert second_result.error.code == "io_permit_not_reservable"
    platform.execute_confirmed_plan.assert_called_once()


def test_io_response_enforces_exactly_one_payload_or_error() -> None:
    with pytest.raises(ValueError):
        RobotIOResponse()
    with pytest.raises(ValueError):
        RobotIOResponse(payload={"ok": True}, error=RobotIOError("x", "y"))


@pytest.mark.parametrize("persisted_reservation", [False, True])
def test_reservation_exception_finishes_only_persisted_reservation(
    persisted_reservation: bool,
) -> None:
    platform = _claiming_platform()
    service, request, _plans, _gates, permits, permit, _scope = _prepared(
        platform=platform,
    )

    class RaisingPermitProxy:
        def __getattr__(self, name):
            return getattr(permits, name)

        def reserve(self, handle, scope):
            if persisted_reservation:
                assert permits.reserve(handle, scope)
            raise OSError("permit persistence failed")

    service._engine.permits = RaisingPermitProxy()

    response = service.execute(request)

    assert response.error.code == "io_state_unavailable"
    expected = (
        ExecutionPermitState.FAILED
        if persisted_reservation else ExecutionPermitState.ISSUED
    )
    assert permits.get(permit.handle).state is expected
    platform.execute_confirmed_plan.assert_not_called()
