"""Current Robot Flow tool boundary: agents may read/run, not author flows."""

from __future__ import annotations

import asyncio
import json

from ai_runtime.robot_tools.robot_flow import RobotFlowTool
from robot_platform.flow import FlowEntry, FlowRegistry, FlowStep


def _run(tool: RobotFlowTool, **kwargs: object) -> dict:
    return json.loads(asyncio.run(tool.execute(**kwargs)))


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

    result = _run(RobotFlowTool(str(path)), action="list")

    assert result["ok"] is True
    assert result["state"] == "flow_list"
    assert [flow["name"] for flow in result["data"]["flows"]] == ["已发布流程"]


def test_agent_can_get_a_saved_flow(tmp_path) -> None:
    path = tmp_path / "flows.json"
    _save_flow(path, "上料")

    result = _run(RobotFlowTool(str(path)), action="get", name="上料")

    assert result["ok"] is True
    assert result["state"] == "flow_found"
    assert result["data"]["flow"]["name"] == "上料"


def test_agent_cannot_register_a_new_flow(tmp_path) -> None:
    result = _run(
        RobotFlowTool(str(tmp_path / "flows.json")),
        action="register",
        name="禁止的 LLM 创作",
        steps=[{"step_id": 1, "func_id": 108, "params": {}}],
    )

    assert result["ok"] is False
    assert result["state"] == "unknown_flow_action"
