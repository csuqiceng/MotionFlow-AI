"""Stage 2.5 spike: drive AgentLoop through a Web-only bus adapter.

The adapter intentionally knows only the bus event contract.  It does not
import, start, or imitate ChannelManager/BaseChannel.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.outbound_events import StreamDeltaEvent, StreamedResponseEvent
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse, ToolCallRequest


class MinimalWebAdapter:
    """Temporary Web transport adapter used to prove the runtime boundary."""

    def __init__(self, bus: MessageBus, *, session_id: str = "web-session") -> None:
        self.bus = bus
        self.session_id = session_id

    async def submit(self, content: str, *, stream: bool = False) -> None:
        await self.bus.publish_inbound(InboundMessage(
            channel="web",
            sender_id="local-user",
            chat_id=self.session_id,
            content=content,
            metadata={"_wants_stream": stream},
            session_key_override=f"web:{self.session_id}",
        ))

    async def receive(self) -> OutboundMessage:
        return await self.bus.consume_outbound()


def _make_loop(tmp_path: Path) -> tuple[AgentLoop, MessageBus]:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.supports_progress_deltas = True
    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")
    loop.tools.get_definitions = MagicMock(return_value=[])
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]
    return loop, bus


class TestWebRuntimeSpike:
    @pytest.mark.asyncio
    async def test_web_adapter_drives_single_turn_and_stream(self, tmp_path: Path) -> None:
        loop, bus = _make_loop(tmp_path)
        adapter = MinimalWebAdapter(bus)

        async def chat_stream_with_retry(*, on_content_delta, **kwargs):
            await on_content_delta("Hel")
            await on_content_delta("lo")
            return LLMResponse(content="Hello", tool_calls=[])

        loop.provider.chat_stream_with_retry = chat_stream_with_retry
        loop.provider.chat_with_retry = AsyncMock()
        runtime_task = asyncio.create_task(loop.run())
        try:
            await adapter.submit("say hello", stream=True)
            received: list[OutboundMessage] = []
            while not any(isinstance(msg.event, StreamedResponseEvent) for msg in received):
                received.append(await asyncio.wait_for(adapter.receive(), timeout=2))

            assert [msg.content for msg in received if isinstance(msg.event, StreamDeltaEvent)] == ["Hel", "lo"]
            final = next(msg for msg in received if isinstance(msg.event, StreamedResponseEvent))
            assert final.channel == "web"
            assert final.chat_id == "web-session"
            assert final.content == "Hello"
        finally:
            loop.stop()
            await asyncio.wait_for(runtime_task, timeout=2)

    @pytest.mark.asyncio
    async def test_web_adapter_drives_tool_call_without_channel_manager(self, tmp_path: Path) -> None:
        loop, bus = _make_loop(tmp_path)
        adapter = MinimalWebAdapter(bus)
        responses = iter([
            LLMResponse(
                content=None,
                tool_calls=[ToolCallRequest(id="call-1", name="robot_get_status", arguments={})],
            ),
            LLMResponse(content="Robot is ready", tool_calls=[]),
        ])
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda **kwargs: next(responses))
        loop.tools.get_definitions = MagicMock(return_value=[{"type": "function"}])
        loop.tools.prepare_call = MagicMock(return_value=(None, {}, None))
        loop.tools.execute = AsyncMock(return_value="ready")
        runtime_task = asyncio.create_task(loop.run())
        try:
            await adapter.submit("get robot status")
            received = await asyncio.wait_for(adapter.receive(), timeout=2)
            while received.content != "Robot is ready":
                received = await asyncio.wait_for(adapter.receive(), timeout=2)
            assert received.content == "Robot is ready"
            loop.tools.execute.assert_awaited_once_with("robot_get_status", {})
        finally:
            loop.stop()
            await asyncio.wait_for(runtime_task, timeout=2)

    @pytest.mark.asyncio
    async def test_web_adapter_receives_error_and_cancellation(self, tmp_path: Path) -> None:
        loop, bus = _make_loop(tmp_path)
        adapter = MinimalWebAdapter(bus, session_id="cancel")
        started = asyncio.Event()

        async def blocked_process(*args, **kwargs):
            started.set()
            await asyncio.Event().wait()

        loop._process_message = blocked_process  # type: ignore[method-assign]
        runtime_task = asyncio.create_task(loop.run())
        try:
            await adapter.submit("long running task")
            await asyncio.wait_for(started.wait(), timeout=2)
            assert await loop._cancel_active_tasks("web:cancel") == 1

            loop._process_message = AsyncMock(side_effect=RuntimeError("expected spike error"))  # type: ignore[method-assign]
            await adapter.submit("trigger error")
            received = await asyncio.wait_for(adapter.receive(), timeout=2)
            assert received.content == "Sorry, I encountered an error."
        finally:
            loop.stop()
            await asyncio.wait_for(runtime_task, timeout=2)
