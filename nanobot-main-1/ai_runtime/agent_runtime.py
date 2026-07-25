"""Transport-neutral façade around the retained agent engine."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

from ai_runtime.contracts import RuntimeEvent, RuntimeRequest, validate_conversation_id
from nanobot.agent.loop import AgentLoop


class AgentRuntime:
    """Publish runtime events without exposing a chat transport to callers."""

    def __init__(self, loop: AgentLoop) -> None:
        # The retained engine owns its private message bus.  Runtime callers
        # interact solely through direct turns and RuntimeEvent callbacks.
        self._loop = loop
        self._started = False
        self._events: asyncio.Queue[RuntimeEvent] = asyncio.Queue()
        self._subscribers: set[asyncio.Queue[RuntimeEvent]] = set()
        self._active_turns: dict[str, set[asyncio.Task[None]]] = {}

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        cron_service = self._loop.cron_service
        if cron_service is not None:
            await cron_service.start()

    async def stop(self) -> None:
        self._started = False
        cron_service = self._loop.cron_service
        if cron_service is not None:
            cron_service.stop()
        active = [task for tasks in self._active_turns.values() for task in tasks]
        self._active_turns.clear()
        for task in active:
            task.cancel()
        if active:
            await asyncio.gather(*active, return_exceptions=True)

    async def submit(self, request: RuntimeRequest) -> None:
        if not self._started:
            raise RuntimeError("AgentRuntime is not started")
        conversation_id = validate_conversation_id(request.conversation_id)
        task = asyncio.create_task(self._run_turn(request, conversation_id))
        self._active_turns.setdefault(conversation_id, set()).add(task)

    async def cancel(self, conversation_id: str) -> int:
        conversation_id = validate_conversation_id(conversation_id)
        tasks = self._active_turns.get(conversation_id, set())
        cancelled = sum(1 for task in tasks if not task.done() and task.cancel())
        return cancelled

    async def delete_conversation(self, conversation_id: str) -> dict[str, int | bool]:
        """Erase every local artifact owned by one product conversation.

        A turn is awaited after cancellation before its session file is removed:
        otherwise the turn's ``finally`` block can save the conversation again
        and make a deleted chat reappear in the sidebar.
        """
        conversation_id = validate_conversation_id(conversation_id)
        active = tuple(self._active_turns.get(conversation_id, set()))
        cancelled = sum(1 for task in active if not task.done() and task.cancel())
        if active:
            await asyncio.gather(*active, return_exceptions=True)

        session_key = f"robot-server:{conversation_id}"
        automations_deleted = 0
        cron_service = self._loop.cron_service
        if cron_service is not None:
            for job in cron_service.list_bound_cron_jobs_for_session(session_key):
                if cron_service.remove_job(job.id) == "removed":
                    automations_deleted += 1

        history_entries_deleted = self._loop.context.memory.remove_history_for_session(session_key)
        session_deleted = self._loop.sessions.delete_session(session_key)
        # Deletion is idempotent.  In particular, a just-created optimistic
        # empty chat has no file yet, but the caller must still remove its row.
        return {
            "deleted": True,
            "session_deleted": session_deleted,
            "cancelled_turns": cancelled,
            "automations_deleted": automations_deleted,
            "history_entries_deleted": history_entries_deleted,
        }

    async def events(self) -> AsyncIterator[RuntimeEvent]:
        """Consume the legacy single-reader stream (kept for programmatic use)."""
        while True:
            yield await self._events.get()

    async def subscribe(self) -> AsyncIterator[RuntimeEvent]:
        """Subscribe without one WebSocket client stealing another's events."""
        queue: asyncio.Queue[RuntimeEvent] = asyncio.Queue()
        self._subscribers.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers.discard(queue)

    async def next_event(self) -> RuntimeEvent:
        return await self._events.get()

    async def check_ai_connectivity(self) -> None:
        """Perform the same minimal provider check formerly used by the WebUI.

        This intentionally bypasses sessions, tools and the robot platform.  It
        is only used by the login-page diagnostics, so it must not create a
        conversation or cause any physical side effect.
        """
        if not self._started:
            raise RuntimeError("AgentRuntime is not started")
        response = await self._loop.provider.chat(
            [{"role": "user", "content": "health"}],
            max_tokens=1,
            temperature=0,
        )
        if getattr(response, "finish_reason", None) == "error":
            raise RuntimeError("provider returned an error")

    def list_sessions(self) -> list[dict[str, Any]]:
        """Return local conversation summaries for the retained WebUI sidebar.

        This exposes the agent engine's persisted session store, not any chat
        channel or gateway state.
        """
        return self._loop.sessions.list_sessions()

    def read_session(self, conversation_id: str) -> dict[str, Any] | None:
        """Read one transport-neutral conversation from the local session store."""
        conversation_id = validate_conversation_id(conversation_id)
        return self._loop.sessions.read_session_file(f"robot-server:{conversation_id}")

    @property
    def cron_service(self) -> Any | None:
        """Expose the local scheduler, never a channel or gateway service."""
        return self._loop.cron_service

    async def _publish(self, event: RuntimeEvent) -> None:
        await self._events.put(event)
        for subscriber in tuple(self._subscribers):
            await subscriber.put(event)

    async def _run_turn(self, request: RuntimeRequest, conversation_id: str) -> None:
        task = asyncio.current_task()
        started_at = time.monotonic()

        async def publish_status(content: str) -> None:
            """Expose a short product status, never model reasoning."""
            await self._publish(RuntimeEvent(
                conversation_id, "status", {"content": content}, request.request_id
            ))

        async def on_stream(content: str) -> None:
            await self._publish(RuntimeEvent(
                conversation_id, "delta", {"content": content}, request.request_id
            ))

        async def on_stream_end(*, resuming: bool = False) -> None:
            await self._publish(RuntimeEvent(
                conversation_id, "stream_end", {"resuming": resuming}, request.request_id
            ))

        async def on_progress(content: str, **metadata: Any) -> None:
            # Raw model reasoning is neither a control action nor an operator
            # facing status.  It remains out of the product conversation.
            if metadata.get("reasoning"):
                return
            if metadata.get("reasoning_end"):
                return
            if metadata.get("file_edit_events"):
                await self._publish(RuntimeEvent(
                    conversation_id,
                    "file_edit",
                    {"edits": metadata["file_edit_events"]},
                    request.request_id,
                ))
                return
            payload: dict[str, Any] = {"content": content}
            for key in ("tool_hint", "tool_events"):
                value = metadata.get(key)
                if value not in (None, False, [], ""):
                    payload[key] = value
            await self._publish(RuntimeEvent(
                conversation_id, "tool_progress", payload, request.request_id
            ))

        try:
            # Keep the original single-pass AgentLoop stream.  A second model
            # pass used to turn tool output into a final answer, but doubled
            # time-to-first-token and overall latency for every operator turn.
            # The UI turns only ``stream_end(resuming=True)`` segments into
            # compact activity rows, so this does not expose raw reasoning.
            await publish_status("正在分析请求…")
            response = await self._loop.process_runtime_request(
                request.content,
                conversation_id=conversation_id,
                actor_id=request.actor_id,
                attachments=list(request.attachments),
                on_progress=on_progress,
                on_stream=on_stream if request.stream else None,
                on_stream_end=on_stream_end if request.stream else None,
            )
            await self._publish(RuntimeEvent(
                conversation_id,
                "final",
                {"content": response.content if response is not None else ""},
                request.request_id,
            ))
        except asyncio.CancelledError:
            await self._publish(RuntimeEvent(
                conversation_id, "error", {"message": "cancelled"}, request.request_id
            ))
            raise
        except Exception as exc:
            await self._publish(RuntimeEvent(
                conversation_id, "error", {"message": str(exc)}, request.request_id
            ))
        finally:
            await self._publish(RuntimeEvent(
                conversation_id,
                "turn_end",
                {"latency_ms": max(0, round((time.monotonic() - started_at) * 1000))},
                request.request_id,
            ))
            if task is not None:
                tasks = self._active_turns.get(conversation_id)
                if tasks is not None:
                    tasks.discard(task)
                    if not tasks:
                        self._active_turns.pop(conversation_id, None)
