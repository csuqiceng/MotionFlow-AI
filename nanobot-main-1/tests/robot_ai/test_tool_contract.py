"""Stable tool-runtime contracts independent of the Nanobot implementation."""

from __future__ import annotations

import asyncio
import importlib

from ai_runtime.tool_contracts import ToolContext, ToolInvocation, ToolResult
from ai_runtime.tool_manifest import ToolManifest
from ai_runtime.robot_tools.loader import adapt_legacy_robot_tool


class _LegacyTool:
    name = "robot_demo"
    parameters = {"type": "object", "properties": {"value": {"type": "integer"}}}

    def __init__(self) -> None:
        self.received: dict[str, int] | None = None

    async def execute(self, **kwargs: int) -> str:
        self.received = kwargs
        return '{"ok": true, "state": "demo_completed", "message": "ok", "data": {"value": 7}, "errors": []}'


def test_legacy_robot_tool_adapter_preserves_name_schema_and_structured_result() -> None:
    legacy = _LegacyTool()
    adapter = adapt_legacy_robot_tool(legacy)

    result = asyncio.run(
        adapter.execute(
            ToolContext(actor="user:42", session_key="session-1"),
            ToolInvocation(name="robot_demo", parameters={"value": 7}),
        )
    )

    assert adapter.name == "robot_demo"
    assert adapter.parameters == _LegacyTool.parameters
    assert legacy.received == {"value": 7}
    assert result == ToolResult.success(
        state="demo_completed",
        message="ok",
        data={"value": 7},
    )


def test_legacy_robot_tool_adapter_carries_the_product_tool_manifest() -> None:
    manifest = ToolManifest(
        tool_id="robot_demo",
        version="1.0.0",
        required_capabilities=("state_read",),
        allowed_roles=("engineer",),
    )

    adapter = adapt_legacy_robot_tool(_LegacyTool(), manifest=manifest)

    assert adapter.manifest is manifest


def test_legacy_robot_tool_modules_alias_the_runtime_implementations() -> None:
    for name in ("robot_arm", "robot_flow", "robot_knowledge", "robot_library", "robot_position"):
        legacy = importlib.import_module(f"nanobot.agent.tools.{name}")
        runtime = importlib.import_module(f"ai_runtime.robot_tools.{name}")

        assert legacy is runtime
