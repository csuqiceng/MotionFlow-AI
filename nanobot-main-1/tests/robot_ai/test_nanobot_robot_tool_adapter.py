import asyncio
import json

from nanobot.agent.tools.loader import ToolLoader
from nanobot.agent.tools.robot_arm import RobotArmTool


def _run_tool(tool: RobotArmTool, **kwargs) -> dict:
    raw = asyncio.run(tool.execute(**kwargs))
    return json.loads(str(raw))


def test_robot_arm_tool_is_discoverable_by_loader() -> None:
    discovered = ToolLoader().discover()

    assert RobotArmTool in discovered


def test_robot_arm_tool_status_action_returns_robot_state() -> None:
    tool = RobotArmTool()

    result = _run_tool(tool, action="status")

    assert result["ok"] is True
    assert result["state"] == "status_report"
    assert result["data"]["robot_state"]["mode"] == "idle"


def test_robot_arm_tool_move_axis_action_updates_state() -> None:
    tool = RobotArmTool()

    result = _run_tool(tool, action="move_axis", axis="x", delta=10.0)

    assert result["ok"] is True
    assert result["state"] == "simulated_motion_completed"
    assert result["data"]["position"] == 10.0


def test_robot_arm_tool_rejects_unknown_action() -> None:
    tool = RobotArmTool()

    result = _run_tool(tool, action="dance")

    assert result["ok"] is False
    assert result["state"] == "unknown_robot_action"
    assert result["errors"][0]["code"] == "unknown_robot_action"


def test_robot_arm_tool_is_exclusive_for_robot_safety() -> None:
    tool = RobotArmTool()

    assert tool.exclusive is True
    assert tool.read_only is False
