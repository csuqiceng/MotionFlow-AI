from __future__ import annotations

import time

from robot_ai.execution.pending_plan import (
    PendingPlan,
    PendingPlanStore,
    _param_hash,
)


def test_param_hash_is_stable_and_canonical() -> None:
    params_a = {"x": 1, "y": [1, 2, 3]}
    params_b = {"y": [1, 2, 3], "x": 1}  # same content, different key order
    assert _param_hash(params_a) == _param_hash(params_b)


def test_param_hash_differs_for_different_params() -> None:
    assert _param_hash({"x": 1}) != _param_hash({"x": 2})
    assert _param_hash({"x": 1}) != _param_hash({"x": 1, "y": 2})


def test_create_returns_plan_with_nonempty_id_and_hash() -> None:
    store = PendingPlanStore()
    plan = store.create(
        command="linear_move",
        parameters={"x": 100, "y": 200},
        dry_run_result={"ok": True},
    )
    assert isinstance(plan, PendingPlan)
    assert plan.plan_id
    assert plan.param_hash
    assert plan.plan_id != plan.param_hash
    assert plan.command == "linear_move"
    assert plan.parameters == {"x": 100, "y": 200}
    assert plan.dry_run_result == {"ok": True}
    assert plan.confirmed is False
    assert plan.expires_at > plan.created_at


def test_get_returns_created_plan() -> None:
    store = PendingPlanStore()
    plan = store.create(
        command="linear_move", parameters={"x": 1}, dry_run_result={}
    )
    assert store.get(plan.plan_id) == plan
    assert store.get(plan.plan_id) is not plan
    assert store.get("nonexistent") is None


def test_verify_confirmed_same_params_is_true() -> None:
    store = PendingPlanStore()
    params = {"x": 1, "y": 2}
    plan = store.create(command="linear_move", parameters=params, dry_run_result={})
    assert store.confirm(plan.plan_id) is True
    assert store.verify(plan.plan_id, params) is True


def test_verify_confirmed_different_params_is_false() -> None:
    store = PendingPlanStore()
    plan = store.create(command="linear_move", parameters={"x": 1}, dry_run_result={})
    assert store.confirm(plan.plan_id) is True
    assert store.verify(plan.plan_id, {"x": 999}) is False


def test_verify_not_confirmed_is_false() -> None:
    store = PendingPlanStore()
    params = {"x": 1}
    plan = store.create(command="linear_move", parameters=params, dry_run_result={})
    # Not confirmed yet
    assert store.verify(plan.plan_id, params) is False


def test_verify_expired_is_false() -> None:
    store = PendingPlanStore(ttl_sec=0.01)
    params = {"x": 1}
    plan = store.create(command="linear_move", parameters=params, dry_run_result={})
    assert store.confirm(plan.plan_id) is True
    time.sleep(0.05)
    assert store.verify(plan.plan_id, params) is False


def test_verify_unknown_plan_is_false() -> None:
    store = PendingPlanStore()
    assert store.verify("nonexistent", {"x": 1}) is False


def test_confirm_confirms_active_plan() -> None:
    store = PendingPlanStore()
    plan = store.create(command="linear_move", parameters={"x": 1}, dry_run_result={})
    assert plan.confirmed is False
    assert store.confirm(plan.plan_id) is True
    assert store.get(plan.plan_id).confirmed is True  # type: ignore[union-attr]


def test_confirm_double_confirm_is_ok() -> None:
    store = PendingPlanStore()
    plan = store.create(command="linear_move", parameters={"x": 1}, dry_run_result={})
    assert store.confirm(plan.plan_id) is True
    # Second confirm should also succeed (idempotent)
    assert store.confirm(plan.plan_id) is True
    assert store.get(plan.plan_id).confirmed is True  # type: ignore[union-attr]


def test_confirm_unknown_plan_is_false() -> None:
    store = PendingPlanStore()
    assert store.confirm("nonexistent") is False


def test_confirm_expired_plan_is_false() -> None:
    store = PendingPlanStore(ttl_sec=0.01)
    plan = store.create(command="linear_move", parameters={"x": 1}, dry_run_result={})
    time.sleep(0.05)
    assert store.confirm(plan.plan_id) is False


def test_is_expired_uses_provided_now() -> None:
    store = PendingPlanStore(ttl_sec=100.0)
    plan = store.create(command="linear_move", parameters={"x": 1}, dry_run_result={})
    # Far future
    assert plan.is_expired(now=plan.expires_at + 1) is True
    # Before expiry
    assert plan.is_expired(now=plan.expires_at - 1) is False


def test_matches_uses_param_hash() -> None:
    store = PendingPlanStore()
    plan = store.create(command="linear_move", parameters={"x": 1}, dry_run_result={})
    assert plan.matches({"x": 1}) is True
    assert plan.matches({"x": 2}) is False


def test_expire_old_evicts_expired_plans() -> None:
    store = PendingPlanStore(ttl_sec=0.01)
    plan = store.create(command="linear_move", parameters={"x": 1}, dry_run_result={})
    time.sleep(0.05)
    store.expire_old()
    assert store.get(plan.plan_id) is None


def test_parameters_are_copied_not_referenced() -> None:
    store = PendingPlanStore()
    params = {"x": 1}
    plan = store.create(command="linear_move", parameters=params, dry_run_result={})
    params["x"] = 999  # mutate caller dict
    assert plan.parameters == {"x": 1}  # plan unaffected
    assert plan.matches({"x": 1}) is True


def test_authorization_receipt_requires_confirmation_and_is_server_bound() -> None:
    store = PendingPlanStore()
    plan = store.create(command="linear_move", parameters={"x": 1}, dry_run_result={})

    assert store.authorize(plan.plan_id, permit_handle="permit-1") is None
    assert store.confirm(plan.plan_id)
    receipt = store.authorize(plan.plan_id, permit_handle="permit-1")
    assert receipt is not None
    assert store.verify_confirmation(plan.plan_id, receipt)
    assert not store.verify_confirmation(plan.plan_id, "forged-receipt")
    assert store.get(plan.plan_id).permit_handle == "permit-1"  # type: ignore[union-attr]


def test_new_authorization_receipt_invalidates_the_previous_receipt() -> None:
    store = PendingPlanStore()
    plan = store.create(command="linear_move", parameters={"x": 1}, dry_run_result={})
    assert store.confirm(plan.plan_id)
    first = store.authorize(plan.plan_id, permit_handle="permit-1")
    second = store.authorize(plan.plan_id, permit_handle="permit-1")

    assert first is not None and second is not None and first != second
    assert not store.verify_confirmation(plan.plan_id, first)
    assert store.verify_confirmation(plan.plan_id, second)


def test_get_snapshot_cannot_mutate_stored_plan() -> None:
    store = PendingPlanStore()
    plan = store.create(command="flow_run", parameters={"snapshot": {"steps": [1]}}, dry_run_result={})
    fetched = store.get(plan.plan_id)
    assert fetched is not None
    fetched.parameters["snapshot"]["steps"].append(2)

    fresh = store.get(plan.plan_id)
    assert fresh is not None
    assert fresh.parameters == {"snapshot": {"steps": [1]}}
