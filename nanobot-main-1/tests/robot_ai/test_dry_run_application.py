from __future__ import annotations

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from ai_runtime.robot_tools.robot_arm import RobotArmTool
from ai_runtime.robot_tools.robot_flow import RobotFlowTool
from robot_platform.adapters.flow import FileRobotFlowAdapter
from robot_platform.application import (
    AuthenticatedPrincipal,
    RobotDryRunApplicationService,
    RobotDryRunResponse,
    RobotFlowApplicationService,
)
from robot_platform.execution import PendingPlanStore, SessionGateStore
from robot_platform.flow import FlowEntry, FlowRegistry, FlowStep


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        actor_id="operator-1", role="operator", session_id="session-1",
        auth_source="test",
    )


def _service(platform=None, *, allowed_io_output_channels=()):
    return RobotDryRunApplicationService(
        platform or MagicMock(), PendingPlanStore(), SessionGateStore(),
        product_profile_version="profile-v1",
        capability_version="cap-v1",
        core_version="core-v1",
        allowed_io_output_channels=allowed_io_output_channels,
    )


def test_command_preview_and_stage_share_one_dry_run_path() -> None:
    platform = MagicMock()
    platform.plan_motion.return_value = {
        "ok": True, "state": "planned", "data": {"real_execution": False},
    }
    service = _service(platform)

    staged = service.stage_command(_principal(), "delay", {"seconds": 0.1})

    assert staged.ok and staged.staged
    assert staged.payload["plan"]["data"]["real_execution"] is False
    platform.plan_motion.assert_called_once_with("delay", {"seconds": 0.1})
    assert service._pending_plans.get(staged.payload["plan_id"]) is not None
    assert service._session_gates.get("robot-server:session-1").pending_plan_id == staged.payload["plan_id"]


def test_failed_command_preview_is_not_staged() -> None:
    platform = MagicMock()
    platform.plan_motion.return_value = {"ok": False, "state": "rejected"}
    service = _service(platform)

    result = service.stage_command(_principal(), "delay", {"seconds": -1})

    assert result.payload == {"ok": False, "state": "rejected"}
    assert result.staged is False
    assert service._pending_plans._plans == {}


def test_io_stage_injects_server_owned_channel_policy_into_frozen_plan() -> None:
    platform = MagicMock()
    platform.plan_motion.return_value = {"ok": True, "state": "planned"}
    service = _service(platform, allowed_io_output_channels=(8, 3))

    result = service.stage_command(
        _principal(), "io", {"io_number": 3, "enabled": True},
    )

    assert result.ok and result.staged
    canonical = {
        "io_number": 3,
        "enabled": True,
        "allowed_io_channels": [3, 8],
    }
    platform.plan_motion.assert_called_once_with("io", canonical)
    stored = service._pending_plans.get(result.payload["plan_id"])
    assert stored.parameters == canonical


@pytest.mark.parametrize(
    "parameters",
    [
        {"io_number": 999, "enabled": True},
        {
            "io_number": 999,
            "enabled": True,
            "allowed_io_channels": [999],
        },
        {"io_number": True, "enabled": True},
        {"io_number": 3, "enabled": 1},
    ],
)
def test_io_caller_cannot_supply_or_extend_channel_policy(parameters) -> None:
    platform = MagicMock()
    service = _service(platform, allowed_io_output_channels=(3, 8))

    result = service.stage_command(_principal(), "io", parameters)

    assert result.error.code == "invalid_request"
    platform.plan_motion.assert_not_called()
    assert service._pending_plans._plans == {}


def test_partial_stage_failure_rolls_back_plan_and_session_gate() -> None:
    class FailingGate(SessionGateStore):
        def set_pending_plan(self, session_key, plan_id) -> None:
            super().set_pending_plan(session_key, plan_id)
            raise RuntimeError("gate persistence failed")

    platform = MagicMock()
    platform.plan_motion.return_value = {"ok": True, "state": "planned"}
    plans = PendingPlanStore()
    gates = FailingGate()
    SessionGateStore.set_pending_plan(
        gates, "robot-server:session-1", "previous-plan",
    )
    service = RobotDryRunApplicationService(
        platform, plans, gates,
        product_profile_version="profile-v1", capability_version="cap-v1",
        core_version="core-v1",
    )

    result = service.stage_command(_principal(), "delay", {"seconds": 0})

    assert result.error.code == "planning_state_unavailable"
    assert plans._plans == {}
    assert gates.get("robot-server:session-1").pending_plan_id == "previous-plan"


