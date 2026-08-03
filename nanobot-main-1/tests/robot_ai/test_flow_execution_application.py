from __future__ import annotations

from unittest.mock import MagicMock

from robot_platform.application import (
    AuthenticatedPrincipal,
    RobotDryRunApplicationService,
    RobotFlowApplicationService,
    RobotFlowExecutionApplicationService,
    RobotFlowResponse,
)
from robot_platform.application.flow_execution import RobotFlowExecutionApplicationPort
from robot_platform.execution import (
    ExecutionPermitState, ExecutionPermitStore, ExecutionScope, FlowApprovalStore,
    PendingPlanStore, SessionGateStore,
)
from robot_platform.flow import (
    ActionNode, ConditionNode, FlowEntry, FlowExecutionSnapshot, FlowStep,
    NodeContract, run_flow,
    HumanApprovalNode, node_to_dict,
)
from robot_platform.adapters import FileFlowManagementAdapter, FileRobotFlowAdapter
from robot_platform.feature_policy import ProductFeaturePolicy
from robot_platform.platform import RobotPlatform


def _principal(role: str = "operator") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal("user-1", role, "session-1", "test")


def test_flow_execution_port_declares_the_complete_lifecycle() -> None:
    assert {"plan", "preview", "confirm", "execute"}.issubset(
        RobotFlowExecutionApplicationPort.__dict__
    )


def test_human_approval_receipt_is_principal_bound_and_one_use() -> None:
    approvals = FlowApprovalStore()
    principal = _principal()
    receipt = approvals.issue(
        plan_id="plan-1", node_id="approval-1", snapshot_hash="snapshot-1",
        principal=principal,
    )

    assert not approvals.claim(
        receipt, plan_id="plan-1", node_id="approval-1",
        snapshot_hash="snapshot-1",
        principal=AuthenticatedPrincipal("user-2", "operator", "session-2", "test"),
    )
    assert approvals.claim(
        receipt, plan_id="plan-1", node_id="approval-1",
        snapshot_hash="snapshot-1", principal=principal,
    )
    assert not approvals.claim(
        receipt, plan_id="plan-1", node_id="approval-1",
        snapshot_hash="snapshot-1", principal=principal,
    )


def _service(
    *, platform=None, pending=None, gates=None, permits=None, planning=None,
    flows=None, event_sink=None,
):
    return RobotFlowExecutionApplicationService(
        platform or MagicMock(),
        pending or MagicMock(),
        gates or MagicMock(),
        permits or MagicMock(),
        planning or MagicMock(),
        flows or MagicMock(),
        robot_id="robot-1",
        controller_id="controller-1",
        product_profile_version="profile-1",
        capability_version="capability-1",
        deployment_instance_id="deployment-1",
        core_version="core-1",
        event_sink=event_sink,
    )


def test_flow_execution_rejects_role_before_any_port() -> None:
    pending = MagicMock()
    planning = MagicMock()
    service = _service(pending=pending, planning=planning)

    response = service.plan(_principal("viewer"), {"flow_name": "pick"})

    assert response.error.code == "flow_forbidden"
    pending.get.assert_not_called()
    planning.stage_flow.assert_not_called()


def test_legacy_flow_preview_cannot_request_real_execution() -> None:
    flows = MagicMock()
    service = _service(flows=flows)

    response = service.preview(_principal(), {
        "name": "pick", "execute_real": True,
    })

    assert response.error.code == "staged_execution_required"
    flows.query.assert_not_called()


def test_flow_preview_sanitizes_nested_infrastructure_fields() -> None:
    flows = MagicMock()
    flows.query.return_value = RobotFlowResponse(payload={
        "flow": {"name": "pick"},
        "result": {
            "ok": True,
            "state": "flow_completed",
            "data": {
                "flow_name": "pick",
                "results": [{
                    "step_index": 1,
                    "result": {
                        "ok": True,
                        "state": "delay_completed",
                        "data": {"seconds": 1, "controller_host": "10.0.0.8"},
                        "sdk_path": "C:/secret/vendor.dll",
                    },
                }],
                "permit_handle": "opaque-secret",
            },
        },
    })
    service = _service(flows=flows)

    response = service.preview(_principal(), {"name": "pick"})

    assert response.ok
    rendered = repr(response.payload)
    assert "10.0.0.8" not in rendered
    assert "vendor.dll" not in rendered
    assert "opaque-secret" not in rendered
    assert response.payload["data"]["results"][0]["result"]["data"]["seconds"] == 1


def test_flow_port_exception_is_sanitized() -> None:
    flows = MagicMock()
    flows.query.side_effect = RuntimeError("C:/secret/flows.json")
    service = _service(flows=flows)

    response = service.preview(_principal(), {"name": "pick"})

    assert response.error.code == "flow_state_unavailable"
    assert "C:/secret" not in repr(response)


