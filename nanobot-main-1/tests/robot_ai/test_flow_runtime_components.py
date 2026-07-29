from __future__ import annotations

from pathlib import Path
import asyncio

import pytest

from robot_platform.flow import (
    FlowEntry,
    FlowExecutionSnapshot,
    FlowNodeType,
    ActionNode,
    CompensationNode,
    ConditionNode,
    FlowNodeExecutionContext,
    HumanApprovalNode,
    NodeContract,
    ParallelNode,
    RetryNode,
    SequenceNode,
    TimeoutNode,
    execute_node,
    node_from_dict,
    node_to_dict,
    FlowStep,
    plan_controlled_compensation,
    run_flow,
)
from robot_platform.flow.execution_history import ExecutionHistory
from robot_platform.flow.execution_registry import LibraryExecutionRegistry


def _snapshot(step: FlowStep) -> FlowExecutionSnapshot:
    return FlowExecutionSnapshot.create(
        FlowEntry(name="typed", flow_id="flow-1", steps=[step]),
        product_profile_version="1",
        capability_version="1",
        core_version="1",
    )


def test_snapshot_exposes_typed_flow_nodes_and_emits_correlated_events() -> None:
    snapshot = _snapshot(FlowStep(1, "delay", 110, {"seconds": 0}))
    events = []

    result = run_flow(
        snapshot,
        operator_runner=lambda **_kwargs: {"ok": True, "state": "done"},
        execution_id="execution-1",
        on_event=events.append,
    )

    assert snapshot.steps[0].node_type is FlowNodeType.DELAY
    assert isinstance(snapshot.root_node, SequenceNode)
    assert result["ok"] is True
    assert [event.kind for event in events] == [
        "flow_started", "node_started", "node_succeeded", "flow_completed",
    ]
    assert all(event.execution_id == "execution-1" for event in events)
    assert all(event.snapshot_hash == snapshot.content_hash for event in events)


def test_v2_condition_graph_controls_production_dispatch() -> None:
    flow = FlowEntry(name="branch", flow_id="branch", steps=[
        FlowStep(1, "left", 110, {"seconds": 0}),
        FlowStep(2, "right", 110, {"seconds": 0}),
    ])
    contract = NodeContract(
        timeout_seconds=1, idempotency="intrinsic", side_effect="none",
    )
    root = ConditionNode(
        node_id="branch", input_name="choose_left", comparison="eq", expected=True,
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
        flow, product_profile_version="1", capability_version="1", core_version="1",
        root_node=root,
        execution_inputs={"choose_left": False},
    )
    dispatched: list[float] = []
    result = run_flow(
        snapshot,
        operator_runner=lambda **kwargs: (
            dispatched.append(kwargs["request"].parameters["seconds"])
            or {"ok": True, "state": "done"}
        ),
    )
    assert result["ok"] is True
    assert [item["step_index"] for item in result["data"]["results"]] == [2]
    assert dispatched == [0.0]


def test_parallel_and_retry_reject_physical_side_effects() -> None:
    physical = ActionNode(
        node_id="move", command="linear_move",
        parameters={"target_pose": {axis: 0.0 for axis in ("x", "y", "z", "rx", "ry", "rz")},
                    "speed_pct": 10, "acceleration_pct": 10, "deceleration_pct": 10,
                    "r_min": 0, "r_max": 1000, "z_min": -1000, "z_max": 1000},
        contract=NodeContract(idempotency="request", side_effect="motion"),
    )
    with pytest.raises(ValueError, match="ParallelNode cannot contain hardware"):
        ParallelNode(node_id="parallel-motion", children=(physical,))
    with pytest.raises(ValueError, match="RetryNode cannot retry hardware"):
        RetryNode(node_id="retry-motion", child=physical, max_attempts=2)


