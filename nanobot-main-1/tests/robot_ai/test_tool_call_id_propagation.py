from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_runtime.robot_tools.loader import NanobotToolRuntimeAdapter
from ai_runtime.tool_catalog import PRODUCT_TOOL_MANIFESTS_BY_ID
from ai_runtime.tool_contracts import ToolResult
from nanobot.agent.runner import AgentRunSpec, AgentRunner
from nanobot.agent.tools.context import RequestContext
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.providers.base import ToolCallRequest


def _legacy_tool(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        description=name,
        parameters={"type": "object", "properties": {}, "required": []},
        cast_params=lambda params: params,
        validate_params=lambda params: [],
        to_schema=lambda: {
            "type": "function",
            "function": {
                "name": name,
                "description": name,
                "parameters": {"type": "object", "properties": {}},
            },
        },
    )


@pytest.mark.asyncio
async def test_runner_propagates_tool_call_id_to_product_runtime_idempotency_key():
    runtime = MagicMock()
    runtime.execute = AsyncMock(return_value=ToolResult.success(state="ok"))
    adapter = NanobotToolRuntimeAdapter(
        runtime,
        _legacy_tool("robot_arm"),
        PRODUCT_TOOL_MANIFESTS_BY_ID["robot_arm"],
    )
    adapter.set_context(RequestContext(channel="test", chat_id="chat"))
    registry = ToolRegistry()
    registry.register(adapter)

    await AgentRunner(MagicMock())._execute_tools(
        AgentRunSpec(
            initial_messages=[], tools=registry, model="test-model", max_iterations=1,
            max_tool_result_chars=16_000,
        ),
        [ToolCallRequest(id="call-runtime-1", name="robot_arm", arguments={})],
        {},
        {},
    )

    invocation = runtime.execute.await_args.args[1]
    assert invocation.invocation_id == "call-runtime-1"
    assert invocation.idempotency_key == "call-runtime-1"


def test_read_only_robot_lookups_do_not_require_request_idempotency():
    assert PRODUCT_TOOL_MANIFESTS_BY_ID["robot_knowledge"].idempotency == "none"
    assert PRODUCT_TOOL_MANIFESTS_BY_ID["robot_position"].idempotency == "none"
