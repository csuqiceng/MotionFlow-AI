"""Transport-neutral context for one model-requested tool invocation."""

from __future__ import annotations

from contextvars import ContextVar, Token


_CURRENT_TOOL_CALL_ID: ContextVar[str] = ContextVar(
    "agent_tool_call_id",
    default="",
)


def bind_tool_call_id(tool_call_id: str) -> Token[str]:
    """Bind the provider-generated ID for exactly one tool invocation."""
    return _CURRENT_TOOL_CALL_ID.set(str(tool_call_id or ""))


def reset_tool_call_id(token: Token[str]) -> None:
    _CURRENT_TOOL_CALL_ID.reset(token)


def current_tool_call_id() -> str:
    return _CURRENT_TOOL_CALL_ID.get()
