"""Stable contracts for product tools independent of a specific agent SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ai_runtime.identity import VerifiedPrincipal


class GovernedSideEffectTool:
    """Marker for reviewed Application-only side-effect Tool adapters.

    ProductToolRuntime rejects arbitrary non-read implementations.  Concrete
    product adapters inherit this marker and additionally expose an explicit
    canonical-effect contract.
    """


@dataclass(frozen=True)
class ToolContext:
    """Request metadata made available to a product tool adapter."""

    actor: str = ""
    session_key: str = ""
    principal: VerifiedPrincipal | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    on_progress: Any | None = None

    @property
    def verified_actor(self) -> str:
        return self.principal.actor if self.principal is not None else "untrusted:unknown"


@dataclass(frozen=True)
class ToolInvocation:
    """One requested tool call using the stable public tool name and JSON data."""

    name: str
    parameters: dict[str, Any] = field(default_factory=dict)
    invocation_id: str = ""
    idempotency_key: str = ""


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

    def to_contract_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "state": self.state,
            "message": self.message,
            "data": dict(self.data),
            "errors": [dict(error) for error in self.errors],
        }


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