def test_command_stage_freezes_parameters_once_before_dry_run() -> None:
    entered = threading.Event()
    release = threading.Event()
    received: list[dict] = []
    platform = MagicMock()

    def blocking_preview(command, parameters):
        del command
        received.append(deepcopy(parameters))
        entered.set()
        assert release.wait(timeout=5)
        return {"ok": True, "state": "planned"}

    platform.plan_motion.side_effect = blocking_preview
    service = _service(platform)
    original = {"target": {"x": 1}}
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            service.stage_command, _principal(), "linear_move", original,
        )
        assert entered.wait(timeout=5)
        original["target"]["x"] = 999
        release.set()
        result = future.result(timeout=5)

    stored = service._pending_plans.get(result.payload["plan_id"])
    assert received == [{"target": {"x": 1}}]
    assert stored.parameters == received[0]
    assert original == {"target": {"x": 999}}


def test_flow_stage_freezes_snapshot_and_never_requests_real_execution() -> None:
    platform = MagicMock()
    platform.resolve_flow.return_value = FlowEntry(
        name="flow", steps=[FlowStep(1, "delay", 110, {"seconds": 0})],
    )
    platform.run_flow_entry.return_value = {
        "ok": True, "state": "flow_dry_run", "data": {"real_execution": False},
    }
    service = _service(platform)

    result = service.stage_flow(_principal(), "flow", alias="spoken-flow")

    assert result.ok and result.staged
    assert result.payload["content_hash"]
    platform.run_flow_entry.assert_called_once()
    assert platform.run_flow_entry.call_args.kwargs["execute_real"] is False
    stored = service._pending_plans.get(result.payload["plan_id"])
    assert stored.parameters["snapshot"]["resolved_alias"] == "spoken-flow"


def test_dry_run_exception_is_sanitized() -> None:
    platform = MagicMock()
    platform.plan_motion.side_effect = RuntimeError("controller secret")
    result = _service(platform).preview_command("delay", {"seconds": 0})
    assert result.error.code == "dry_run_unavailable"
    assert "secret" not in result.error.message


def test_flow_resolution_value_error_is_sanitized() -> None:
    platform = MagicMock()
    platform.resolve_flow.side_effect = ValueError("controller secret path")
    result = _service(platform).stage_flow(_principal(), "flow")
    assert result.error.code == "dry_run_unavailable"
    assert "secret" not in result.error.message


def test_dry_run_response_rejects_impossible_state() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        RobotDryRunResponse()


def test_robot_arm_preview_uses_application_port_not_platform(tmp_path) -> None:
    platform = MagicMock()
    platform.plan_motion.side_effect = AssertionError("Tool bypassed dry-run Application")
    planning = MagicMock()
    planning.preview_command.return_value = RobotDryRunResponse(
        payload={"ok": True, "state": "planned", "data": {}},
    )
    tool = RobotArmTool(
        platform=platform, dry_run_application=planning,
        positions_path=str(tmp_path / "positions.json"),
    )
    result = json.loads(asyncio.run(tool.execute(action="delay", seconds=0.1)))
    assert result["state"] == "planned"
    planning.preview_command.assert_called_once_with("delay", {"seconds": 0.1})
    platform.plan_motion.assert_not_called()


def test_robot_flow_preview_uses_application_port_not_platform(tmp_path) -> None:
    flow_path = tmp_path / "flows.json"
    ok, _ = FlowRegistry(flow_path).add(
        FlowEntry(name="flow", steps=[FlowStep(1, "delay", 110, {"seconds": 0})]),
    )
    assert ok
    platform = MagicMock()
    platform.run_flow_entry.side_effect = AssertionError("Tool bypassed dry-run Application")
    planning = MagicMock()
    planning.preview_flow_entry.return_value = RobotDryRunResponse(
        payload={"ok": True, "state": "flow_dry_run", "data": {}},
    )
    tool = RobotFlowTool(
        flow_application=RobotFlowApplicationService(
            FileRobotFlowAdapter(
                tmp_path,
                flows_path=flow_path,
                aliases_path=tmp_path / "aliases.json",
            ),
            planning,
        ),
    )
    result = json.loads(asyncio.run(tool.execute(action="run", name="flow")))
    assert result["state"] == "flow_dry_run"
    planning.preview_flow_entry.assert_called_once()
    platform.run_flow_entry.assert_not_called()
