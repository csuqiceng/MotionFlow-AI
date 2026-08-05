from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from robot_platform.application import AuthenticatedPrincipal
from robot_platform.execution import (
    ExecutionPermitState,
    ExecutionPermitStore,
    ExecutionScope,
)


def _scope(**overrides: object) -> ExecutionScope:
    values: dict[str, object] = {
        "principal": AuthenticatedPrincipal(
            actor_id="operator-1",
            role="operator",
            session_id="session-1",
            auth_source="robot-server-session",
        ),
        "robot_id": "robot-1",
        "controller_id": "controller-1",
        "operation_type": "linear_move",
        "payload": {"x": 10, "speed": 5},
        "payload_schema_version": "1",
        "product_profile_version": "profile-v1",
        "capability_version": "cap-v1",
        "deployment_instance_id": "deployment-1",
        "core_version": "core-v1",
        "plan_id": "plan-1",
        "plan_version": "1",
    }
    values.update(overrides)
    return ExecutionScope.for_payload(**values)  # type: ignore[arg-type]


def test_principal_rejects_untrusted_empty_identity_fields() -> None:
    try:
        AuthenticatedPrincipal("", "operator", "session", "server")
    except ValueError as exc:
        assert "actor_id" in str(exc)
    else:
        raise AssertionError("empty principal must be rejected")


def test_permit_handle_is_opaque_and_does_not_embed_scope_data() -> None:
    scope = _scope()
    permit = ExecutionPermitStore().issue(
        scope, operation_id="operation-1", idempotency_key="request-1"
    )

    assert permit.handle
    assert "operator-1" not in permit.handle
    assert "robot-1" not in permit.handle
    assert "plan-1" not in permit.handle


def test_same_idempotency_key_returns_same_permit_for_same_scope() -> None:
    store = ExecutionPermitStore()
    scope = _scope()

    first = store.issue(scope, operation_id="operation-1", idempotency_key="request-1")
    second = store.issue(scope, operation_id="operation-2", idempotency_key="request-1")

    assert second.handle == first.handle
    assert second.operation_id == first.operation_id


def test_idempotency_key_cannot_be_rebound_to_another_scope() -> None:
    store = ExecutionPermitStore()
    store.issue(_scope(), operation_id="operation-1", idempotency_key="request-1")

    try:
        store.issue(
            _scope(robot_id="robot-2"),
            operation_id="operation-2",
            idempotency_key="request-1",
        )
    except ValueError as exc:
        assert "another execution scope" in str(exc)
    else:
        raise AssertionError("idempotency key scope rebinding must fail")


def test_scope_change_rejects_reservation() -> None:
    store = ExecutionPermitStore()
    permit = store.issue(_scope(), operation_id="operation-1", idempotency_key="request-1")

    assert store.reserve(permit.handle, _scope(robot_id="robot-2")) is False
    assert store.get(permit.handle).state is ExecutionPermitState.ISSUED  # type: ignore[union-attr]


def test_concurrent_reserve_has_exactly_one_winner() -> None:
    store = ExecutionPermitStore()
    scope = _scope()
    permit = store.issue(scope, operation_id="operation-1", idempotency_key="request-1")

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: store.reserve(permit.handle, scope), range(32)))

    assert results.count(True) == 1
    assert results.count(False) == 31


def test_reserved_permit_cannot_start_after_ttl() -> None:
    store = ExecutionPermitStore(ttl_sec=10)
    scope = _scope()
    permit = store.issue(
        scope, operation_id="operation-1", idempotency_key="request-1", now=100
    )
    assert store.reserve(permit.handle, scope, now=101) is True

    assert store.mark_executing(permit.handle, now=110) is False
    assert store.get(permit.handle, now=110).state is ExecutionPermitState.EXPIRED  # type: ignore[union-attr]


def test_expired_permit_cannot_be_reserved() -> None:
    store = ExecutionPermitStore(ttl_sec=1)
    scope = _scope()
    permit = store.issue(
        scope, operation_id="operation-1", idempotency_key="request-1", now=100
    )

    assert store.reserve(permit.handle, scope, now=102) is False
    assert store.get(permit.handle, now=102).state is ExecutionPermitState.EXPIRED  # type: ignore[union-attr]


