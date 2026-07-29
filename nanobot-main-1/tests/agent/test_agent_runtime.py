from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_runtime.contracts import RuntimeEvent, RuntimeRequest as _RuntimeRequest
from ai_runtime.identity import issue_verified_principal
from ai_runtime.providers.nanobot_engine import NanobotEngine
from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse


AgentRuntime = NanobotEngine


def RuntimeRequest(**kwargs):
    raw_actor = str(kwargs.pop("actor_id", "operator"))
    role, separator, actor_id = raw_actor.partition(":")
    if not separator or role not in {"operator", "engineer"}:
        role, actor_id = "operator", raw_actor
    principal = issue_verified_principal(
        actor_id=actor_id, role=role,
        session_id=f"test:{kwargs.get('conversation_id', 'unknown')}",
        auth_source="test",
    )
    return _RuntimeRequest(actor_id=principal.actor, principal=principal, **kwargs)


def _runtime(tmp_path: Path) -> NanobotEngine:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.supports_progress_deltas = True

    async def stream(*, on_content_delta, on_thinking_delta=None, **kwargs):
        if on_thinking_delta is not None:
            await on_thinking_delta("Inspecting the request.")
        await on_content_delta("Hel")
        await on_content_delta("lo")
        return LLMResponse(content="Hello", tool_calls=[])

    provider.chat_stream_with_retry = stream
    provider.chat_with_retry = AsyncMock()
    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")
    loop.tools.get_definitions = MagicMock(return_value=[])
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]
    return AgentRuntime(loop)


@pytest.mark.asyncio
async def test_runtime_start_recovers_interrupted_product_turns() -> None:
    class RecoveringLoop:
        cron_service = None

        def __init__(self) -> None:
            self.recovery_calls = 0

        def recover_interrupted_runtime_requests(self) -> int:
            self.recovery_calls += 1
            return 1

    loop = RecoveringLoop()
    runtime = AgentRuntime(loop)  # type: ignore[arg-type]

    await runtime.start()

    assert loop.recovery_calls == 1
    await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_emits_transport_neutral_events_without_channel_manager(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    await runtime.start()
    try:
        await runtime.submit(RuntimeRequest(
            conversation_id="conversation-1", actor_id="operator", content="hello", request_id="request-1"
        ))
        events = []
        while not any(event.kind == "final" for event in events):
            events.append(await asyncio.wait_for(runtime.next_event(), timeout=2))

        assert [(event.kind, event.payload.get("content")) for event in events if event.kind == "delta"] == [
            ("delta", "Hel"),
            ("delta", "lo"),
        ]
        # The desktop operator UI shows explicit product status and tool
        # progress, never the model's private reasoning stream.
        assert [event for event in events if event.kind.startswith("reasoning")] == []
        assert [event.payload["content"] for event in events if event.kind == "status"] == ["正在分析请求…"]
        final = next(event for event in events if event.kind == "final")
        assert final.conversation_id == "conversation-1"
        assert final.payload == {"content": "Hello"}
        assert final.request_id == "request-1"
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_streams_a_pre_tool_draft(tmp_path: Path) -> None:
    class ToolLoop:
        cron_service = None

        async def process_runtime_request(self, _content: str, **kwargs):
            await kwargs["on_stream"]("我先查询位置 A。")
            await kwargs["on_stream_end"](resuming=True)
            await kwargs["on_progress"](
                "robot_position({\"action\": \"get\"})",
                tool_hint=True,
                tool_events=[{"tool": "robot_position", "phase": "start"}],
            )
            await kwargs["on_stream"]("位置 A 已确认，可以继续执行。")
            await kwargs["on_stream_end"](resuming=False)
            return SimpleNamespace(content="位置 A 已确认，可以继续执行。")

    runtime = AgentRuntime(ToolLoop())
    await runtime.start()
    try:
        await runtime.submit(RuntimeRequest(
            conversation_id="tool-turn", actor_id="operator", content="移动到 A 点"
        ))
        events = []
        while not any(event.kind == "turn_end" for event in events):
            events.append(await asyncio.wait_for(runtime.next_event(), timeout=2))

        assert [event.payload["content"] for event in events if event.kind == "delta"] == [
            "我先查询位置 A。",
            "位置 A 已确认，可以继续执行。"
        ]
        assert [event.payload["resuming"] for event in events if event.kind == "stream_end"] == [True, False]
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_serializes_turns_for_the_same_conversation() -> None:
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    second_started = asyncio.Event()
    calls: list[str] = []

    class SerialLoop:
        cron_service = None

        async def process_runtime_request(self, content: str, **_kwargs):
            calls.append(content)
            if content == "first":
                first_started.set()
                await release_first.wait()
            else:
                second_started.set()
            return SimpleNamespace(content=f"reply:{content}")

    runtime = AgentRuntime(SerialLoop())
    await runtime.start()
    try:
        await runtime.submit(RuntimeRequest(
            conversation_id="shared-chat", actor_id="operator", content="first",
        ))
        await asyncio.wait_for(first_started.wait(), timeout=1)
        await runtime.submit(RuntimeRequest(
            conversation_id="shared-chat", actor_id="operator", content="second",
        ))
        await asyncio.sleep(0)

        assert calls == ["first"]
        assert not second_started.is_set()

        release_first.set()
        events = []
        while sum(event.kind == "turn_end" for event in events) < 2:
            events.append(await asyncio.wait_for(runtime.next_event(), timeout=1))

        assert calls == ["first", "second"]
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_rejects_invalid_conversation_ids_before_bus_delivery(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    await runtime.start()
    try:
        with pytest.raises(ValueError):
            await runtime.submit(RuntimeRequest(conversation_id="", actor_id="operator", content="hello"))
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_event_backpressure_is_bounded_and_keeps_latest_event() -> None:
    loop = MagicMock(cron_service=None)
    runtime = AgentRuntime(loop, event_queue_capacity=2)

    for index in range(5):
        await runtime._publish(RuntimeEvent(
            "conversation-1", "delta", {"content": str(index)}, "request-1",
        ))

    assert runtime._events.qsize() == 2
    assert runtime.dropped_event_count == 3
    assert (await runtime.next_event()).payload["content"] == "3"
    assert (await runtime.next_event()).payload["content"] == "4"


@pytest.mark.asyncio
async def test_delete_conversation_cleans_session_and_session_scoped_history(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    loop = runtime._loop
    session_key = "robot-server:delete-me"
    session = loop.sessions.get_or_create(session_key)
    session.add_message("user", "delete this conversation")
    loop.sessions.save(session)
    loop.context.memory.append_history("conversation summary", session_key=session_key)
    loop.context.memory.append_history("keep this", session_key="robot-server:keep-me")

    result = await runtime.delete_conversation("delete-me")

    assert result["deleted"] is True
    assert result["session_deleted"] is True
    assert result["history_entries_deleted"] == 1
    assert loop.sessions.read_session_file(session_key) is None
    assert [entry["content"] for entry in loop.context.memory._read_entries()] == ["keep this"]
