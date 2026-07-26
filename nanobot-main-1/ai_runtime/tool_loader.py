"""Robot-only tool registration for the desktop AI runtime.

The generic nanobot loader discovers every optional tool module.  The robot
desktop product deliberately exposes only its four robot capabilities, so an
explicit loader makes that boundary auditable and keeps optional integrations
out of the packaged runtime.
"""

from __future__ import annotations

from typing import Any

from nanobot.agent.tools.allowlist import tool_allowed
from nanobot.agent.tools.cron import CronTool
from nanobot.agent.tools.registry import ToolRegistry
from ai_runtime.robot_tools.robot_arm import RobotArmTool
from ai_runtime.robot_tools.robot_flow import RobotFlowTool
from ai_runtime.robot_tools.robot_knowledge import RobotKnowledgeTool
from ai_runtime.robot_tools.robot_library import RobotLibraryTool
from ai_runtime.robot_tools.robot_position import RobotPositionTool


class RobotToolLoader:
    """Register only the supported robot tools, respecting ``enabled_tools``."""

    _tool_classes = (
        RobotArmTool,
        RobotFlowTool,
        RobotKnowledgeTool,
        RobotPositionTool,
        RobotLibraryTool,
        # Automations are a first-class desktop capability.  CronTool owns
        # only the local runtime's scheduler; it does not reintroduce any
        # chat-channel dependency.
        CronTool,
    )

    def load(self, ctx: Any, registry: ToolRegistry, *, scope: str = "core") -> list[str]:
        if scope != "core":
            return []
        enabled_tools = getattr(ctx.config, "enabled_tools", [])
        registered: list[str] = []
        for tool_cls in self._tool_classes:
            if not tool_cls.enabled(ctx):
                continue
            tool = tool_cls.create(ctx)
            if tool.name != "robot_library" and not tool_allowed(tool.name, enabled_tools):
                continue
            registry.register(tool)
            registered.append(tool.name)
        return registered