def test_consumed_permit_cannot_be_executed_again() -> None:
    store = ExecutionPermitStore()
    scope = _scope()
    permit = store.issue(scope, operation_id="operation-1", idempotency_key="request-1")

    assert store.reserve(permit.handle, scope) is True
    assert store.mark_executing(permit.handle) is True
    assert store.claim_dispatch(
        permit.handle, scope, dispatch_id="dispatch",
        operation_type="linear_move", payload={"x": 10, "speed": 5},
    )
    assert store.complete(permit.handle, {"ok": True}) is True
    assert store.reserve(permit.handle, scope) is False
    assert store.mark_executing(permit.handle) is False
    assert store.definite_result_for_idempotency_key("request-1") == {"ok": True}


def test_definite_replay_requires_exact_handle_key_and_scope() -> None:
    store = ExecutionPermitStore()
    scope = _scope()
    permit = store.issue(scope, operation_id="operation-1", idempotency_key="request-1")
    assert store.reserve(permit.handle, scope)
    assert store.mark_executing(permit.handle)
    assert store.claim_dispatch(
        permit.handle, scope, dispatch_id="dispatch", operation_type="linear_move",
        payload={"x": 10, "speed": 5},
    )
    assert store.complete(permit.handle, {"ok": True})

    assert store.definite_result_for_exact_execution(
        permit.handle, "request-1", scope,
    ) == {"ok": True}
    assert store.definite_result_for_exact_execution(
        "wrong-handle", "request-1", scope,
    ) is None
    assert store.definite_result_for_exact_execution(
        permit.handle, "wrong-key", scope,
    ) is None
    assert store.definite_result_for_exact_execution(
        permit.handle, "request-1", _scope(controller_id="controller-2"),
    ) is None


def test_interrupted_execution_becomes_unknown_and_is_never_reissued() -> None:
    store = ExecutionPermitStore()
    scope = _scope()
    permit = store.issue(scope, operation_id="operation-1", idempotency_key="request-1")
    assert store.reserve(permit.handle, scope) is True
    assert store.mark_executing(permit.handle) is True

    assert store.mark_outcome_unknown(
        permit.handle, reason="process_interrupted_during_execution"
    )
    recovered = store.get(permit.handle)
    assert recovered is not None
    assert recovered.state is ExecutionPermitState.OUTCOME_UNKNOWN
    assert store.reserve(permit.handle, scope) is False
    assert store.definite_result_for_idempotency_key("request-1") is None

    try:
        store.issue(scope, operation_id="operation-2", idempotency_key="request-2")
    except ValueError as exc:
        assert "physical execution identity already has a permit" in str(exc)
    else:
        raise AssertionError("unknown execution scope must block a new permit")


def test_unknown_physical_execution_cannot_be_reissued_after_auth_or_runtime_changes() -> None:
    store = ExecutionPermitStore()
    original = _scope()
    permit = store.issue(original, operation_id="operation-1", idempotency_key="request-1")
    assert store.reserve(permit.handle, original)
    assert store.mark_executing(permit.handle)
    assert store.mark_outcome_unknown(permit.handle, reason="connection_lost")

    changed_scopes = (
        _scope(
            principal=AuthenticatedPrincipal(
                "operator-1", "operator", "new-session", "robot-server-session"
            )
        ),
        _scope(
            principal=AuthenticatedPrincipal(
                "engineer-2", "engineer", "session-2", "robot-server-session"
            )
        ),
        _scope(deployment_instance_id="deployment-2"),
        _scope(core_version="core-v2"),
        _scope(product_profile_version="profile-v2"),
        _scope(capability_version="cap-v2"),
    )
    for index, changed in enumerate(changed_scopes, start=2):
        try:
            store.issue(
                changed,
                operation_id=f"operation-{index}",
                idempotency_key=f"request-{index}",
            )
        except ValueError as exc:
            assert "physical execution identity already has a permit" in str(exc)
        else:
            raise AssertionError("auth/runtime changes must not unlock an unknown physical plan")


