"""Current Robot Flow tool boundary: agents may read/run, not author flows."""

from __future__ import annotations

import asyncio
import json

from ai_runtime.robot_tools.robot_flow import RobotFlowTool
from robot_platform.adapters.flow import FileRobotFlowAdapter
from robot_platform.application import (
    RobotDryRunApplicationService,
    RobotFlowApplicationService,
)
from robot_platform.flow import FlowEntry, FlowRegistry, FlowStep
from robot_platform.platform import RobotPlatform


def _run(tool: RobotFlowTool, **kwargs: object) -> dict:
    return json.loads(asyncio.run(tool.execute(**kwargs)))


def _tool(tmp_path, path=None) -> RobotFlowTool:
    flows = path or tmp_path / "flows.json"
    platform = RobotPlatform(flows_path=flows)
    dry_run = RobotDryRunApplicationService(
        platform, None, None,
        product_profile_version="test",
        capability_version="test",
        core_version="test",
    )
    return RobotFlowTool(flow_application=RobotFlowApplicationService(
        FileRobotFlowAdapter(tmp_path, flows_path=flows), dry_run,
    ))


def _save_flow(path, name: str = "已发布流程") -> None:
    ok, message = FlowRegistry(path).add(
        FlowEntry(
            name=name,
            steps=[FlowStep(step_id=1, action="delay", func_id=110, params={"seconds": 1})],
        )
    )
    assert ok, message


def test_agent_can_list_a_saved_flow(tmp_path) -> None:
    path = tmp_path / "flows.json"
    _save_flow(path)

    result = _run(_tool(tmp_path, path), action="list")

    assert result["ok"] is True
    assert result["state"] == "flow_list"
    assert [flow["name"] for flow in result["data"]["flows"]] == ["已发布流程"]


def test_agent_can_get_a_saved_flow(tmp_path) -> None:
    path = tmp_path / "flows.json"
    _save_flow(path, "上料")

    result = _run(_tool(tmp_path, path), action="get", name="上料")

    assert result["ok"] is True
    assert result["state"] == "flow_found"
    assert result["data"]["flow"]["name"] == "上料"


def test_agent_cannot_register_a_new_flow(tmp_path) -> None:
    result = _run(
        _tool(tmp_path),
        action="register",
        name="禁止的 LLM 创作",
        steps=[{"step_id": 1, "func_id": 108, "params": {}}],
    )

    assert result["ok"] is False
    assert result["state"] == "unknown_flow_action"
