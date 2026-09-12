"""Stable Agent Engine protocol consumed by product servers and transports."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from ai_runtime.contracts import RuntimeEvent, RuntimeRequest


AgentRequest = RuntimeRequest
AgentEvent = RuntimeEvent


@runtime_checkable
class AgentEngine(Protocol):
    """Transport-neutral agent lifecycle, turns, events and session access."""

    async def start(self) -> None:
        ...

    async def stop(self) -> None:
        ...

    async def submit(self, request: AgentRequest) -> None:
        ...

    async def cancel(self, conversation_id: str) -> int:
        ...

    async def delete_conversation(self, conversation_id: str) -> dict[str, int | bool]:
        ...

    async def subscribe(self) -> AsyncIterator[AgentEvent]:
        ...

    async def check_ai_connectivity(self) -> None:
        ...

    def list_sessions(self) -> list[dict[str, Any]]:
        ...

    def read_session(self, conversation_id: str) -> dict[str, Any] | None:
        ...

    @property
    def cron_service(self) -> Any | None:
        ...