def test_new_plan_version_cannot_bypass_unresolved_controller_execution() -> None:
    store = ExecutionPermitStore()
    original = _scope()
    first = store.issue(original, operation_id="operation-1", idempotency_key="request-1")
    assert store.reserve(first.handle, original)
    assert store.mark_executing(first.handle)
    assert store.mark_outcome_unknown(first.handle, reason="connection_lost")

    replanned = _scope(plan_id="plan-2", plan_version="2")
    try:
        store.issue(replanned, operation_id="operation-2", idempotency_key="request-2")
    except ValueError as exc:
        assert "controller has an unresolved execution" in str(exc)
    else:
        raise AssertionError("replanning must not bypass an unresolved physical write")


@pytest.mark.parametrize(
    "action",
    ["release_emergency_stop", "alarm_reset", "release_cancel"],
)
def test_safety_recovery_permit_can_clear_latches_but_not_bypass_general_lock(
    action: str,
) -> None:
    store = ExecutionPermitStore()
    original = _scope()
    prior = store.issue(original, operation_id="operation-1", idempotency_key="request-1")
    assert store.reserve(prior.handle, original)
    assert store.mark_executing(prior.handle)
    assert store.mark_outcome_unknown(prior.handle, reason="connection_lost")

    recovery = _scope(
        operation_type="system",
        payload={"command": "system", "parameters": {"action": action}},
        plan_id="recovery-plan-1",
    )
    permit = store.issue_safety_recovery_action(
        recovery,
        action=action,
        operation_id="recovery-operation-1",
        idempotency_key="recovery-request-1",
    )

    assert permit.state is ExecutionPermitState.ISSUED
    with pytest.raises(ValueError, match="controller has an unresolved execution"):
        store.issue(
            _scope(plan_id="ordinary-plan-2"),
            operation_id="ordinary-operation-2",
            idempotency_key="ordinary-request-2",
        )
    with pytest.raises(ValueError, match="unsupported safety recovery action"):
        store.issue_safety_recovery_action(
            recovery,
            action="pause",
            operation_id="bad-recovery-operation",
            idempotency_key="bad-recovery-request",
        )
    mismatched_action = (
        "release_cancel" if action != "release_cancel" else "alarm_reset"
    )
    with pytest.raises(ValueError, match="does not match execution scope"):
        store.issue_safety_recovery_action(
            recovery,
            action=mismatched_action,
            operation_id="mismatched-recovery-operation",
            idempotency_key="mismatched-recovery-request",
        )


def test_safety_recovery_permit_never_bypasses_active_execution() -> None:
    store = ExecutionPermitStore()
    original = _scope()
    prior = store.issue(original, operation_id="operation-1", idempotency_key="request-1")
    assert store.reserve(prior.handle, original)
    assert store.mark_executing(prior.handle)
    recovery = _scope(
        operation_type="system",
        payload={"command": "system", "parameters": {"action": "release_cancel"}},
        plan_id="recovery-plan-1",
    )

    with pytest.raises(ValueError, match="controller has an unresolved execution"):
        store.issue_safety_recovery_action(
            recovery,
            action="release_cancel",
            operation_id="recovery-operation-1",
            idempotency_key="recovery-request-1",
        )


