from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("loguru")
pytest.importorskip("pydantic")

from nanobot.agent.tools.robot_flow import RobotFlowTool  # noqa: E402
from robot_ai.models import ToolResult  # noqa: E402


def _tool(tmp_path) -> RobotFlowTool:
    return RobotFlowTool(str(tmp_path / "flows.json"))


def _run(tool: RobotFlowTool, **kwargs) -> dict:
    return json.loads(asyncio.run(tool.execute(**kwargs)))


def _delay_step(seconds: float = 1.0) -> dict:
    return {"step_id": 1, "action": "delay", "func_id": 110, "params": {"seconds": seconds}}


def test_register_list_get_confirm_delete(tmp_path) -> None:
    tool = _tool(tmp_path)

    registered = _run(tool, action="register", name="Pick", steps=[_delay_step()])
    assert registered["ok"] is True
    assert registered["state"] == "flow_registered"

    listed = _run(tool, action="list")
    assert listed["data"]["count"] == 1
    assert listed["data"]["flows"][0]["name"] == "Pick"

    got = _run(tool, action="get", name="pick")  # case-insensitive
    assert got["ok"] is True
    assert got["data"]["flow"]["name"] == "Pick"

    confirmed = _run(tool, action="confirm", name="Pick")
    assert confirmed["ok"] is True
    assert confirmed["state"] == "flow_confirmed"

    deleted = _run(tool, action="delete", name="Pick")
    assert deleted["ok"] is True
    assert _run(tool, action="list")["data"]["count"] == 0


def test_register_rejects_empty_name_or_steps(tmp_path) -> None:
    tool = _tool(tmp_path)
    assert _run(tool, action="register", name="", steps=[_delay_step()])["ok"] is False
    assert _run(tool, action="register", name="X", steps=[])["ok"] is False


def test_get_missing_flow(tmp_path) -> None:
    tool = _tool(tmp_path)
    result = _run(tool, action="get", name="missing")
    assert result["ok"] is False
    assert result["state"] == "flow_not_found"


def test_unknown_action(tmp_path) -> None:
    tool = _tool(tmp_path)
    result = _run(tool, action="bogus")
    assert result["state"] == "unknown_flow_action"


def test_run_flow_through_tool(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    tool = _tool(tmp_path)
    _run(tool, action="register", name="RunMe", steps=[_delay_step(), _delay_step(2.0)])

    import robot_ai.flow.executor as executor_module

    monkeypatch.setattr(
        executor_module,
        "run_zmotion_operator_command",
        lambda **kwargs: ToolResult.success(state="zmotion_operator_dry_run", data={}).to_dict(),
    )

    result = _run(tool, action="run", name="runme")
    assert result["ok"] is True
    assert result["state"] == "flow_completed"
    assert result["data"]["total_steps"] == 2


def test_run_missing_flow(tmp_path) -> None:
    tool = _tool(tmp_path)
    result = _run(tool, action="run", name="ghost")
    assert result["state"] == "flow_not_found"


def test_robot_flow_schema_does_not_expose_real_execution_params() -> None:
    """The LLM must not be able to pass execute_real / confirmation params."""
    params = RobotFlowTool().parameters
    props = params["properties"]
    assert "execute_real" not in props
    assert "confirm_work_area_clear" not in props
    assert "confirm_estop_ready" not in props
    assert "confirmation_code" not in props


def test_robot_flow_run_ignores_llm_execute_real_and_uses_config(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The tool uses execution_mode config, not LLM-supplied execute_real.
    In dry_run_only mode (AUTO_EXECUTE=False), even if the LLM passes
    execute_real=True, the tool stays dry-run."""
    # Simulate dry_run_only mode regardless of the real config.
    monkeypatch.setattr("nanobot.agent.tools.robot_flow.AUTO_EXECUTE", False)

    tool = _tool(tmp_path)
    _run(tool, action="register", name="RunMe", steps=[_delay_step()])

    captured: dict = {}

    def fake_runner(**kwargs):
        request = kwargs["request"]
        captured["execute_real"] = request.execute_real
        return ToolResult.success(
            state="zmotion_operator_dry_run",
            data={"real_execution": request.execute_real},
        ).to_dict()

    import robot_ai.flow.executor as executor_module

    monkeypatch.setattr(executor_module, "run_zmotion_operator_command", fake_runner)

    # LLM attempts to force real execution via the side door:
    result = _run(
        tool,
        action="run",
        name="runme",
        execute_real=True,
        confirm_work_area_clear=True,
        confirm_estop_ready=True,
        confirmation_code="EXECUTE_ZMOTION_REAL",
    )

    assert captured["execute_real"] is False  # forced dry-run despite LLM's True
    assert result["ok"] is True
    assert result["data"]["real_execution"] is False


def test_robot_flow_register_rejects_alarm_reset_step(tmp_path) -> None:
    """alarm_reset is operator-only; the LLM can't sneak it into a flow step."""
    tool = _tool(tmp_path)
    result = _run(
        tool,
        action="register",
        name="Bad",
        steps=[
            {
                "step_id": 1,
                "action": "alarm_reset",
                "func_id": 104,
                "params": {"action": "alarm_reset"},
            }
        ],
    )
    assert result["ok"] is False
    assert result["state"] == "flow_invalid"
    assert result["errors"][0]["code"] == "alarm_reset_not_allowed_in_flow"
