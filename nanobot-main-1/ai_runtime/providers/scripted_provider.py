"""Minimal deterministic second Provider used for contract and integration PoCs."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from ai_runtime.engine_contract import AgentEngine, AgentEvent, AgentRequest
from ai_runtime.provider_config import AiProviderConfig


class ScriptedAgentEngine:
    def __init__(self, *, event_queue_capacity: int = 512) -> None:
        self._started = False
        if not 1 <= int(event_queue_capacity) <= 100_000:
            raise ValueError("event_queue_capacity must be within 1-100000")
        self._event_queue_capacity = int(event_queue_capacity)
        self._events: asyncio.Queue[AgentEvent] = asyncio.Queue(maxsize=self._event_queue_capacity)
        self._subscribers: set[asyncio.Queue[AgentEvent]] = set()
        self._dropped_event_count = 0
        self._active: dict[str, set[asyncio.Task[None]]] = {}
        self._sessions: dict[str, list[dict[str, str]]] = {}

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False
        tasks = [task for group in self._active.values() for task in group]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._active.clear()

    async def submit(self, request: AgentRequest) -> None:
        if not self._started:
            raise RuntimeError("AgentEngine is not started")
        task = asyncio.create_task(self._run_turn(request))
        self._active.setdefault(request.conversation_id, set()).add(task)

    async def cancel(self, conversation_id: str) -> int:
        tasks = self._active.get(conversation_id, set())
        return sum(1 for task in tasks if not task.done() and task.cancel())

    async def delete_conversation(self, conversation_id: str) -> dict[str, int | bool]:
        deleted = self._sessions.pop(conversation_id, None) is not None
        return {
            "deleted": True,
            "session_deleted": deleted,
            "cancelled_turns": 0,
            "automations_deleted": 0,
            "history_entries_deleted": 0,
        }

    async def subscribe(self) -> AsyncIterator[AgentEvent]:
        queue: asyncio.Queue[AgentEvent] = asyncio.Queue(maxsize=self._event_queue_capacity)
        self._subscribers.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers.discard(queue)

    async def check_ai_connectivity(self) -> None:
        if not self._started:
            raise RuntimeError("AgentEngine is not started")

    def list_sessions(self) -> list[dict[str, Any]]:
        return [
            {"key": conversation_id, "message_count": len(messages)}
            for conversation_id, messages in self._sessions.items()
        ]

    def read_session(self, conversation_id: str) -> dict[str, Any] | None:
        messages = self._sessions.get(conversation_id)
        return None if messages is None else {
            "key": conversation_id, "messages": [dict(item) for item in messages],
        }

    @property
    def cron_service(self) -> None:
        return None

    @property
    def dropped_event_count(self) -> int:
        return self._dropped_event_count

    async def _run_turn(self, request: AgentRequest) -> None:
        task = asyncio.current_task()
        try:
            self._sessions.setdefault(request.conversation_id, []).append({
                "role": "user", "content": request.content,
            })
            await self._publish(AgentEvent(
                request.conversation_id,
                "final",
                {"content": f"scripted:{request.content}"},
                request.request_id,
            ))
        except asyncio.CancelledError:
            await self._publish(AgentEvent(
                request.conversation_id, "error", {"message": "cancelled"}, request.request_id,
            ))
            raise
        finally:
            await self._publish(AgentEvent(
                request.conversation_id, "turn_end", {"latency_ms": 0}, request.request_id,
            ))
            if task is not None:
                group = self._active.get(request.conversation_id)
                if group is not None:
                    group.discard(task)
                    if not group:
                        self._active.pop(request.conversation_id, None)

    async def _publish(self, event: AgentEvent) -> None:
        self._offer(self._events, event)
        for subscriber in tuple(self._subscribers):
            self._offer(subscriber, event)

    def _offer(self, queue: asyncio.Queue[AgentEvent], event: AgentEvent) -> None:
        if queue.full():
            try:
                queue.get_nowait()
                self._dropped_event_count += 1
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(event)


class ScriptedProvider:
    engine_id = "scripted"

    def create_engine(
        self,
        config: AiProviderConfig,
        *,
        config_path: Path | None = None,
    ) -> AgentEngine:
        del config_path
        if config.engine_id != self.engine_id:
            raise ValueError(f"Unsupported AI engine: {config.engine_id}")
        return ScriptedAgentEngine()
