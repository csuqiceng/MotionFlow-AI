from __future__ import annotations

from ai_runtime.tool_operation_store import InMemoryToolOperationStore
from robot_platform.application import AuthenticatedPrincipal
from robot_platform.execution import ExecutionPermitState, ExecutionPermitStore, ExecutionScope
from robot_server.execution_recovery import ExecutionRecoveryService
from robot_server.robot_api import _execution_outcome_unknown_error
from robot_server.robot_api import _io_result, _motion_result
from robot_platform.application import (
    RobotIOError,
    RobotIOResponse,
    RobotMotionError,
    RobotMotionResponse,
)


def _principal(role: str = "operator") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal("operator-1", role, "session-1", "test")


def _unknown_permit(store: ExecutionPermitStore):
    scope = ExecutionScope.for_payload(
        principal=_principal(), robot_id="robot-1", controller_id="controller-1",
        operation_type="linear_move", payload={"x": 100}, payload_schema_version="1",
        product_profile_version="profile-1", capability_version="capability-1",
        deployment_instance_id="deployment-1", core_version="core-1",
        plan_id="plan-1", plan_version="1",
    )
    permit = store.issue(scope, operation_id="robot-operation:plan-1", idempotency_key="plan-1")
    assert store.reserve(permit.handle, scope)
    assert store.mark_executing(permit.handle)
    assert store.mark_outcome_unknown(permit.handle, reason="test_unknown")
    return permit


class _Platform:
    def __init__(self, state: dict) -> None:
        self.state = state

    def execution_context(self) -> dict[str, str]:
        return {"controller_id": "controller-1"}

    def get_status(self) -> dict:
        return {"ok": True, "data": {"robot_state": self.state}}


def test_reconcile_unknown_requires_fresh_safe_controller_evidence(tmp_path) -> None:
    store = ExecutionPermitStore()
    permit = _unknown_permit(store)
    service = ExecutionRecoveryService(
        platform=_Platform({
            "connected_real_device": True, "mode": "idle", "alarms": [], "cancel_latch": False,
        }),
        permits=store, audit_path=tmp_path / "audit.jsonl",
    )

    status, listed = service.list_unresolved(_principal())
    assert status == 200
    item = listed["data"]["items"][0]
    assert item["operation_id"] == permit.operation_id
    assert item["recovery_ready"] is True
    assert item["reason"] == "controller_result_not_definite"
    assert set(item) == {"operation_id", "issued_at", "updated_at", "reason", "recovery_ready"}

    status, result = service.reconcile({
        "operation_id": permit.operation_id,
        "confirm_work_area_clear": True,
        "confirm_estop_ready": True,
        "notes": "现场已核验，控制器空闲且无报警。",
    }, principal=_principal())

    assert status == 200
    assert result["ok"] is True
    record = store.get(permit.handle)
    assert record is not None and record.state is ExecutionPermitState.RECOVERED_SAFE
    assert record.result["prior_outcome"] == "unknown"
    assert "现场已核验" not in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_reconcile_unknown_releases_only_the_matching_tool_operation(tmp_path) -> None:
    store = ExecutionPermitStore()
    permit = _unknown_permit(store)
    tool_operations = InMemoryToolOperationStore(durable=True)
    assert tool_operations.begin(
        "robot_arm", "request-1", "request-fingerprint",
        operation_fingerprint="matching-effect", target_device_id="controller-1",
        effect_operation_id=permit.operation_id,
    )
    assert tool_operations.mark_unknown(
        "robot_arm", "request-1", "request-fingerprint", reason="after_dispatch",
    )
    assert tool_operations.begin(
        "robot_arm", "request-2", "other-request-fingerprint",
        operation_fingerprint="other-effect", target_device_id="controller-1",
        effect_operation_id="robot-operation:other-plan",
    )
    assert tool_operations.mark_unknown(
        "robot_arm", "request-2", "other-request-fingerprint", reason="after_dispatch",
    )
    service = ExecutionRecoveryService(
        platform=_Platform({
            "connected_real_device": True, "mode": "idle", "alarms": [], "cancel_latch": False,
        }),
        permits=store, tool_operation_store=tool_operations, audit_path=tmp_path / "audit.jsonl",
    )

    status, result = service.reconcile({
        "operation_id": permit.operation_id,
        "confirm_work_area_clear": True,
        "confirm_estop_ready": True,
        "notes": "operator-confirmed-recovery-safety",
    }, principal=_principal())

    assert status == 200
    assert result["ok"] is True
    assert tool_operations.get("robot_arm", "request-1").state == "completed"  # type: ignore[union-attr]
    assert tool_operations.get("robot_arm", "request-2").state == "unknown"  # type: ignore[union-attr]


