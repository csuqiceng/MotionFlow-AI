from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("loguru")
pytest.importorskip("pydantic")

from nanobot.agent.tools.robot_flow import RobotFlowTool  # noqa: E402


def _run(tool: RobotFlowTool, **kwargs) -> dict:
    return json.loads(asyncio.run(tool.execute(**kwargs)))


def _step(func_id: int, action: str = "", params: dict | None = None) -> dict:
    return {
        "step_id": 1,
        "action": action,
        "func_id": func_id,
        "params": params or {},
    }


def test_register_rejects_unknown_func_id(tmp_path) -> None:
    tool = RobotFlowTool(str(tmp_path / "flows.json"))
    result = _run(tool, action="register", name="Bad", steps=[_step(999)])
    assert result["ok"] is False
    assert result["state"] == "flow_invalid"
    assert result["errors"][0]["code"] == "step_func_not_allowed"


def test_register_rejects_func_id_104_alarm_reset(tmp_path) -> None:
    tool = RobotFlowTool(str(tmp_path / "flows.json"))
    result = _run(
        tool,
        action="register",
        name="Bad",
        steps=[_step(104, "alarm_reset", {"action": "alarm_reset"})],
    )
    assert result["ok"] is False
    assert result["errors"][0]["code"] == "alarm_reset_not_allowed_in_flow"


def test_register_rejects_func_id_104_unknown_action(tmp_path) -> None:
    tool = RobotFlowTool(str(tmp_path / "flows.json"))
    result = _run(
        tool,
        action="register",
        name="Bad",
        steps=[_step(104, "bogus", {"action": "bogus"})],
    )
    assert result["ok"] is False
    assert result["errors"][0]["code"] == "step_action_not_allowed"


def test_register_allows_func_id_104_pause(tmp_path) -> None:
    tool = RobotFlowTool(str(tmp_path / "flows.json"))
    result = _run(
        tool,
        action="register",
        name="Ok",
        steps=[_step(104, "pause", {"action": "pause"})],
    )
    assert result["ok"] is True


def test_register_allows_func_id_104_system_actions(tmp_path) -> None:
    tool = RobotFlowTool(str(tmp_path / "flows.json"))
    for action in (
        "emergency_stop",
        "release_emergency_stop",
        "pause",
        "resume",
        "stop_current",
        "release_cancel",
    ):
        result = _run(
            tool,
            action="register",
            name=f"Ok-{action}",
            steps=[_step(104, action, {"action": action})],
        )
        assert result["ok"] is True, action


def test_register_allows_func_id_108(tmp_path) -> None:
    tool = RobotFlowTool(str(tmp_path / "flows.json"))
    result = _run(
        tool,
        action="register",
        name="Ok",
        steps=[
            _step(
                108,
                "linear_move",
                {"target_pose": {"x": 1, "y": 2, "z": 3, "rx": 0, "ry": 0, "rz": 0}},
            )
        ],
    )
    assert result["ok"] is True


def test_register_allows_func_id_0_migrated_non_executable(tmp_path) -> None:
    """func_id=0 steps (migrated free-text) are kept for reference but won't
    execute (run_flow maps func_id=0 to 'unsupported')."""
    tool = RobotFlowTool(str(tmp_path / "flows.json"))
    result = _run(
        tool,
        action="register",
        name="Migrated",
        steps=[_step(0, "移动到位置A", {"query_key": "移动到位置A"})],
    )
    assert result["ok"] is True
