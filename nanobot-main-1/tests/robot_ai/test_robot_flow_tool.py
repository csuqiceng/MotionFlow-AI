from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("loguru")
pytest.importorskip("pydantic")

from nanobot.agent.tools.robot_flow import RobotFlowTool  # noqa: E402
from robot_ai.models import ToolResult  # noqa: E402
from robot_platform.flow import FlowEntry, FlowRegistry, FlowStep


def _tool(tmp_path) -> RobotFlowTool:
    return RobotFlowTool(str(tmp_path / "flows.json"))


def _run(tool: RobotFlowTool, **kwargs) -> dict:
    return json.loads(asyncio.run(tool.execute(**kwargs)))


def _delay_step(seconds: float = 1.0) -> dict:
    return {"step_id": 1, "action": "delay", "func_id": 110, "params": {"seconds": seconds}}


def _save_flow(tmp_path, name: str, steps: list[dict]) -> None:
    ok, message = FlowRegistry(tmp_path / "flows.json").add(
        FlowEntry(name=name, steps=[FlowStep.from_dict(step) for step in steps])
    )
    assert ok is True, message


def test_list_and_get_pre_saved_flow(tmp_path) -> None:
    tool = _tool(tmp_path)
    _save_flow(tmp_path, "Pick", [_delay_step()])

    listed = _run(tool, action="list")
    assert listed["data"]["count"] == 1
    assert listed["data"]["flows"][0]["name"] == "Pick"

    got = _run(tool, action="get", name="pick")  # case-insensitive
    assert got["ok"] is True
    assert got["data"]["flow"]["name"] == "Pick"

def test_removed_flow_authoring_actions_are_rejected(tmp_path) -> None:
    tool = _tool(tmp_path)
    assert _run(tool, action="register", name="X", steps=[_delay_step()])["state"] == "unknown_flow_action"
    assert _run(tool, action="confirm", name="X")["state"] == "unknown_flow_action"
    assert _run(tool, action="delete", name="X")["state"] == "unknown_flow_action"


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
    _save_flow(tmp_path, "RunMe", [_delay_step(), _delay_step(2.0)])

    import robot_platform.flow.executor as executor_module

    monkeypatch.setattr(
        executor_module,
        "run_operator_command",
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
    In dry_run_only mode, even if the LLM passes
    execute_real=True, the tool stays dry-run."""
    # The tool resolves the host runtime value dynamically, rather than using
    # a boolean captured when the module was imported.
    monkeypatch.setattr(
        "nanobot.agent.tools.robot_flow.get_robot_execution_mode",
        lambda: "dry_run_only",
    )

    tool = _tool(tmp_path)
    _save_flow(tmp_path, "RunMe", [_delay_step()])

    captured: dict = {}

    def fake_runner(**kwargs):
        request = kwargs["request"]
        captured["execute_real"] = request.execute_real
        return ToolResult.success(
            state="zmotion_operator_dry_run",
            data={"real_execution": request.execute_real},
        ).to_dict()

    import robot_platform.flow.executor as executor_module

    monkeypatch.setattr(executor_module, "run_operator_command", fake_runner)

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


def test_robot_flow_rejects_removed_alarm_reset_authoring_action(tmp_path) -> None:
    """LLM-facing authoring is removed; alarm reset cannot enter a flow tool call."""
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
    assert result["state"] == "unknown_flow_action"
