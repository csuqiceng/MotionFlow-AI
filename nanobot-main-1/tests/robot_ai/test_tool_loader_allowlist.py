from __future__ import annotations

import pytest

pytest.importorskip("loguru")
pytest.importorskip("pydantic")

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.loader import ToolLoader
from nanobot.agent.tools.registry import ToolRegistry


class _FakeConfig:
    def __init__(self, enabled_tools: list[str]) -> None:
        self.enabled_tools = enabled_tools


class _FakeCtx:
    def __init__(self, enabled_tools: list[str]) -> None:
        self.config = _FakeConfig(enabled_tools)


@tool_parameters({"type": "object", "properties": {}, "required": [], "additionalProperties": True})
class _RobotLike(Tool):
    @property
    def name(self) -> str: return "robot_arm"
    @property
    def description(self) -> str: return "r"
    @property
    def read_only(self) -> bool: return True
    async def execute(self, **kwargs): return "ok"


@tool_parameters({"type": "object", "properties": {}, "required": [], "additionalProperties": True})
class _ExecLike(Tool):
    @property
    def name(self) -> str: return "exec"
    @property
    def description(self) -> str: return "e"
    @property
    def read_only(self) -> bool: return False
    async def execute(self, **kwargs): return "ok"


def test_loader_filters_builtins_by_enabled_tools() -> None:
    loader = ToolLoader(test_classes=[_RobotLike, _ExecLike])
    registry = ToolRegistry()
    ctx = _FakeCtx(["robot_arm", "robot_flow"])
    registered = loader.load(ctx, registry)
    assert "robot_arm" in registered
    assert "exec" not in registered


def test_loader_wildcard_keeps_all() -> None:
    loader = ToolLoader(test_classes=[_RobotLike, _ExecLike])
    registry = ToolRegistry()
    ctx = _FakeCtx(["*"])
    registered = loader.load(ctx, registry)
    assert "robot_arm" in registered
    assert "exec" in registered
