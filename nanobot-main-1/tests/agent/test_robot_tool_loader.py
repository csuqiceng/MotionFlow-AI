from __future__ import annotations

from types import SimpleNamespace

from ai_runtime.tool_loader import RobotToolLoader
from nanobot.agent.tools.context import ToolContext
from nanobot.agent.tools.registry import ToolRegistry


def test_robot_tool_loader_registers_only_robot_capabilities(tmp_path) -> None:
    registry = ToolRegistry()
    context = ToolContext(
        config=SimpleNamespace(enabled_tools=["robot_arm", "robot_position"]),
        workspace=str(tmp_path),
    )

    registered = RobotToolLoader().load(context, registry)

    assert registered == ["robot_arm", "robot_position"]
    assert registry.tool_names == ["robot_arm", "robot_position"]