def test_flow_confirm_preserves_unresolved_execution_for_recovery() -> None:
    pending = PendingPlanStore()
    gates = SessionGateStore()
    permits = ExecutionPermitStore()
    snapshot = FlowExecutionSnapshot.create(
        FlowEntry(name="pick", steps=[FlowStep(1, "delay", 110, {"seconds": 0})]),
        product_profile_version="profile-1", capability_version="capability-1",
        core_version="core-1",
    )
    plan = pending.create(
        command="flow_run",
        parameters={"selection": {"name": "pick", "alias": None}, "snapshot": snapshot.to_dict()},
        dry_run_result={"ok": True},
    )
    gates.set_pending_plan("robot-server:session-1", plan.plan_id)
    old_scope = ExecutionScope.for_payload(
        principal=_principal(), robot_id="robot-1", controller_id="controller-1",
        operation_type="linear_move", payload={"old": True}, payload_schema_version="1",
        product_profile_version="profile-1", capability_version="capability-1",
        deployment_instance_id="deployment-1", core_version="core-1",
        plan_id="old-plan", plan_version="1",
    )
    old = permits.issue(old_scope, operation_id="robot-operation:old", idempotency_key="old-plan")
    assert permits.reserve(old.handle, old_scope)
    assert permits.mark_executing(old.handle)
    assert permits.mark_outcome_unknown(old.handle, reason="controller_timeout")
    service = _service(pending=pending, gates=gates, permits=permits)

    response = service.confirm(_principal(), plan.plan_id, {
        "confirm_work_area_clear": True, "confirm_estop_ready": True,
    })

    assert response.error.code == "execution_outcome_unknown"


def test_flow_replay_rejects_changed_actor_with_same_session() -> None:
    pending = PendingPlanStore()
    gates = SessionGateStore()
    permits = ExecutionPermitStore()
    snapshot = FlowExecutionSnapshot.create(
        FlowEntry(
            name="pick",
            flow_id="pick",
            version=1,
            steps=[FlowStep(1, "delay", 110, {"seconds": 0})],
        ),
        product_profile_version="profile-1",
        capability_version="capability-1",
        core_version="core-1",
    )
    plan = pending.create(
        command="flow_run",
        parameters={
            "selection": {"name": "pick", "alias": None},
            "snapshot": snapshot.to_dict(),
        },
        dry_run_result={"ok": True},
    )
    gates.set_pending_plan("robot-server:session-1", plan.plan_id)
    platform = MagicMock()
    event_sink = MagicMock()

    def run_flow(_snapshot, **kwargs):
        assert kwargs["execution_id"] == plan.plan_id
        assert kwargs["on_event"] == event_sink.append
        assert kwargs["before_step"](1)
        kwargs["on_step"](1, "running", None)
        grant = kwargs["flow_step_grants"][0]
        assert permits.claim_dispatch(
            grant.permit_handle,
            grant.scope,
            dispatch_id=grant.dispatch_id,
            operation_type="delay",
            payload={"command": "delay", "parameters": {"seconds": 0.0}},
        )
        step_result = {"ok": True, "state": "delay_completed", "data": {}}
        kwargs["on_step"](1, "succeeded", step_result)
        return {"ok": True, "state": "flow_completed", "data": {}}

    platform.run_flow_entry.side_effect = run_flow
    service = _service(
        platform=platform, pending=pending, gates=gates, permits=permits,
        event_sink=event_sink,
    )
    confirmed = service.confirm(_principal(), plan.plan_id, {
        "confirm_work_area_clear": True,
        "confirm_estop_ready": True,
    })
    receipt = confirmed.payload["confirm_code"]

    first = service.execute(_principal(), plan.plan_id, {"confirm_code": receipt})
    changed = service.execute(
        AuthenticatedPrincipal("user-2", "operator", "session-1", "test"),
        plan.plan_id,
        {"confirm_code": receipt},
    )

    assert first.ok
    assert changed.error.code == "flow_permit_scope_mismatch"
    assert platform.run_flow_entry.call_count == 1


