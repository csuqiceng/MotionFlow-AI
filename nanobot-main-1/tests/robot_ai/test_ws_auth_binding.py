"""WS auth-envelope binding (1b): outermost inbound gate + per-frame liveness +
connection-keyed bindings + cleanup + reconnect-reauth. Real gateway fixture."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket import WebSocketChannel, WebSocketConfig
from nanobot.session.manager import SessionManager
from nanobot.session.namespace import derive_namespace
from nanobot.webui.gateway_services import build_gateway_services
from robot_ai.library.auth import UserSessionStore, get_user_session_store

_PORT = 29877


def _build_channel(tmp_path: Path, *, bus=None) -> WebSocketChannel:
    cfg = WebSocketConfig.model_validate({
        "enabled": True, "allowFrom": ["*"],
        "host": "127.0.0.1", "port": _PORT,
        "path": "/ws", "websocketRequiresToken": False,
    })
    b = bus if bus is not None else MessageBus()
    gateway = build_gateway_services(
        config=cfg, bus=b, session_manager=SessionManager(tmp_path),
        static_dist_path=None, workspace_path=tmp_path,
        default_restrict_to_workspace=False, runtime_model_name=None,
        runtime_surface="browser", runtime_capabilities_overrides=None,
    )
    return WebSocketChannel(cfg, b, gateway=gateway, unified_session=False)


class FrameConn:
    """Async-iterator fake WS connection: yields frames, captures send/close."""
    def __init__(self, frames: list[str]):
        self._frames = list(frames)
        self.sent: list[dict] = []
        self.closed = False
        self.request = None
        self.remote_address = ("127.0.0.1", 0)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._frames:
            raise StopAsyncIteration
        return self._frames.pop(0)

    async def send(self, raw: str):
        try:
            self.sent.append(json.loads(raw))
        except json.JSONDecodeError:
            self.sent.append({"_raw": raw})

    async def close(self, code: int = 1000, reason: str = ""):
        self.closed = True


def _events(conn): return {e.get("event"): e for e in conn.sent}
def _error_detail(conn): return next((e.get("detail") for e in conn.sent if e.get("event") == "error"), None)


# ---- pure-logic layer ----
def test_resolve_identity_valid():
    store = UserSessionStore(ttl_seconds=3600)
    tok = store.issue({"user_id": "AbCd1234", "username": "e", "role": "engineer"})
    from nanobot.channels.websocket import resolve_bound_identity
    assert resolve_bound_identity(store, tok) == {
        "role": "engineer", "user_id": "AbCd1234",
        "namespace": "engineer:AbCd1234", "user_token": tok}

def test_resolve_identity_invalid_returns_none():
    from nanobot.channels.websocket import resolve_bound_identity
    assert resolve_bound_identity(UserSessionStore(), "bogus") is None

def test_resolve_identity_revoked_returns_none():
    store = UserSessionStore(ttl_seconds=3600)
    tok = store.issue({"user_id": "u", "username": "o", "role": "operator"})
    store.revoke(tok)
    from nanobot.channels.websocket import resolve_bound_identity
    assert resolve_bound_identity(store, tok) is None

def test_gate_unbound_business_frame_closes():
    from nanobot.channels.websocket import frame_gate_decision, FrameDecision
    assert frame_gate_decision(bound=None, envelope_type="new_chat") is FrameDecision.REJECT_AND_CLOSE
    assert frame_gate_decision(bound=None, envelope_type="message") is FrameDecision.REJECT_AND_CLOSE

def test_gate_auth_only_when_unbound():
    from nanobot.channels.websocket import frame_gate_decision, FrameDecision
    assert frame_gate_decision(bound=None, envelope_type="auth") is FrameDecision.PROCESS

def test_gate_reauth_when_bound_closes():
    from nanobot.channels.websocket import frame_gate_decision, FrameDecision
    bound = {"role": "engineer", "user_id": "x", "namespace": "engineer:x", "user_token": "t"}
    assert frame_gate_decision(bound=bound, envelope_type="auth") is FrameDecision.REJECT_AND_CLOSE

def test_gate_business_ok_when_bound():
    from nanobot.channels.websocket import frame_gate_decision, FrameDecision
    bound = {"role": "engineer", "user_id": "x", "namespace": "engineer:x", "user_token": "t"}
    for t in ("new_chat", "attach", "message", "fork_chat", "set_workspace_scope"):
        assert frame_gate_decision(bound=bound, envelope_type=t) is FrameDecision.PROCESS


# ---- integration: real _connection_loop ----
@pytest.fixture()
def store():
    return get_user_session_store()

@pytest.mark.asyncio
async def test_raw_text_before_auth_closes(tmp_path):
    from nanobot.channels.websocket import resolve_bound_identity  # noqa: F401 — ensure import works
    ch = _build_channel(tmp_path)
    conn = FrameConn(["hello raw text"])
    await ch._connection_loop(conn)
    assert conn.closed is True
    assert _error_detail(conn) == "auth_required"

@pytest.mark.asyncio
async def test_non_auth_envelope_before_auth_closes(tmp_path):
    ch = _build_channel(tmp_path)
    conn = FrameConn([json.dumps({"type": "new_chat"})])
    await ch._connection_loop(conn)
    assert conn.closed is True
    assert _error_detail(conn) == "auth_required"

@pytest.mark.asyncio
async def test_invalid_auth_token_closes(tmp_path):
    ch = _build_channel(tmp_path)
    conn = FrameConn([json.dumps({"type": "auth", "user_token": "bogus"})])
    await ch._connection_loop(conn)
    assert conn.closed is True
    assert _error_detail(conn) == "auth_failed"

@pytest.mark.asyncio
async def test_auth_ok_carries_no_chat_and_creates_no_session(tmp_path, store):
    ch = _build_channel(tmp_path)
    tok = store.issue({"user_id": "u1", "username": "o", "role": "operator"})
    conn = FrameConn([json.dumps({"type": "auth", "user_token": tok})])
    await ch._connection_loop(conn)
    ev = _events(conn)
    assert "auth_ok" in ev
    assert "chat_id" not in ev["auth_ok"]
    assert ev["auth_ok"]["role"] == "operator"
    assert ch.gateway.session_manager.list_sessions(namespace="operator:u1") == []

@pytest.mark.asyncio
async def test_cleanup_clears_binding(tmp_path, store):
    tok = store.issue({"user_id": "u2", "username": "e", "role": "engineer"})
    conn = FrameConn([json.dumps({"type": "auth", "user_token": tok})])
    ch = _build_channel(tmp_path)
    await ch._connection_loop(conn)
    assert conn not in ch._connection_bindings

@pytest.mark.asyncio
async def test_reconnect_requires_reauth(tmp_path, store):
    ch = _build_channel(tmp_path)
    conn = FrameConn([json.dumps({"type": "new_chat"})])
    await ch._connection_loop(conn)
    assert conn.closed is True

@pytest.mark.asyncio
async def test_revoked_token_next_frame_closes(tmp_path, store):
    ch = _build_channel(tmp_path)
    tok = store.issue({"user_id": "u3", "username": "e", "role": "engineer"})
    conn = FrameConn([
        json.dumps({"type": "auth", "user_token": tok}),
        json.dumps({"type": "new_chat"}),
    ])
    from nanobot.channels import websocket as wsmod
    real = wsmod.resolve_bound_identity
    call = {"n": 0}
    def spy(s, t):
        call["n"] += 1
        if call["n"] == 2:
            s.revoke(t)
        return real(s, t)
    wsmod.resolve_bound_identity = spy
    try:
        await ch._connection_loop(conn)
    finally:
        wsmod.resolve_bound_identity = real
    assert conn.closed is True

@pytest.mark.asyncio
async def test_reauth_while_bound_closes(tmp_path, store):
    ch = _build_channel(tmp_path)
    tok = store.issue({"user_id": "u4", "username": "e", "role": "engineer"})
    conn = FrameConn([
        json.dumps({"type": "auth", "user_token": tok}),
        json.dumps({"type": "auth", "user_token": tok}),
    ])
    await ch._connection_loop(conn)
    assert conn.closed is True


# ---- B5: namespace enforcement on business frames (fail-closed + zero side-effects) ----
@pytest.mark.asyncio
async def test_new_chat_stamps_caller_namespace(tmp_path, store):
    ch = _build_channel(tmp_path)
    tok = store.issue({"user_id": "n1", "username": "e", "role": "engineer"})
    conn = FrameConn([json.dumps({"type": "auth", "user_token": tok}),
                      json.dumps({"type": "new_chat"})])
    await ch._connection_loop(conn)
    chat_id = next((e["chat_id"] for e in conn.sent if e.get("event") == "attached"), None)
    assert chat_id
    ch.gateway.session_manager.assert_namespace_owner(
        f"websocket:{chat_id}", derive_namespace("engineer", "n1"))

@pytest.mark.asyncio
async def test_attach_cross_namespace_error_keepopen_no_side_effect(tmp_path, store):
    ch = _build_channel(tmp_path)
    tok_o = store.issue({"user_id": "other", "username": "e", "role": "engineer"})
    c_o = FrameConn([json.dumps({"type": "auth", "user_token": tok_o}),
                     json.dumps({"type": "new_chat"})])
    await ch._connection_loop(c_o)
    other_chat = next(e["chat_id"] for e in c_o.sent if e.get("event") == "attached")
    tok_m = store.issue({"user_id": "me", "username": "e", "role": "engineer"})
    c_m = FrameConn([json.dumps({"type": "auth", "user_token": tok_m}),
                     json.dumps({"type": "attach", "chat_id": other_chat})])
    await ch._connection_loop(c_m)
    assert any(e.get("code") == "session_not_available" for e in c_m.sent)
    assert c_m.closed is False
    assert c_m not in ch._subs.get(other_chat, set())

@pytest.mark.asyncio
async def test_message_cross_namespace_no_publish_no_write(tmp_path, store):
    bus = MagicMock()
    ch = _build_channel(tmp_path, bus=bus)
    tok_o = store.issue({"user_id": "o2", "username": "e", "role": "engineer"})
    c_o = FrameConn([json.dumps({"type": "auth", "user_token": tok_o}),
                     json.dumps({"type": "new_chat"})])
    await ch._connection_loop(c_o)
    other_chat = next(e["chat_id"] for e in c_o.sent if e.get("event") == "attached")
    target_key = f"websocket:{other_chat}"
    before = ch.gateway.session_manager.get_or_create(target_key).messages[:]
    tok_m = store.issue({"user_id": "m2", "username": "e", "role": "engineer"})
    c_m = FrameConn([json.dumps({"type": "auth", "user_token": tok_m}),
                     json.dumps({"type": "message", "chat_id": other_chat, "content": "hi"})])
    await ch._connection_loop(c_m)
    assert any(e.get("code") == "session_not_available" for e in c_m.sent)
    assert c_m.closed is False
    bus.publish.assert_not_called()
    after = ch.gateway.session_manager.get_or_create(target_key).messages
    assert after == before

@pytest.mark.asyncio
async def test_fork_cross_namespace_creates_nothing(tmp_path, store):
    ch = _build_channel(tmp_path)
    tok_o = store.issue({"user_id": "o3", "username": "e", "role": "engineer"})
    c_o = FrameConn([json.dumps({"type": "auth", "user_token": tok_o}),
                     json.dumps({"type": "new_chat"})])
    await ch._connection_loop(c_o)
    other_chat = next(e["chat_id"] for e in c_o.sent if e.get("event") == "attached")
    mine_before = ch.gateway.session_manager.list_sessions(namespace="engineer:m3")
    tok_m = store.issue({"user_id": "m3", "username": "e", "role": "engineer"})
    c_m = FrameConn([json.dumps({"type": "auth", "user_token": tok_m}),
                     json.dumps({"type": "fork_chat", "source_chat_id": other_chat,
                                 "before_user_index": 0})])
    await ch._connection_loop(c_m)
    assert any(e.get("code") == "session_not_available" for e in c_m.sent)
    assert c_m.closed is False
    assert ch.gateway.session_manager.list_sessions(namespace="engineer:m3") == mine_before

@pytest.mark.asyncio
async def test_set_workspace_scope_cross_namespace_not_persisted(tmp_path, store, monkeypatch):
    ch = _build_channel(tmp_path)
    persist_calls = []
    monkeypatch.setattr(ch._workspaces, "persist_scope",
                        lambda cid, scope: persist_calls.append((cid, scope)))
    tok_o = store.issue({"user_id": "o4", "username": "e", "role": "engineer"})
    c_o = FrameConn([json.dumps({"type": "auth", "user_token": tok_o}),
                     json.dumps({"type": "new_chat"})])
    await ch._connection_loop(c_o)
    other_chat = next(e["chat_id"] for e in c_o.sent if e.get("event") == "attached")
    # Snapshot after the owner's new_chat so we measure ONLY the attacker's effect.
    count_before = len(persist_calls)
    tok_m = store.issue({"user_id": "m4", "username": "e", "role": "engineer"})
    c_m = FrameConn([json.dumps({"type": "auth", "user_token": tok_m}),
                     json.dumps({"type": "set_workspace_scope", "chat_id": other_chat,
                                 "project_path": "/x"})])
    await ch._connection_loop(c_m)
    assert any(e.get("code") == "session_not_available" for e in c_m.sent)
    assert c_m.closed is False
    assert len(persist_calls) == count_before

@pytest.mark.asyncio
async def test_namespace_allows_failclosed_without_manager(tmp_path, store):
    ch = _build_channel(tmp_path)
    # GatewayServices is a frozen dataclass; bypass to simulate no session_manager.
    object.__setattr__(ch.gateway, "session_manager", None)
    bound = {"role": "engineer", "user_id": "x", "namespace": "engineer:x", "user_token": "t"}
    conn = FrameConn([])
    ok = await ch._namespace_allows(conn, "any", bound)
    assert ok is False
    assert any(e.get("code") == "session_not_available" for e in conn.sent)

@pytest.mark.asyncio
async def test_attach_own_namespace_ok(tmp_path, store):
    ch = _build_channel(tmp_path)
    tok = store.issue({"user_id": "m5", "username": "e", "role": "engineer"})
    c1 = FrameConn([json.dumps({"type": "auth", "user_token": tok}),
                    json.dumps({"type": "new_chat"})])
    await ch._connection_loop(c1)
    mine = next(e["chat_id"] for e in c1.sent if e.get("event") == "attached")
    c2 = FrameConn([json.dumps({"type": "auth", "user_token": tok}),
                    json.dumps({"type": "attach", "chat_id": mine})])
    await ch._connection_loop(c2)
    assert next((e["chat_id"] for e in c2.sent if e.get("event") == "attached"), None) == mine
    assert c2.closed is False

@pytest.mark.asyncio
async def test_new_chat_scope_failure_creates_no_session(tmp_path, store, monkeypatch):
    ch = _build_channel(tmp_path)
    tok = store.issue({"user_id": "sf", "username": "e", "role": "engineer"})

    def _boom(*a, **k):
        raise ValueError("scope fail")

    monkeypatch.setattr(ch._workspaces, "scope_for_new_chat", _boom)
    conn = FrameConn([json.dumps({"type": "auth", "user_token": tok}),
                      json.dumps({"type": "new_chat", "project_path": "/x"})])
    await ch._connection_loop(conn)
    assert not any(e.get("event") == "attached" for e in conn.sent)
    assert ch.gateway.session_manager.list_sessions(namespace="engineer:sf") == []