def test_reconcile_unknown_never_clears_an_unsafe_controller(tmp_path) -> None:
    store = ExecutionPermitStore()
    permit = _unknown_permit(store)
    service = ExecutionRecoveryService(
        platform=_Platform({
            "connected_real_device": True, "mode": "alarm", "alarms": ["controller_alarm"], "cancel_latch": False,
        }),
        permits=store, audit_path=tmp_path / "audit.jsonl",
    )

    status, result = service.reconcile({
        "operation_id": permit.operation_id,
        "confirm_work_area_clear": True,
        "confirm_estop_ready": True,
        "notes": "attempt",
    }, principal=_principal())

    assert status == 422
    assert result["error"]["code"] == "execution_recovery_controller_not_safe"
    assert store.get(permit.handle).state is ExecutionPermitState.OUTCOME_UNKNOWN  # type: ignore[union-attr]


def test_listing_unresolved_auto_rechecks_controller_and_reports_not_ready(tmp_path) -> None:
    store = ExecutionPermitStore()
    permit = _unknown_permit(store)
    service = ExecutionRecoveryService(
        platform=_Platform({
            "connected_real_device": False, "mode": "disconnected",
            "alarms": ["controller_read_failed"], "cancel_latch": False,
        }),
        permits=store, audit_path=tmp_path / "audit.jsonl",
    )

    status, listed = service.list_unresolved(_principal())

    assert status == 200
    item = listed["data"]["items"][0]
    assert item["operation_id"] == permit.operation_id
    assert item["recovery_ready"] is False
    assert store.get(permit.handle).state is ExecutionPermitState.OUTCOME_UNKNOWN  # type: ignore[union-attr]


def test_listing_never_exposes_legacy_permits_for_another_controller_or_free_text(tmp_path) -> None:
    store = ExecutionPermitStore()
    permit = _unknown_permit(store)
    permit_record = store.get(permit.handle)
    assert permit_record is not None
    store._permits[permit.handle].result = {  # type: ignore[attr-defined]
        "reason": "controller at 10.0.0.1 failed", "diagnostic": {"secret": "password"},
    }
    service = ExecutionRecoveryService(
        platform=_Platform({"connected_real_device": True, "mode": "idle", "alarms": [], "cancel_latch": False}),
        permits=store, audit_path=tmp_path / "audit.jsonl",
    )

    status, listed = service.list_unresolved(_principal())

    assert status == 200
    assert listed["data"]["items"][0]["reason"] == "controller_result_not_definite"
    assert "10.0.0.1" not in repr(listed)
    assert "password" not in repr(listed)


def test_unresolved_execution_api_error_has_a_stable_code() -> None:
    status, result = _execution_outcome_unknown_error()

    assert status == 409
    assert result["error"]["code"] == "execution_outcome_unknown"


def test_motion_unknown_variants_use_the_same_public_recovery_code() -> None:
    for code in ("motion_outcome_unknown", "motion_dispatch_outcome_unknown", "motion_commit_failed"):
        status, result = _motion_result(RobotMotionResponse(error=RobotMotionError(code, "internal")))
        assert status == 409
        assert result["error"]["code"] == "execution_outcome_unknown"


def test_motion_non_definite_payload_uses_the_same_public_recovery_code() -> None:
    status, result = _motion_result(RobotMotionResponse(payload={
        "ok": False,
        "state": "controller_completion_timeout",
    }))

    assert status == 409
    assert result["error"]["code"] == "execution_outcome_unknown"


def test_io_unknown_variants_use_the_same_public_recovery_code() -> None:
    for code in ("io_outcome_unknown", "io_dispatch_outcome_unknown", "io_commit_failed"):
        status, result = _io_result(RobotIOResponse(error=RobotIOError(code, "internal")))
        assert status == 409
        assert result["error"]["code"] == "execution_outcome_unknown"


def test_io_non_definite_payload_uses_the_same_public_recovery_code() -> None:
    status, result = _io_result(RobotIOResponse(payload={
        "ok": False,
        "state": "vendor_write_failed",
        "errors": [{"code": "vendor_write_failed"}],
    }))

    assert status == 409
    assert result["error"]["code"] == "execution_outcome_unknown"