def test_preissued_ordinary_permit_cannot_start_after_another_outcome_is_unknown() -> None:
    store = ExecutionPermitStore()
    first_scope = _scope(plan_id="first-plan")
    second_scope = _scope(
        operation_type="io",
        payload={"io_number": 1, "enabled": True},
        plan_id="second-plan",
    )
    first = store.issue(first_scope, operation_id="first-operation", idempotency_key="first-request")
    second = store.issue(second_scope, operation_id="second-operation", idempotency_key="second-request")
    third_scope = _scope(plan_id="third-plan")
    third = store.issue(third_scope, operation_id="third-operation", idempotency_key="third-request")

    # The second plan was confirmed before the first controller outcome became
    # unknown. It must still be stopped before controller dispatch.
    assert store.reserve(first.handle, first_scope)
    assert store.mark_executing(first.handle)
    assert store.mark_outcome_unknown(first.handle, reason="controller_timeout")
    assert store.reserve(second.handle, second_scope) is False
    second_record = store.get(second.handle)
    assert second_record is not None
    assert second_record.state is ExecutionPermitState.FAILED
    assert second_record.result == {
        "reason": "outcome_unknown_before_dispatch",
        "write_dispatched": False,
    }
    assert store.reserve(third.handle, third_scope) is False
    third_record = store.get(third.handle)
    assert third_record is not None
    assert third_record.state is ExecutionPermitState.FAILED

    recovery_scope = _scope(
        operation_type="system",
        payload={"command": "system", "parameters": {"action": "release_cancel"}},
        plan_id="recovery-plan",
    )
    recovery = store.issue_safety_recovery_action(
        recovery_scope,
        action="release_cancel",
        operation_id="recovery-operation",
        idempotency_key="recovery-request",
    )
    assert recovery.state is ExecutionPermitState.ISSUED


def test_preissued_ordinary_permit_cannot_start_while_another_is_executing() -> None:
    store = ExecutionPermitStore()
    first_scope = _scope(plan_id="first-plan")
    second_scope = _scope(
        operation_type="io",
        payload={"io_number": 1, "enabled": True},
        plan_id="second-plan",
    )
    first = store.issue(first_scope, operation_id="first-operation", idempotency_key="first-request")
    second = store.issue(second_scope, operation_id="second-operation", idempotency_key="second-request")

    assert store.reserve(first.handle, first_scope)
    assert store.mark_executing(first.handle)
    assert store.reserve(second.handle, second_scope) is False
    second_record = store.get(second.handle)
    assert second_record is not None
    assert second_record.state is ExecutionPermitState.FAILED
    assert second_record.result == {
        "reason": "active_execution_before_dispatch",
        "write_dispatched": False,
    }
    assert store.claim_dispatch(
        second.handle,
        second_scope,
        dispatch_id="second-dispatch",
        operation_type="io",
        payload={"io_number": 1, "enabled": True},
    ) is False


def test_flow_child_can_start_only_with_its_persisted_parent_group() -> None:
    store = ExecutionPermitStore()
    parent_scope = _scope(
        operation_type="flow_run",
        payload={"snapshot": "flow-v1"},
        plan_id="flow-plan",
    )
    child_scope = _scope(
        operation_type="io",
        payload={"io_number": 1, "enabled": True},
        plan_id="flow-plan:step:1",
    )
    parent = store.issue_flow_parent(
        parent_scope,
        operation_id="flow-parent",
        idempotency_key="flow-parent-request",
    )
    child = store.issue_flow_child(
        child_scope,
        parent_handle=parent.handle,
        operation_id="flow-child",
        idempotency_key="flow-child-request",
    )

    assert store.reserve(parent.handle, parent_scope)
    assert store.mark_executing(parent.handle)
    assert store.reserve(child.handle, child_scope)
    assert store.mark_executing(child.handle)


def test_generic_permit_cannot_masquerade_as_flow_parent() -> None:
    store = ExecutionPermitStore()

    with pytest.raises(ValueError, match="issue_flow_parent"):
        store.issue(
            _scope(
                operation_type="system",
                payload={"command": "system", "parameters": {"action": "pause"}},
                plan_id="forged-flow-plan",
            ),
            operation_id="forged-parent",
            idempotency_key="forged-parent-request",
            requires_dispatch_claim=False,
        )


def test_consumed_flow_parent_cannot_issue_an_unrelated_child() -> None:
    store = ExecutionPermitStore()
    parent_scope = _scope(
        operation_type="flow_run",
        payload={"snapshot": "flow-v1"},
        plan_id="flow-plan",
    )
    parent = store.issue_flow_parent(
        parent_scope,
        operation_id="flow-parent",
        idempotency_key="flow-parent-request",
    )
    assert store.reserve(parent.handle, parent_scope)
    assert store.mark_executing(parent.handle)
    assert store.complete(parent.handle, {"ok": True})

    with pytest.raises(ValueError, match="matching issued flow parent"):
        store.issue_flow_child(
            _scope(
                operation_type="io",
                payload={"io_number": 1, "enabled": True},
                plan_id="unrelated-plan",
            ),
            parent_handle=parent.handle,
            operation_id="forged-child",
            idempotency_key="forged-child-request",
        )


