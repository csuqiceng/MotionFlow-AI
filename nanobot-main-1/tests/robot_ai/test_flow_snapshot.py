from __future__ import annotations

import pytest

from robot_platform.application import AuthenticatedPrincipal
from robot_platform.execution import ExecutionPermitStore, ExecutionScope, FlowStepExecutionGrant
from robot_platform.flow import (
    ActionNode, FlowEntry, FlowExecutionSnapshot, FlowStep, NodeContract,
    SequenceNode,
)
from robot_platform.flow.executor import run_flow


def _snapshot() -> FlowExecutionSnapshot:
    return FlowExecutionSnapshot.create(
        FlowEntry(
            name="assembly", flow_id="flow-assembly", version=4,
            steps=[FlowStep(step_id=7, action="delay", func_id=110, params={"seconds": 0.25})],
        ),
        product_profile_version="profile-1",
        capability_version="capability-1",
        core_version="core-1",
        resolved_alias="daily",
    )


def test_snapshot_is_fully_expanded_and_detached_from_authoring_model() -> None:
    params = {"seconds": 0.25}
    flow = FlowEntry(
        name="assembly", flow_id="flow-assembly", version=4,
        steps=[FlowStep(step_id=7, action="delay", func_id=110, params=params)],
    )
    snapshot = FlowExecutionSnapshot.create(
        flow, product_profile_version="profile-1",
        capability_version="capability-1", core_version="core-1",
    )
    params["seconds"] = 99
    flow.steps.clear()

    assert snapshot.flow_id == "flow-assembly"
    assert snapshot.published_version == "4"
    assert snapshot.steps[0].command == "delay"
    assert snapshot.steps[0].parameters == {"seconds": 0.25}
    assert len(snapshot.content_hash) == 64


def test_flow_snapshot_rejects_dedicated_emergency_stop_step() -> None:
    flow = FlowEntry(
        name="unsafe", steps=[FlowStep(
            step_id=1, action="emergency_stop", func_id=104,
            params={"action": "emergency_stop"},
        )],
    )

    with pytest.raises(ValueError, match="cannot contain dedicated emergency stop"):
        FlowExecutionSnapshot.create(
            flow, product_profile_version="p", capability_version="c", core_version="k",
        )


def test_flow_snapshot_rejects_duplicate_node_ids_across_the_full_graph() -> None:
    steps = [
        FlowStep(1, "first", 110, {"seconds": 1}),
        FlowStep(2, "second", 110, {"seconds": 2}),
    ]
    contract = NodeContract(idempotency="intrinsic", side_effect="none")
    root = SequenceNode(node_id="root", children=(
        ActionNode(
            node_id="duplicate", command="delay", parameters={"seconds": 1.0},
            step_index=1, step_id=1, contract=contract,
        ),
        ActionNode(
            node_id="duplicate", command="delay", parameters={"seconds": 2.0},
            step_index=2, step_id=2, contract=contract,
        ),
    ))
    with pytest.raises(ValueError, match="globally unique"):
        FlowExecutionSnapshot.create(
            FlowEntry(name="duplicate", steps=steps),
            product_profile_version="p", capability_version="c", core_version="k",
            root_node=root,
        )


def test_snapshot_round_trip_validates_content_hash_and_rejects_tampering() -> None:
    snapshot = _snapshot()
    assert FlowExecutionSnapshot.from_dict(snapshot.to_dict()) == snapshot
    tampered = snapshot.to_dict()
    tampered["steps"][0]["parameters"]["seconds"] = 9
    try:
        FlowExecutionSnapshot.from_dict(tampered)
    except ValueError as exc:
        assert "content hash mismatch" in str(exc)
    else:
        raise AssertionError("tampered immutable snapshot must be rejected")

    for field, value in (("resolved_alias", "redirected"), ("schema_version", "1")):
        tampered_metadata = snapshot.to_dict()
        tampered_metadata[field] = value
        try:
            FlowExecutionSnapshot.from_dict(tampered_metadata)
        except ValueError as exc:
            assert "content hash mismatch" in str(exc)
        else:
            raise AssertionError(f"tampered {field} must be rejected")


def test_step_insertion_deletion_and_reordering_change_snapshot_hash() -> None:
    one = FlowStep(step_id=1, action="delay", func_id=110, params={"seconds": 1})
    two = FlowStep(step_id=2, action="delay", func_id=110, params={"seconds": 2})

    def build(steps):
        return FlowExecutionSnapshot.create(
            FlowEntry(name="flow", flow_id="flow", version=1, steps=steps),
            product_profile_version="p", capability_version="c", core_version="k",
        )

    original = build([one, two])
    reordered = build([two, one])
    deleted = build([one])
    inserted = build([one, two, FlowStep(step_id=3, action="delay", func_id=110,
                                         params={"seconds": 3})])

    assert len({original.content_hash, reordered.content_hash,
                deleted.content_hash, inserted.content_hash}) == 4


def test_each_snapshot_step_claims_its_child_permit_exactly_once() -> None:
    snapshot = _snapshot()
    step = snapshot.steps[0]
    principal = AuthenticatedPrincipal("operator", "operator", "session", "test")
    scope = ExecutionScope.for_payload(
        principal=principal, robot_id="robot", controller_id="controller",
        operation_type=step.command,
        payload={"command": step.command, "parameters": step.parameters},
        payload_schema_version="1", product_profile_version="profile-1",
        capability_version="capability-1", deployment_instance_id="deployment",
        core_version="core-1", plan_id="plan:step:1", plan_version="1:hash",
    )
    store = ExecutionPermitStore()
    permit = store.issue(scope, operation_id="flow-step", idempotency_key="flow-step")
    grant = FlowStepExecutionGrant(permit.handle, scope, "plan:step:1:dispatch")
    writes: list[str] = []

    def before_step(index: int) -> bool:
        assert index == 1
        return store.reserve(permit.handle, scope) and store.mark_executing(permit.handle)

    def runner(*, request, permit_verifier, **_kwargs):
        assert permit_verifier.claim_dispatch(
            request.execution_permit_handle, request.execution_scope,
            dispatch_id=request.execution_dispatch_id,
            operation_type=request.command,
            payload={"command": request.command, "parameters": request.parameters},
        )
        writes.append(request.command)
        return {"ok": True, "state": "delay_completed"}

    def on_step(_index: int, status: str, result):
        if status == "succeeded":
            assert store.complete(permit.handle, result)

    first = run_flow(
        snapshot, execute_real=True, confirm_work_area_clear=True,
        confirm_estop_ready=True, permit_verifier=store,
        flow_step_grants=(grant,), operator_runner=runner,
        before_step=before_step, on_step=on_step,
    )
    second = run_flow(
        snapshot, execute_real=True, confirm_work_area_clear=True,
        confirm_estop_ready=True, permit_verifier=store,
        flow_step_grants=(grant,), operator_runner=runner,
        before_step=before_step, on_step=on_step,
    )

    assert first["ok"] is True
    assert second["state"] == "flow_stopped"
    assert writes == ["delay"]