def test_real_condition_flow_skips_unselected_permit_and_replays() -> None:
    pending = PendingPlanStore()
    gates = SessionGateStore()
    permits = ExecutionPermitStore()
    flow = FlowEntry(name="branch", flow_id="branch", version=1, steps=[
        FlowStep(1, "left", 110, {"seconds": 0}),
        FlowStep(2, "right", 110, {"seconds": 0}),
    ])
    contract = NodeContract(
        timeout_seconds=1, idempotency="intrinsic", side_effect="none",
    )
    graph = ConditionNode(
        node_id="choose", input_name="left", comparison="eq", expected=True,
        if_true=ActionNode(
            node_id="left", command="delay", parameters={"seconds": 0.0},
            step_index=1, step_id=1, contract=contract,
        ),
        if_false=ActionNode(
            node_id="right", command="delay", parameters={"seconds": 0.0},
            step_index=2, step_id=2, contract=contract,
        ),
    )
    snapshot = FlowExecutionSnapshot.create(
        flow, product_profile_version="profile-1",
        capability_version="capability-1", core_version="core-1",
        root_node=graph,
        execution_inputs={"left": True},
    )
    plan = pending.create(
        command="flow_run",
        parameters={"selection": {"name": "branch", "alias": None},
                    "snapshot": snapshot.to_dict()},
        dry_run_result={"ok": True},
    )
    gates.set_pending_plan("robot-server:session-1", plan.plan_id)
    platform = MagicMock()

    def execute_snapshot(current, **options):
        def runner(*, request, permit_verifier, **_kwargs):
            assert permit_verifier.claim_dispatch(
                request.execution_permit_handle, request.execution_scope,
                dispatch_id=request.execution_dispatch_id,
                operation_type=request.command,
                payload={"command": request.command, "parameters": request.parameters},
            )
            return {"ok": True, "state": "delay_completed", "data": {}}

        return run_flow(
            current, operator_runner=runner, node_inputs={"left": True}, **options,
        )

    platform.run_flow_entry.side_effect = execute_snapshot
    service = _service(
        platform=platform, pending=pending, gates=gates, permits=permits,
    )
    confirmed = service.confirm(_principal(), plan.plan_id, {
        "confirm_work_area_clear": True, "confirm_estop_ready": True,
    })
    receipt = confirmed.payload["confirm_code"]

    first = service.execute(_principal(), plan.plan_id, {"confirm_code": receipt})
    replay = service.execute(_principal(), plan.plan_id, {"confirm_code": receipt})
    stored = pending.get(plan.plan_id)
    assert stored is not None
    states = [permits.get(handle).state for handle in stored.child_permit_handles]

    assert first.ok and replay.payload == first.payload
    assert states == [ExecutionPermitState.CONSUMED, ExecutionPermitState.SKIPPED]
    assert platform.run_flow_entry.call_count == 1


def test_published_v2_graph_runs_through_real_application_and_platform_chain(
    tmp_path,
) -> None:
    steps = [
        FlowStep(1, "left", 110, {"seconds": 0}),
        FlowStep(2, "right", 110, {"seconds": 0}),
    ]
    contract = NodeContract(
        timeout_seconds=1, idempotency="intrinsic", side_effect="none",
    )
    graph = HumanApprovalNode(
        node_id="approval-1", prompt="Run selected branch?", approval_key="approval-1",
        child=ConditionNode(
            node_id="condition", input_name="left", comparison="eq", expected=True,
            if_true=ActionNode(
                node_id="left", command="delay", parameters={"seconds": 0.0},
                step_index=1, step_id=1, contract=contract,
            ),
            if_false=ActionNode(
                node_id="right", command="delay", parameters={"seconds": 0.0},
                step_index=2, step_id=2, contract=contract,
            ),
        ),
    )
    created = FileFlowManagementAdapter(tmp_path).execute(
        "create", "", {
            "name": "Published Branch", "steps": [step.to_dict() for step in steps],
            "node_graph": node_to_dict(graph),
        }, actor="test:engineer",
    )
    assert created.ok

    pending = PendingPlanStore()
    gates = SessionGateStore()
    permits = ExecutionPermitStore()
    dispatched: list[int] = []

    def operator_runner(**kwargs):
        request = kwargs["request"]
        if request.execute_real:
            verifier = kwargs["permit_verifier"]
            assert verifier.claim_dispatch(
                request.execution_permit_handle, request.execution_scope,
                dispatch_id=request.execution_dispatch_id,
                operation_type=request.command,
                payload={"command": request.command, "parameters": request.parameters},
            )
            dispatched.append(int(request.parameters["seconds"]))
        return {"ok": True, "state": "delay_completed", "data": {}}

    platform = RobotPlatform(
        operator_runner=operator_runner,
        feature_policy=ProductFeaturePolicy.from_enabled_tools([
            "robot_arm", "robot_flow",
        ]),
    )
    planning = RobotDryRunApplicationService(
        platform, pending, gates,
        product_profile_version="profile-1", capability_version="capability-1",
        core_version="core-1",
    )
    flows = RobotFlowApplicationService(FileRobotFlowAdapter(tmp_path), planning)
    service = RobotFlowExecutionApplicationService(
        platform, pending, gates, permits, planning, flows,
        robot_id="robot-1", controller_id="controller-1",
        product_profile_version="profile-1", capability_version="capability-1",
        deployment_instance_id="deployment-1", core_version="core-1",
        approval_store=FlowApprovalStore(),
    )

    planned = service.plan(_principal(), {
        "flow_name": "Published Branch", "inputs": {"left": False},
    })
    assert planned.ok and planned.staged
    confirmed = service.confirm(_principal(), planned.payload["plan_id"], {
        "confirm_work_area_clear": True, "confirm_estop_ready": True,
        "approved_node_ids": ["approval-1"],
    })
    assert confirmed.ok, confirmed.error
    executed = service.execute(
        _principal(), planned.payload["plan_id"],
        {"confirm_code": confirmed.payload["confirm_code"]},
    )
    replay = service.execute(
        _principal(), planned.payload["plan_id"],
        {"confirm_code": confirmed.payload["confirm_code"]},
    )

    assert executed.ok and replay.payload == executed.payload
    assert [item["step_index"] for item in executed.payload["data"]["results"]] == [2]
    assert dispatched == [0]