def test_flow_child_cannot_start_after_its_parent_outcome_becomes_unknown() -> None:
    store = ExecutionPermitStore()
    parent_scope = _scope(
        operation_type="flow_run",
        payload={"snapshot": "flow-v1"},
        plan_id="flow-plan",
    )
    parent = store.issue_flow_parent(
        parent_scope,
        operation_id="flow-parent",
        idempotency_key="flow-parent-request",
    )
    child_scope = _scope(
        operation_type="io",
        payload={"io_number": 1, "enabled": True},
        plan_id="flow-plan:step:1",
    )
    child = store.issue_flow_child(
        child_scope,
        parent_handle=parent.handle,
        operation_id="flow-child",
        idempotency_key="flow-child-request",
    )
    assert store.reserve(parent.handle, parent_scope)
    assert store.mark_executing(parent.handle)
    assert store.mark_outcome_unknown(parent.handle, reason="controller_timeout")

    assert store.reserve(child.handle, child_scope) is False
    child_record = store.get(child.handle)
    assert child_record is not None
    assert child_record.state is ExecutionPermitState.FAILED
    assert child_record.result == {
        "reason": "outcome_unknown_before_dispatch",
        "write_dispatched": False,
    }


def test_explicit_unknown_outcome_is_not_a_retryable_failure() -> None:
    store = ExecutionPermitStore()
    scope = _scope()
    permit = store.issue(scope, operation_id="operation-1", idempotency_key="request-1")
    assert store.reserve(permit.handle, scope)
    assert store.mark_executing(permit.handle)
    assert store.mark_outcome_unknown(permit.handle, reason="sdk_result_not_persisted")

    record = store.get(permit.handle)
    assert record is not None
    assert record.state is ExecutionPermitState.OUTCOME_UNKNOWN
    assert record.result == {"reason": "sdk_result_not_persisted"}
    assert store.definite_result_for_idempotency_key("request-1") is None


def test_reserved_permit_can_fail_only_before_sdk_dispatch() -> None:
    store = ExecutionPermitStore()
    scope = _scope()
    permit = store.issue(scope, operation_id="operation-1", idempotency_key="request-1")
    assert store.reserve(permit.handle, scope)

    assert store.abort_before_dispatch(
        permit.handle, reason="write_ahead_audit_failed", audit_id="audit-1"
    )
    record = store.get(permit.handle)
    assert record is not None
    assert record.state is ExecutionPermitState.FAILED
    assert record.result == {
        "reason": "write_ahead_audit_failed",
        "audit_id": "audit-1",
        "write_dispatched": False,
    }
    assert store.mark_executing(permit.handle) is False


def test_executing_failure_requires_controller_evidence() -> None:
    store = ExecutionPermitStore()
    scope = _scope()
    permit = store.issue(scope, operation_id="operation-1", idempotency_key="request-1")
    assert store.reserve(permit.handle, scope)
    assert store.mark_executing(permit.handle)

    try:
        store.fail_with_controller_evidence(
            permit.handle,
            {"ok": False},
            controller_operation_id="",
            controller_evidence="controller rejected command",
            audit_id="audit-1",
        )
    except ValueError as exc:
        assert "requires operation, evidence, and audit IDs" in str(exc)
    else:
        raise AssertionError("unproven executing failure must be rejected")

    assert store.get(permit.handle).state is ExecutionPermitState.EXECUTING  # type: ignore[union-attr]


