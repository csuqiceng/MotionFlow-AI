"""Robot-only tool registration for the desktop AI runtime.

The generic nanobot loader discovers every optional tool module.  The robot
desktop product deliberately exposes only its four robot capabilities, so an
explicit loader makes that boundary auditable and keeps optional integrations
out of the packaged runtime.
"""

from __future__ import annotations

from typing import Any

from ai_runtime.robot_tools.robot_arm import RobotArmTool
from ai_runtime.robot_tools.robot_flow import RobotFlowTool
from ai_runtime.robot_tools.robot_knowledge import RobotKnowledgeTool
from ai_runtime.robot_tools.robot_library import RobotLibraryTool
from ai_runtime.robot_tools.robot_position import RobotPositionTool
from ai_runtime.robot_tools.loader import (
    NanobotToolRuntimeAdapter,
    adapt_legacy_robot_tool,
)
from ai_runtime.tool_catalog import PRODUCT_TOOL_MANIFESTS_BY_ID
from ai_runtime.tool_runtime import ProductToolRuntime, ToolAuditPort
from ai_runtime.tool_operation_store import ToolOperationStorePort
from nanobot.agent.tools.cron import CronTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.cron.application import CronApplicationPort, CronMutationPolicyPort


class RobotToolLoader:
    """Register only the supported robot tools, respecting ``enabled_tools``."""

    def __init__(
        self,
        *,
        enabled_tools: list[str] | None = None,
        platform: Any = None,
        status_application: Any = None,
        dry_run_application: Any = None,
        automatic_motion_application: Any = None,
        automatic_flow_application: Any = None,
        knowledge_application: Any = None,
        position_application: Any = None,
        library_application: Any = None,
        flow_application: Any = None,
        cron_application: CronApplicationPort | None = None,
        cron_mutation_policy: CronMutationPolicyPort | None = None,
        tool_audit: ToolAuditPort | None = None,
        tool_operation_store: ToolOperationStorePort | None = None,
    ) -> None:
        self._enabled_tools = enabled_tools
        self._platform = platform
        self._status_application = status_application
        self._dry_run_application = dry_run_application
        self._automatic_motion_application = automatic_motion_application
        self._automatic_flow_application = automatic_flow_application
        self._knowledge_application = knowledge_application
        self._position_application = position_application
        self._library_application = library_application
        self._flow_application = flow_application
        self._cron_application = cron_application
        self._cron_mutation_policy = cron_mutation_policy
        self._tool_audit = tool_audit
        self._tool_operation_store = tool_operation_store

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
        enabled_tools = self._enabled_tools if self._enabled_tools is not None else getattr(ctx.config, "enabled_tools", [])
        capabilities = (
            self._platform.controller_capabilities
            if self._platform is not None
            else {"supports_state_read": True, "motion_primitives": []}
        )
        runtime = ProductToolRuntime(
            capabilities=capabilities,
            enabled_tool_ids=enabled_tools,
            audit=self._tool_audit,
            target_device_id=(
                self._platform.execution_context().get("controller_id", "")
                if self._platform is not None else ""
            ),
            state_reader=(
                self._platform.get_status if self._platform is not None else None
            ),
            operation_store=self._tool_operation_store,
        )
        registered: list[str] = []
        for tool_cls in self._tool_classes:
            if (
                tool_cls is CronTool
                and enabled_tools is not None
                and "*" not in enabled_tools
                and "cron" not in enabled_tools
            ):
                continue
            if tool_cls is CronTool and self._cron_application is None:
                continue
            if tool_cls is not CronTool and not tool_cls.enabled(ctx):
                continue
            if self._platform is not None and tool_cls is RobotArmTool:
                tool = RobotArmTool(
                    status_application=self._status_application,
                    dry_run_application=self._dry_run_application,
                    automatic_motion_application=self._automatic_motion_application,
                    position_application=self._position_application,
                )
            elif tool_cls is RobotFlowTool:
                tool = RobotFlowTool(
                    flow_application=self._flow_application,
                    automatic_flow_application=self._automatic_flow_application,
                )
            elif tool_cls is RobotKnowledgeTool:
                tool = RobotKnowledgeTool(
                    knowledge_application=self._knowledge_application,
                )
            elif tool_cls is RobotPositionTool:
                tool = RobotPositionTool(
                    position_application=self._position_application,
                )
            elif tool_cls is RobotLibraryTool:
                tool = RobotLibraryTool(
                    library_application=self._library_application,
                )
            elif tool_cls is CronTool:
                tool = CronTool(
                    self._cron_application,
                    default_timezone=ctx.timezone,
                    mutation_policy=self._cron_mutation_policy,
                )
            else:
                tool = tool_cls.create(ctx)
            manifest = PRODUCT_TOOL_MANIFESTS_BY_ID[tool.name]
            stable_tool = adapt_legacy_robot_tool(tool, manifest=manifest)
            runtime.register(stable_tool, manifest)
            if tool.name not in runtime.exposed_tool_ids(role="operator"):
                continue
            registry.register(NanobotToolRuntimeAdapter(runtime, tool, manifest))
            registered.append(tool.name)
        return registered
