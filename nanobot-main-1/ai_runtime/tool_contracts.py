"""Stable contracts for product tools independent of a specific agent SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolContext:
    """Request metadata made available to a product tool adapter."""

    actor: str = ""
    session_key: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    on_progress: Any | None = None


@dataclass(frozen=True)
class ToolInvocation:
    """One requested tool call using the stable public tool name and JSON data."""

    name: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    """Structured, SDK-neutral result returned by a tool adapter."""

    ok: bool
    state: str
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def success(
        cls,
        *,
        state: str,
        message: str = "",
        data: dict[str, Any] | None = None,
    ) -> "ToolResult":
        return cls(ok=True, state=state, message=message, data=dict(data or {}))

    @classmethod
    def failure(
        cls,
        *,
        state: str,
        message: str,
        errors: list[dict[str, Any]] | None = None,
        data: dict[str, Any] | None = None,
    ) -> "ToolResult":
        return cls(
            ok=False,
            state=state,
            message=message,
            data=dict(data or {}),
            errors=list(errors or []),
        )


class Tool(Protocol):
    """Minimal runtime contract for a product capability."""

    @property
    def name(self) -> str:
        ...

    @property
    def parameters(self) -> dict[str, Any]:
        ...

    async def execute(self, context: ToolContext, invocation: ToolInvocation) -> ToolResult:
        ...
