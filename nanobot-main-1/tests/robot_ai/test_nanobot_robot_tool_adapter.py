import asyncio
import json

import pytest


def _load_robot_tool():
    pytest.importorskip("loguru")
    pytest.importorskip("pydantic")
    from nanobot.agent.tools.robot_arm import RobotArmTool

    return RobotArmTool


def _run_tool(tool, **kwargs) -> dict:
    raw = asyncio.run(tool.execute(**kwargs))
    return json.loads(str(raw))


def test_robot_arm_tool_is_loaded_by_the_explicit_robot_product_loader(tmp_path) -> None:
    pytest.importorskip("loguru")
    pytest.importorskip("pydantic")
    from types import SimpleNamespace

    from ai_runtime.tool_loader import RobotToolLoader
    from nanobot.agent.tools.context import ToolContext
    from nanobot.agent.tools.registry import ToolRegistry

    RobotArmTool = _load_robot_tool()
    registry = ToolRegistry()
    context = ToolContext(
        config=SimpleNamespace(enabled_tools=["robot_arm"]),
        workspace=str(tmp_path),
    )
    RobotToolLoader().load(context, registry)

    assert isinstance(registry.get("robot_arm"), RobotArmTool)


def test_robot_arm_tool_status_action_returns_robot_state() -> None:
    RobotArmTool = _load_robot_tool()
    tool = RobotArmTool()

    result = _run_tool(tool, action="status")

    assert result["ok"] is True
    assert result["state"] == "status_report"
    assert result["data"]["robot_state"]["mode"] == "idle"


def test_robot_arm_tool_rejects_removed_legacy_motion_actions() -> None:
    RobotArmTool = _load_robot_tool()
    tool = RobotArmTool()

    result = _run_tool(tool, action="move_axis", axis="x", delta=10.0)

    assert result["ok"] is False
    assert result["state"] == "unknown_robot_action"


def test_robot_arm_tool_schema_lists_restricted_operator_actions_only() -> None:
    RobotArmTool = _load_robot_tool()
    params = RobotArmTool().parameters

    assert params["properties"]["action"]["enum"] == [
        "status",
        "emergency_stop",
        "release_emergency_stop",
        "pause",
        "resume",
        "stop_current",
        "release_cancel",
        "delay",
        "io",
        "linear_move",
        "linear_path",
    ]
    assert "move_axis" not in params["properties"]["action"]["enum"]
    assert "home" not in params["properties"]["action"]["enum"]
    assert "stop" not in params["properties"]["action"]["enum"]


def test_robot_arm_tool_rejects_unknown_action() -> None:
    RobotArmTool = _load_robot_tool()
    tool = RobotArmTool()

    result = _run_tool(tool, action="dance")

    assert result["ok"] is False
    assert result["state"] == "unknown_robot_action"
    assert result["errors"][0]["code"] == "unknown_robot_action"


def test_robot_arm_tool_is_exclusive_for_robot_safety() -> None:
    RobotArmTool = _load_robot_tool()
    tool = RobotArmTool()

    assert tool.exclusive is True
    assert tool.read_only is False


def test_robot_arm_tool_linear_move_channel_is_dry_run(monkeypatch) -> None:
    """In dry_run_only mode, the LLM-facing tool builds a request with
    execute_real=False (no real write), forwards the target pose, and returns
    the operator's result as JSON."""
    # Simulate dry_run_only mode regardless of the real config.
    monkeypatch.setattr("nanobot.agent.tools.robot_arm.AUTO_EXECUTE", False)

    RobotArmTool = _load_robot_tool()
    captured: dict = {}

    def fake_operator_runner(*, request, config=None, client_factory=None, executor_factory=None):
        captured["request"] = request
        return {
            "ok": True,
            "state": "zmotion_operator_dry_run",
            "message": "Dry-run plan created; no controller writes were issued.",
            "data": {
                "real_execution": False,
                "plan": {"function_code": 108, "blockers": ["operator_confirmation_missing"]},
            },
            "errors": [],
        }

    tool = RobotArmTool(operator_runner=fake_operator_runner)
    result = _run_tool(
        tool,
        action="linear_move",
        target_pose={"x": 900.0, "y": 0.0, "z": 999.0, "rx": 0.0, "ry": 0.0, "rz": 0.0},
        speed_pct=5.0,
    )

    req = captured["request"]
    assert req.command == "linear_move"
    assert req.parameters["target_pose"]["x"] == 900.0
    assert req.parameters["target_pose"]["z"] == 999.0
    # The LLM tool path must never set execute_real — real writes only come from
    # the human-confirmed operator CLI/bridge.
    assert req.execute_real is False

    assert result["ok"] is True
    assert result["state"] == "zmotion_operator_dry_run"
    assert result["data"]["real_execution"] is False
    assert result["data"]["plan"]["function_code"] == 108