def test_unknown_physical_result_never_runs_automatic_compensation() -> None:
    flow = FlowEntry(name="comp", flow_id="comp", steps=[
        FlowStep(1, "set", 120, {"io_number": 1, "enabled": True}),
        FlowStep(2, "reset", 120, {"io_number": 1, "enabled": False}),
    ])
    contract = NodeContract(idempotency="request", side_effect="io")
    primary = ActionNode(
        node_id="primary", command="io",
        parameters={"io_number": 1, "enabled": True, "allowed_io_channels": []},
        step_index=1, step_id=1, contract=contract,
    )
    reverse = ActionNode(
        node_id="reverse", command="io",
        parameters={"io_number": 1, "enabled": False, "allowed_io_channels": []},
        step_index=2, step_id=2, contract=contract,
    )
    snapshot = FlowExecutionSnapshot.create(
        flow, product_profile_version="1", capability_version="1", core_version="1",
        root_node=CompensationNode(
            node_id="compensation", child=primary,
            compensation=reverse, automatic=True,
        ),
    )
    dispatched: list[int] = []

    def runner(**kwargs):
        channel = kwargs["request"].parameters["io_number"]
        dispatched.append(channel)
        return {"ok": False, "state": "operation_outcome_unknown"}

    result = run_flow(
        snapshot, operator_runner=runner, allowed_io_output_channels=(1,),
    )
    assert result["state"] == "flow_node_failed"
    assert dispatched == [1]


def test_stop_before_primary_never_runs_automatic_compensation() -> None:
    flow = FlowEntry(name="stopped-comp", flow_id="stopped-comp", steps=[
        FlowStep(1, "set", 120, {"io_number": 1, "enabled": True}),
        FlowStep(2, "reset", 120, {"io_number": 1, "enabled": False}),
    ])
    contract = NodeContract(idempotency="request", side_effect="io")
    snapshot = FlowExecutionSnapshot.create(
        flow, product_profile_version="1", capability_version="1", core_version="1",
        root_node=CompensationNode(
            node_id="compensation",
            child=ActionNode(
                node_id="primary", command="io",
                parameters={"io_number": 1, "enabled": True, "allowed_io_channels": []},
                step_index=1, step_id=1, contract=contract,
            ),
            compensation=ActionNode(
                node_id="reverse", command="io",
                parameters={"io_number": 1, "enabled": False, "allowed_io_channels": []},
                step_index=2, step_id=2, contract=contract,
            ),
            automatic=True,
        ),
    )
    dispatched: list[int] = []

    result = run_flow(
        snapshot,
        operator_runner=lambda **kwargs: dispatched.append(
            kwargs["request"].parameters["io_number"]
        ) or {"ok": True, "state": "done"},
        before_step=lambda _index: False,
        allowed_io_output_channels=(1,),
    )

    assert result["state"] == "flow_stopped"
    assert dispatched == []


def test_restart_marks_interrupted_execution_for_reconciliation_without_replay(
    tmp_path: Path,
) -> None:
    history = ExecutionHistory(tmp_path / "history.json")
    execution_id = history.create(
        kind="flow", source_id="flow-1", step_count=2, actor="engineer:user-1",
    )
    history.mark_step(execution_id, 1, "running")

    recovered = LibraryExecutionRegistry(
        history=ExecutionHistory(tmp_path / "history.json")
    )
    record = recovered.get(execution_id)

    assert recovered.recovered_execution_ids == (execution_id,)
    assert record["state"] == "reconcile_required"
    assert record["result"]["state"] == "execution_outcome_unknown"
    assert record["allowed_actions"] == ["reset"]


def test_compensation_requires_authority_and_plans_only_explicit_io_reversal() -> None:
    io_snapshot = _snapshot(FlowStep(
        1, "io", 120,
        {"io_number": 3, "enabled": True, "allowed_io_channels": [3]},
    ))
    completed = [{
        "step_index": 1,
        "result": {
            "ok": True,
            "data": {"compensation": {"io_number": 3, "previous_enabled": False}},
        },
    }]

    with pytest.raises(PermissionError):
        plan_controlled_compensation(
            io_snapshot, completed, requested_by="engineer:user-1", authorized=False,
        )
    plan = plan_controlled_compensation(
        io_snapshot, completed, requested_by="engineer:user-1", authorized=True,
    )

    assert len(plan.actions) == 1
    assert dict(plan.actions[0].parameters) == {"io_number": 3, "enabled": False}
    assert plan.snapshot_hash == io_snapshot.content_hash

    motion = _snapshot(FlowStep(1, "move", 108, {"target_x": 1}))
    assert plan_controlled_compensation(
        motion, completed, requested_by="engineer:user-1", authorized=True,
    ).actions == ()