def test_unknown_outcome_can_only_be_reconciled_with_controller_evidence() -> None:
    store = ExecutionPermitStore()
    scope = _scope()
    permit = store.issue(scope, operation_id="operation-1", idempotency_key="request-1")
    assert store.reserve(permit.handle, scope)
    assert store.mark_executing(permit.handle)
    assert store.mark_outcome_unknown(permit.handle, reason="connection_lost")

    assert store.reconcile_unknown(
        permit.handle,
        succeeded=True,
        controller_operation_id="controller-op-1",
        controller_evidence="sequence 42 completed",
        audit_id="audit-1",
        result={"ok": True},
    )
    record = store.get(permit.handle)
    assert record is not None
    assert record.state is ExecutionPermitState.CONSUMED
    assert record.result is not None
    assert record.result["reconciled"] is True
    assert store.reconcile_unknown(
        permit.handle,
        succeeded=False,
        controller_operation_id="controller-op-1",
        controller_evidence="duplicate",
        audit_id="audit-2",
        result={"ok": False},
    ) is False


def test_nested_results_are_deep_copied_on_write_and_read() -> None:
    store = ExecutionPermitStore()
    scope = _scope()
    permit = store.issue(scope, operation_id="operation-1", idempotency_key="request-1")
    assert store.reserve(permit.handle, scope)
    assert store.mark_executing(permit.handle)
    assert store.claim_dispatch(
        permit.handle, scope, dispatch_id="dispatch",
        operation_type="linear_move", payload={"x": 10, "speed": 5},
    )
    result = {"ok": True, "data": {"sequence": 42}}
    assert store.complete(permit.handle, result)

    result["data"]["sequence"] = 99  # type: ignore[index]
    first = store.get(permit.handle)
    assert first is not None
    assert first.result == {"ok": True, "data": {"sequence": 42}}
    first.result["data"]["sequence"] = 100  # type: ignore[index]
    second = store.get(permit.handle)
    assert second is not None
    assert second.result == {"ok": True, "data": {"sequence": 42}}


def test_dispatch_claim_is_exact_and_single_use() -> None:
    store = ExecutionPermitStore()
    scope = _scope()
    permit = store.issue(scope, operation_id="operation-1", idempotency_key="request-1")
    assert store.reserve(permit.handle, scope)
    assert store.mark_executing(permit.handle)
    payload = {"x": 10, "speed": 5}

    assert store.claim_dispatch(
        permit.handle, scope, dispatch_id="dispatch-1",
        operation_type="linear_move", payload=payload,
    )
    assert not store.claim_dispatch(
        permit.handle, scope, dispatch_id="dispatch-1",
        operation_type="linear_move", payload=payload,
    )


def test_dispatch_required_permit_cannot_complete_without_backend_claim() -> None:
    store = ExecutionPermitStore()
    scope = _scope()
    permit = store.issue(scope, operation_id="operation", idempotency_key="request")
    assert store.reserve(permit.handle, scope)
    assert store.mark_executing(permit.handle)
    assert not store.complete(permit.handle, {"ok": True})
    assert store.claim_dispatch(
        permit.handle, scope, dispatch_id="dispatch",
        operation_type="linear_move", payload={"x": 10, "speed": 5},
    )
    assert store.complete(permit.handle, {"ok": True})
    assert not store.claim_dispatch(
        permit.handle, scope, dispatch_id="dispatch-2",
        operation_type="linear_move",
        payload={"command": "linear_move", "parameters": {"target": {"x": 2}}},
    )


def test_orchestration_parent_must_explicitly_opt_out_of_dispatch_claim() -> None:
    store = ExecutionPermitStore()
    scope = _scope(operation_type="flow_run", payload={"snapshot": "hash"})
    permit = store.issue_flow_parent(
        scope, operation_id="flow-parent", idempotency_key="flow-parent",
    )
    assert store.reserve(permit.handle, scope)
    assert store.mark_executing(permit.handle)
    assert store.complete(permit.handle, {"ok": True, "state": "flow_completed"})


