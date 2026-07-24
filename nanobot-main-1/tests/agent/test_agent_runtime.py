from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_runtime.agent_runtime import AgentRuntime, RuntimeRequest, _visible_reasoning
from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse


def _runtime(tmp_path: Path) -> AgentRuntime:
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


def test_reasoning_hides_runner_injected_unavailable_tool_recovery() -> None:
    raw = (
        "Checking the controller.\n\n"
        "Error: Tool 'read_file' not found. Available: robot_arm, robot_flow\n\n"
        "[Analyze the error above and try a different approach.]\n\n"
        "I will use the robot status tool instead."
    )

    assert _visible_reasoning(raw) == (
        "Checking the controller.\n\nI will use the robot status tool instead."
    )


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
            ("delta", "Hel"), ("delta", "lo"),
        ]
        assert [(event.kind, event.payload.get("content")) for event in events if event.kind.startswith("reasoning")] == [
            ("reasoning_delta", "Inspecting the request."),
            ("reasoning_end", None),
        ]
        final = next(event for event in events if event.kind == "final")
        assert final.conversation_id == "conversation-1"
        assert final.payload == {"content": "Hello"}
        assert final.request_id == "request-1"
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
