"""Integration tests for the WebSocket channel using WsTestClient.

Complements the unit/lightweight tests in test_websocket_channel.py by covering
multi-client scenarios, edge cases, and realistic usage patterns.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import websockets
from ws_test_client import WsTestClient, issue_token, issue_token_ok

from nanobot.bus.events import OutboundMessage
from nanobot.bus.outbound_events import ProgressEvent
from nanobot.channels.websocket import WebSocketChannel, WebSocketConfig
from nanobot.session.manager import SessionManager
from nanobot.webui.gateway_services import build_gateway_services


def _ch(bus: Any, port: int, *, tmp_path: Path | None = None, **kw: Any) -> WebSocketChannel:
    cfg: dict[str, Any] = {
        "enabled": True,
        "allowFrom": ["*"],
        "host": "127.0.0.1",
        "port": port,
        "path": "/",
        "websocketRequiresToken": False,
    }
    cfg.update(kw)
    parsed = WebSocketConfig.model_validate(cfg)
    session_manager = SessionManager(tmp_path / "sessions") if tmp_path is not None else None
    gateway = build_gateway_services(
        config=parsed,
        bus=bus,
        session_manager=session_manager,
        static_dist_path=None,
        workspace_path=Path.cwd(),
        default_restrict_to_workspace=False,
        runtime_model_name=None,
        runtime_surface="browser",
        runtime_capabilities_overrides=None,
    )
    return WebSocketChannel(cfg, bus, gateway=gateway, unified_session=False)


def _issue_user_token(*, role: str = "engineer", user_id: str = "e2e") -> str:
    from robot_ai.library.auth import get_user_session_store

    return get_user_session_store().issue(
        {"user_id": user_id, "username": user_id, "role": role}
    )


async def _auth(client: WsTestClient, *, user_id: str = "e2e") -> None:
    """Drive a client through the slice ② auth gate (send auth, await auth_ok)."""
    tok = _issue_user_token(user_id=user_id)
    await client.send_json({"type": "auth", "user_token": tok})
    auth_ok = await client.recv()
    assert auth_ok.event == "auth_ok", auth_ok.raw


async def _new_chat(client: WsTestClient) -> str:
    """Send ``new_chat`` and return the chat_id from the ``attached`` event.

    Drains the incidental ``session_updated`` frame the server emits right
    after ``attached`` so the caller's next recv() sees only its own frames.
    """
    await client.send_json({"type": "new_chat"})
    chat_id: str | None = None
    while True:
        msg = await client.recv()
        if msg.event == "attached":
            chat_id = msg.chat_id
        elif msg.event == "session_updated" and chat_id is not None:
            return chat_id


@pytest.fixture()
def bus() -> MagicMock:
    b = MagicMock()
    b.publish_inbound = AsyncMock()
    return b


# -- Connection basics ----------------------------------------------------


@pytest.mark.asyncio
async def test_ready_event_fields(bus: MagicMock) -> None:
    ch = _ch(bus, 29901)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29901/", client_id="c1") as c:
            r = await c.recv_ready()
            assert r.event == "ready"
            # slice ②: ready no longer carries a default chat_id (no chat is
            # created until an explicit new_chat). client_id is still echoed.
            assert r.chat_id is None
            assert r.client_id == "c1"
    finally:
        await ch.stop()
        await t


@pytest.mark.asyncio
async def test_anonymous_client_gets_generated_id(bus: MagicMock) -> None:
    ch = _ch(bus, 29902)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29902/", client_id="") as c:
            r = await c.recv_ready()
            assert r.client_id.startswith("anon-")
    finally:
        await ch.stop()
        await t


@pytest.mark.asyncio
async def test_each_connection_unique_chat_id(bus: MagicMock, tmp_path) -> None:
    """slice ②: no default chat on connect; each connection's explicit new_chat
    yields a distinct chat_id (the uniqueness property this test has always
    cared about)."""
    ch = _ch(bus, 29903, tmp_path=tmp_path)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29903/", client_id="a") as c1:
            async with WsTestClient("ws://127.0.0.1:29903/", client_id="b") as c2:
                await c1.recv_ready()
                await c2.recv_ready()
                await _auth(c1, user_id="a")
                await _auth(c2, user_id="b")
                chat_a = await _new_chat(c1)
                chat_b = await _new_chat(c2)
                assert chat_a != chat_b
    finally:
        await ch.stop()
        await t


# -- Inbound messages (client -> server) ----------------------------------


@pytest.mark.asyncio
async def test_plain_text(bus: MagicMock, tmp_path) -> None:
    """slice ②: legacy plain-text routing was removed; the surviving intent —
    inbound content reaches the agent — is exercised via a typed message
    envelope on an explicit chat after auth."""
    ch = _ch(bus, 29904, tmp_path=tmp_path)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29904/", client_id="p") as c:
            await c.recv_ready()
            await _auth(c)
            cid = await _new_chat(c)
            await c.send_json({"type": "message", "chat_id": cid, "content": "hello world"})
            await asyncio.sleep(0.1)
            inbound = bus.publish_inbound.call_args[0][0]
            assert inbound.content == "hello world"
            assert inbound.sender_id == "p"
    finally:
        await ch.stop()
        await t


@pytest.mark.asyncio
async def test_json_content_field(bus: MagicMock, tmp_path) -> None:
    ch = _ch(bus, 29905, tmp_path=tmp_path)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29905/", client_id="j") as c:
            await c.recv_ready()
            await _auth(c)
            cid = await _new_chat(c)
            await c.send_json({"type": "message", "chat_id": cid, "content": "structured"})
            await asyncio.sleep(0.1)
            assert bus.publish_inbound.call_args[0][0].content == "structured"
    finally:
        await ch.stop()
        await t


@pytest.mark.asyncio
async def test_json_text_and_message_fields(bus: MagicMock, tmp_path) -> None:
    """slice ② removed the legacy ``{text}``/``{message}`` field aliases — only
    typed ``message`` envelopes route. The surviving intent (two distinct
    inbound contents on the same chat both reach the agent in order) is
    exercised here."""
    ch = _ch(bus, 29906, tmp_path=tmp_path)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29906/", client_id="x") as c:
            await c.recv_ready()
            await _auth(c)
            cid = await _new_chat(c)
            await c.send_json({"type": "message", "chat_id": cid, "content": "first"})
            await asyncio.sleep(0.1)
            assert bus.publish_inbound.call_args[0][0].content == "first"
            await c.send_json({"type": "message", "chat_id": cid, "content": "second"})
            await asyncio.sleep(0.1)
            assert bus.publish_inbound.call_args[0][0].content == "second"
    finally:
        await ch.stop()
        await t


@pytest.mark.asyncio
async def test_empty_payload_ignored(bus: MagicMock) -> None:
    ch = _ch(bus, 29907)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29907/", client_id="e") as c:
            await c.recv_ready()
            await c.send_text("   ")
            await c.send_json({})
            await asyncio.sleep(0.1)
            bus.publish_inbound.assert_not_awaited()
    finally:
        await ch.stop()
        await t


@pytest.mark.asyncio
async def test_messages_preserve_order(bus: MagicMock, tmp_path) -> None:
    ch = _ch(bus, 29908, tmp_path=tmp_path)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29908/", client_id="o") as c:
            await c.recv_ready()
            await _auth(c)
            cid = await _new_chat(c)
            for i in range(5):
                await c.send_json({"type": "message", "chat_id": cid, "content": f"msg-{i}"})
            await asyncio.sleep(0.2)
            contents = [call[0][0].content for call in bus.publish_inbound.call_args_list]
            assert contents == [f"msg-{i}" for i in range(5)]
    finally:
        await ch.stop()
        await t


# -- Outbound messages (server -> client) ---------------------------------


@pytest.mark.asyncio
async def test_server_send_message(bus: MagicMock, tmp_path) -> None:
    ch = _ch(bus, 29909, tmp_path=tmp_path)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29909/", client_id="r") as c:
            await c.recv_ready()
            await _auth(c)
            cid = await _new_chat(c)
            await ch.send(OutboundMessage(
                channel="websocket", chat_id=cid, content="reply",
            ))
            msg = await c.recv_message()
            assert msg.text == "reply"
    finally:
        await ch.stop()
        await t


@pytest.mark.asyncio
async def test_server_send_tags_tool_hint_with_kind(bus: MagicMock, tmp_path) -> None:
    """Tool-hint progress events surface as ``kind: "tool_hint"``."""
    ch = _ch(bus, 29919, tmp_path=tmp_path)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29919/", client_id="h") as c:
            await c.recv_ready()
            await _auth(c)
            cid = await _new_chat(c)
            # Plain reply: no "kind" field.
            await ch.send(OutboundMessage(
                channel="websocket", chat_id=cid, content="hi",
            ))
            plain = await c.recv_message()
            assert plain.raw.get("kind") is None

            # Tool-hint breadcrumb: kind == "tool_hint".
            await ch.send(OutboundMessage(
                channel="websocket", chat_id=cid,
                content='weather("get")',
                event=ProgressEvent(content='weather("get")', tool_hint=True),
            ))
            hint = await c.recv_message()
            assert hint.raw.get("kind") == "tool_hint"
            assert hint.text == 'weather("get")'

            # Generic progress (non-tool-hint) gets the softer "progress" label.
            await ch.send(OutboundMessage(
                channel="websocket", chat_id=cid,
                content="thinking…",
                event=ProgressEvent(content="thinking…"),
            ))
            prog = await c.recv_message()
            assert prog.raw.get("kind") == "progress"
    finally:
        await ch.stop()
        await t


@pytest.mark.asyncio
async def test_server_send_with_media_and_reply(bus: MagicMock, tmp_path) -> None:
    ch = _ch(bus, 29910, tmp_path=tmp_path)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29910/", client_id="m") as c:
            await c.recv_ready()
            await _auth(c)
            cid = await _new_chat(c)
            await ch.send(OutboundMessage(
                channel="websocket", chat_id=cid, content="img",
                media=["/tmp/a.png"], reply_to="m1",
            ))
            msg = await c.recv_message()
            assert msg.text == "img"
            assert msg.media == ["/tmp/a.png"]
            assert msg.reply_to == "m1"
    finally:
        await ch.stop()
        await t


# -- Streaming ------------------------------------------------------------


@pytest.mark.asyncio
async def test_streaming_deltas_and_end(bus: MagicMock, tmp_path) -> None:
    ch = _ch(bus, 29911, streaming=True, tmp_path=tmp_path)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29911/", client_id="s") as c:
            await c.recv_ready()
            await _auth(c)
            cid = await _new_chat(c)
            for part in ("Hello", " ", "world", "!"):
                await ch.send_delta(cid, part, stream_id="s1")
            await ch.send_delta(cid, "", stream_id="s1", stream_end=True)

            msgs = await c.collect_stream()
            deltas = [m for m in msgs if m.event == "delta"]
            assert "".join(d.text for d in deltas) == "Hello world!"
            ends = [m for m in msgs if m.event == "stream_end"]
            assert len(ends) == 1
    finally:
        await ch.stop()
        await t


@pytest.mark.asyncio
async def test_interleaved_streams(bus: MagicMock, tmp_path) -> None:
    ch = _ch(bus, 29912, streaming=True, tmp_path=tmp_path)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29912/", client_id="i") as c:
            await c.recv_ready()
            await _auth(c)
            cid = await _new_chat(c)
            await ch.send_delta(cid, "A1", stream_id="sa")
            await ch.send_delta(cid, "B1", stream_id="sb")
            await ch.send_delta(cid, "A2", stream_id="sa")
            await ch.send_delta(cid, "", stream_id="sa", stream_end=True)
            await ch.send_delta(cid, "B2", stream_id="sb")
            await ch.send_delta(cid, "", stream_id="sb", stream_end=True)

            msgs = await c.recv_n(6)
            sa = "".join(m.text for m in msgs if m.event == "delta" and m.stream_id == "sa")
            sb = "".join(m.text for m in msgs if m.event == "delta" and m.stream_id == "sb")
            assert sa == "A1A2"
            assert sb == "B1B2"
    finally:
        await ch.stop()
        await t


# -- Multi-client ---------------------------------------------------------


@pytest.mark.asyncio
async def test_independent_sessions(bus: MagicMock, tmp_path) -> None:
    ch = _ch(bus, 29913, tmp_path=tmp_path)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29913/", client_id="u1") as c1:
            async with WsTestClient("ws://127.0.0.1:29913/", client_id="u2") as c2:
                await c1.recv_ready()
                await c2.recv_ready()
                await _auth(c1, user_id="u1")
                await _auth(c2, user_id="u2")
                cid1 = await _new_chat(c1)
                cid2 = await _new_chat(c2)
                await ch.send(OutboundMessage(
                    channel="websocket", chat_id=cid1, content="for-u1",
                ))
                assert (await c1.recv_message()).text == "for-u1"
                await ch.send(OutboundMessage(
                    channel="websocket", chat_id=cid2, content="for-u2",
                ))
                assert (await c2.recv_message()).text == "for-u2"
    finally:
        await ch.stop()
        await t


@pytest.mark.asyncio
async def test_disconnected_client_cleanup(bus: MagicMock, tmp_path) -> None:
    ch = _ch(bus, 29914, tmp_path=tmp_path)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29914/", client_id="tmp") as c:
            await c.recv_ready()
            await _auth(c)
            chat_id = await _new_chat(c)
            assert chat_id in ch._subs
        # disconnected
        await asyncio.sleep(0.1)
        await ch.send(OutboundMessage(
            channel="websocket", chat_id=chat_id, content="orphan",
        ))
        assert chat_id not in ch._subs
    finally:
        await ch.stop()
        await t


# -- Authentication -------------------------------------------------------


@pytest.mark.asyncio
async def test_static_token_accepted(bus: MagicMock) -> None:
    ch = _ch(bus, 29915, token="secret")
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29915/", client_id="a", token="secret") as c:
            assert (await c.recv_ready()).client_id == "a"
    finally:
        await ch.stop()
        await t


@pytest.mark.asyncio
async def test_static_token_rejected(bus: MagicMock) -> None:
    ch = _ch(bus, 29916, token="correct")
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        with pytest.raises(websockets.exceptions.InvalidStatus) as exc:
            async with WsTestClient("ws://127.0.0.1:29916/", client_id="b", token="wrong"):
                pass
        assert exc.value.response.status_code == 401
    finally:
        await ch.stop()
        await t


@pytest.mark.asyncio
async def test_token_issue_full_flow(bus: MagicMock) -> None:
    ch = _ch(bus, 29917, path="/ws",
             tokenIssuePath="/auth/token", tokenIssueSecret="s",
             websocketRequiresToken=True)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        # no secret -> 401
        _, status = await issue_token(port=29917, issue_path="/auth/token")
        assert status == 401

        # with secret -> token
        token = await issue_token_ok(port=29917, issue_path="/auth/token", secret="s")

        # no token -> 401
        with pytest.raises(websockets.exceptions.InvalidStatus) as exc:
            async with WsTestClient("ws://127.0.0.1:29917/ws", client_id="x"):
                pass
        assert exc.value.response.status_code == 401

        # valid token -> ok
        async with WsTestClient("ws://127.0.0.1:29917/ws", client_id="ok", token=token) as c:
            assert (await c.recv_ready()).client_id == "ok"

        # reuse -> 401
        with pytest.raises(websockets.exceptions.InvalidStatus) as exc:
            async with WsTestClient("ws://127.0.0.1:29917/ws", client_id="r", token=token):
                pass
        assert exc.value.response.status_code == 401
    finally:
        await ch.stop()
        await t


# -- Path routing ---------------------------------------------------------


@pytest.mark.asyncio
async def test_custom_path(bus: MagicMock) -> None:
    ch = _ch(bus, 29918, path="/my-chat")
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29918/my-chat", client_id="p") as c:
            assert (await c.recv_ready()).event == "ready"
    finally:
        await ch.stop()
        await t


@pytest.mark.asyncio
async def test_wrong_path_404(bus: MagicMock) -> None:
    ch = _ch(bus, 29919, path="/ws")
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        with pytest.raises(websockets.exceptions.InvalidStatus) as exc:
            async with WsTestClient("ws://127.0.0.1:29919/wrong", client_id="x"):
                pass
        assert exc.value.response.status_code == 404
    finally:
        await ch.stop()
        await t


@pytest.mark.asyncio
async def test_trailing_slash_normalized(bus: MagicMock) -> None:
    ch = _ch(bus, 29920, path="/ws")
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29920/ws/", client_id="s") as c:
            assert (await c.recv_ready()).event == "ready"
    finally:
        await ch.stop()
        await t


# -- Edge cases -----------------------------------------------------------


@pytest.mark.asyncio
async def test_large_message(bus: MagicMock, tmp_path) -> None:
    ch = _ch(bus, 29921, tmp_path=tmp_path)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29921/", client_id="big") as c:
            await c.recv_ready()
            await _auth(c)
            cid = await _new_chat(c)
            big = "x" * 100_000
            await c.send_json({"type": "message", "chat_id": cid, "content": big})
            await asyncio.sleep(0.2)
            assert bus.publish_inbound.call_args[0][0].content == big
    finally:
        await ch.stop()
        await t


@pytest.mark.asyncio
async def test_unicode_roundtrip(bus: MagicMock, tmp_path) -> None:
    ch = _ch(bus, 29922, tmp_path=tmp_path)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29922/", client_id="u") as c:
            await c.recv_ready()
            await _auth(c)
            cid = await _new_chat(c)
            text = "你好世界 🌍 日本語テスト"
            await c.send_json({"type": "message", "chat_id": cid, "content": text})
            await asyncio.sleep(0.1)
            assert bus.publish_inbound.call_args[0][0].content == text
            await ch.send(OutboundMessage(
                channel="websocket", chat_id=cid, content=text,
            ))
            assert (await c.recv_message()).text == text
    finally:
        await ch.stop()
        await t


@pytest.mark.asyncio
async def test_rapid_fire(bus: MagicMock, tmp_path) -> None:
    ch = _ch(bus, 29923, tmp_path=tmp_path)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29923/", client_id="r") as c:
            await c.recv_ready()
            await _auth(c)
            cid = await _new_chat(c)
            for i in range(50):
                await c.send_json({"type": "message", "chat_id": cid, "content": f"in-{i}"})
            await asyncio.sleep(0.5)
            assert bus.publish_inbound.await_count == 50
            for i in range(50):
                await ch.send(OutboundMessage(
                    channel="websocket", chat_id=cid, content=f"out-{i}",
                ))
            received = [(await c.recv_message()).text for _ in range(50)]
            assert received == [f"out-{i}" for i in range(50)]
    finally:
        await ch.stop()
        await t


@pytest.mark.asyncio
async def test_invalid_json_as_plain_text(bus: MagicMock, tmp_path) -> None:
    """slice ②: raw text (including malformed JSON) no longer routes to a
    default chat — it yields a ``no_active_chat`` error and the connection
    survives. The surviving intent (malformed input doesn't crash the server)
    is asserted here."""
    ch = _ch(bus, 29924, tmp_path=tmp_path)
    t = asyncio.create_task(ch.start())
    await asyncio.sleep(0.3)
    try:
        async with WsTestClient("ws://127.0.0.1:29924/", client_id="j") as c:
            await c.recv_ready()
            await _auth(c)
            await c.send_text("{broken json")
            await asyncio.sleep(0.1)
            bus.publish_inbound.assert_not_awaited()
            # Raw text with no active chat yields a no_active_chat error frame.
            err = await c.recv()
            assert err.event == "error"
            # Connection survives: a typed new_chat still works afterwards.
            await c.send_json({"type": "new_chat"})
            attached = await c.recv()
            assert attached.event == "attached"
    finally:
        await ch.stop()
        await t