def test_restart_recovers_executing_as_unknown_and_blocks_new_controller_work(tmp_path) -> None:
    path = tmp_path / "execution-permits.json"
    first = ExecutionPermitStore(storage_path=path)
    scope = _scope()
    permit = first.issue(scope, operation_id="operation-1", idempotency_key="request-1")
    assert first.reserve(permit.handle, scope)
    assert first.mark_executing(permit.handle)
    first.close()

    recovered = ExecutionPermitStore(storage_path=path)
    record = recovered.get(permit.handle)
    assert record is not None
    assert record.state is ExecutionPermitState.OUTCOME_UNKNOWN
    assert record.result == {"reason": "process_restarted_during_execution"}

    another_scope = _scope(plan_id="plan-2")
    try:
        recovered.issue(
            another_scope, operation_id="operation-2", idempotency_key="request-2"
        )
    except ValueError as exc:
        assert "controller has an unresolved execution" in str(exc)
    else:
        raise AssertionError("unresolved controller work must block a new permit")
    recovered.close()


def test_persisted_permit_includes_readable_timestamps(tmp_path) -> None:
    path = tmp_path / "execution-permits.json"
    store = ExecutionPermitStore(storage_path=path)
    try:
        store.issue(
            _scope(), operation_id="operation-1", idempotency_key="request-1", now=0,
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
    finally:
        store.close()

    record = payload["permits"][0]
    assert record["issued_at_iso"] == "1970-01-01T00:00:00+00:00"
    assert record["updated_at_iso"] == "1970-01-01T00:00:00+00:00"
    assert record["expires_at_iso"] == "1970-01-01T00:05:00+00:00"


def test_runtime_store_path_has_exclusive_lifecycle_owner(tmp_path) -> None:
    path = tmp_path / "execution-permits.json"
    owner = ExecutionPermitStore(storage_path=path)
    try:
        try:
            ExecutionPermitStore(storage_path=path)
        except RuntimeError as exc:
            assert "already owned by another server" in str(exc)
        else:
            raise AssertionError("a second server must not own the same runtime directory")
    finally:
        owner.close()


def test_dispatch_claim_snapshot_cannot_mutate_store_state() -> None:
    store = ExecutionPermitStore()
    scope = _scope()
    permit = store.issue(scope, operation_id="operation", idempotency_key="request")
    assert store.reserve(permit.handle, scope)
    assert store.mark_executing(permit.handle)
    assert store.claim_dispatch(
        permit.handle, scope, dispatch_id="dispatch-1",
        operation_type="linear_move", payload={"x": 10, "speed": 5},
    )
    snapshot = store.get(permit.handle)
    assert snapshot is not None
    snapshot.claimed_dispatch_ids.clear()

    fresh = store.get(permit.handle)
    assert fresh is not None
    assert fresh.claimed_dispatch_ids == ["dispatch-1"]


def test_second_process_cannot_open_same_runtime_permit_store(tmp_path) -> None:
    path = tmp_path / "execution-permits.json"
    owner_code = (
        "from robot_platform.execution import ExecutionPermitStore; "
        f"s=ExecutionPermitStore(storage_path={str(path)!r}); "
        "print('ready', flush=True); input(); s.close()"
    )
    owner = subprocess.Popen(
        [sys.executable, "-c", owner_code],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert owner.stdout is not None
        assert owner.stdout.readline().strip() == "ready"
        contender = subprocess.run(
            [
                sys.executable,
                "-c",
                "from robot_platform.execution import ExecutionPermitStore; "
                f"ExecutionPermitStore(storage_path={str(path)!r})",
            ],
            capture_output=True,
            text=True,
        )
        assert contender.returncode != 0
        assert "already owned by another server" in contender.stderr
    finally:
        if owner.stdin is not None:
            owner.stdin.write("\n")
            owner.stdin.flush()
        owner.wait(timeout=10)


def test_constructor_load_failure_releases_runtime_lock(monkeypatch, tmp_path) -> None:
    path = tmp_path / "execution-permits.json"
    original_load = ExecutionPermitStore._load_locked

    def fail_load(_self) -> None:
        raise ValueError("corrupt persisted permit data")

    monkeypatch.setattr(ExecutionPermitStore, "_load_locked", fail_load)
    with pytest.raises(ValueError, match="corrupt persisted"):
        ExecutionPermitStore(storage_path=path)

    monkeypatch.setattr(ExecutionPermitStore, "_load_locked", original_load)
    reopened = ExecutionPermitStore(storage_path=path)
    reopened.close()