@pytest.mark.parametrize("channel,enabled", [(True, False), (1, "false"), ("1", True)])
def test_flow_io_schema_rejects_coercive_values(channel, enabled) -> None:
    with pytest.raises(ValueError, match="Invalid Flow step"):
        _snapshot(FlowStep(
            1, "io", 120,
            {"io_number": channel, "enabled": enabled, "allowed_io_channels": [1]},
        ))


@pytest.mark.asyncio
async def test_v2_discriminated_nodes_round_trip_and_execute_control_nodes() -> None:
    attempts = 0
    calls: list[str] = []

    async def runner(node: ActionNode):
        nonlocal attempts
        calls.append(node.node_id)
        if node.node_id == "retry-action":
            attempts += 1
            if attempts == 1:
                raise RuntimeError("transient")
        return node.node_id

    action_contract = NodeContract(
        capabilities=("state_read",), timeout_seconds=1,
        idempotency="request", side_effect="read",
    )
    retry = RetryNode(
        node_id="retry",
        child=ActionNode(
            node_id="retry-action", command="delay",
            parameters={"seconds": 0}, contract=action_contract,
        ),
        max_attempts=2,
    )
    condition = ConditionNode(
        node_id="condition", input_name="ready", comparison="eq", expected=True,
        if_true=retry,
    )
    parallel = ParallelNode(
        node_id="parallel",
        children=(
            ActionNode(node_id="left", command="delay", parameters={"seconds": 0},
                       contract=action_contract),
            ActionNode(node_id="right", command="delay", parameters={"seconds": 0},
                       contract=action_contract),
        ),
    )
    approved = HumanApprovalNode(
        node_id="approval", prompt="Continue?", approval_key="approval-1",
        child=condition,
    )
    root = SequenceNode(node_id="root", children=(approved, parallel))
    restored = node_from_dict(node_to_dict(root))

    transitions: list[tuple[str, str]] = []
    result = await execute_node(restored, FlowNodeExecutionContext(
        action_runner=runner,
        inputs={"ready": True},
        approval_checker=lambda _node: True,
        on_transition=lambda node_id, state: transitions.append((node_id, state)),
    ))

    assert result == ["left", "right"]
    assert attempts == 2
    assert ("approval", "succeeded") in transitions
    assert {"left", "right"} <= set(calls)


@pytest.mark.asyncio
async def test_timeout_and_reviewed_io_compensation_have_explicit_runtime_semantics() -> None:
    io_contract = NodeContract(
        capabilities=("io",), timeout_seconds=1,
        idempotency="request", side_effect="io",
    )
    primary = ActionNode(
        node_id="primary", command="io",
        parameters={"io_number": 1, "enabled": True},
        contract=io_contract,
    )
    reverse = ActionNode(
        node_id="reverse", command="io",
        parameters={"io_number": 1, "enabled": False},
        contract=io_contract,
    )
    compensation = CompensationNode(
        node_id="compensate", child=primary, compensation=reverse, automatic=True,
    )
    calls: list[str] = []

    async def failing(node: ActionNode):
        calls.append(node.node_id)
        if node.node_id == "primary":
            raise RuntimeError("failed")

    with pytest.raises(RuntimeError, match="failed"):
        await execute_node(compensation, FlowNodeExecutionContext(action_runner=failing))
    assert calls == ["primary", "reverse"]

    approval_guarded = CompensationNode(
        node_id="approval-compensation",
        child=HumanApprovalNode(
            node_id="approval", prompt="approve", approval_key="approval",
            child=primary,
        ),
        compensation=reverse,
        automatic=True,
    )
    calls.clear()
    with pytest.raises(PermissionError):
        await execute_node(
            approval_guarded,
            FlowNodeExecutionContext(
                action_runner=failing, approval_checker=lambda _node: False,
            ),
        )
    assert calls == []

    timeout = TimeoutNode(
        node_id="timeout",
        contract=NodeContract(timeout_seconds=0.01),
        child=ActionNode(
            node_id="slow", command="delay", parameters={"seconds": 1},
            contract=NodeContract(),
        ),
    )
    with pytest.raises(TimeoutError):
        await execute_node(
            timeout,
            FlowNodeExecutionContext(action_runner=lambda _node: asyncio.sleep(1)),
        )
