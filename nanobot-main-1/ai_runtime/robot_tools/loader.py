"""Compatibility adapters from the existing Nanobot tool API to tool contracts."""

from __future__ import annotations

import inspect
import json
from copy import deepcopy
from typing import Any

from ai_runtime.tool_contracts import ToolContext, ToolInvocation, ToolResult


class LegacyRobotToolAdapter:
    """Expose a legacy ``execute(**kwargs)`` tool through the stable contract."""

    def __init__(self, legacy_tool: Any) -> None:
        self._legacy_tool = legacy_tool

    @property
    def name(self) -> str:
        return str(self._legacy_tool.name)

    @property
    def parameters(self) -> dict[str, Any]:
        return deepcopy(dict(self._legacy_tool.parameters))

    async def execute(self, context: ToolContext, invocation: ToolInvocation) -> ToolResult:
        if invocation.name != self.name:
            return ToolResult.failure(
                state="tool_name_mismatch",
                message=f"Invocation for '{invocation.name}' cannot execute '{self.name}'.",
                errors=[{"code": "tool_name_mismatch"}],
            )
        result = self._legacy_tool.execute(**dict(invocation.parameters))
        if inspect.isawaitable(result):
            result = await result
        return _structured_result(result)


def adapt_legacy_robot_tool(legacy_tool: Any) -> LegacyRobotToolAdapter:
    """Wrap one existing robot tool without changing its schema or result wire format."""
    return LegacyRobotToolAdapter(legacy_tool)


def _structured_result(result: Any) -> ToolResult:
    if isinstance(result, dict):
        payload = result
    else:
        try:
            payload = json.loads(str(result))
        except (TypeError, ValueError, json.JSONDecodeError):
            return ToolResult.failure(
                state="tool_result_invalid",
                message="Legacy tool returned a non-JSON result.",
                errors=[{"code": "tool_result_invalid"}],
            )
    if not isinstance(payload, dict):
        return ToolResult.failure(
            state="tool_result_invalid",
            message="Legacy tool returned a non-object JSON result.",
            errors=[{"code": "tool_result_invalid"}],
        )
    raw_errors = payload.get("errors") or []
    errors = [dict(error) for error in raw_errors if isinstance(error, dict)]
    raw_data = payload.get("data") or {}
    data = dict(raw_data) if isinstance(raw_data, dict) else {}
    return ToolResult(
        ok=bool(payload.get("ok")),
        state=str(payload.get("state") or "tool_result_missing_state"),
        message=str(payload.get("message") or ""),
        data=data,
        errors=errors,
    )
