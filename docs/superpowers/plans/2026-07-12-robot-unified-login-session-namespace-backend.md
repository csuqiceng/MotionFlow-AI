# 统一登录 + 会话命名空间隔离 — 切片② 后端实施计划 (Plan A, rev 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 在切片① 身份层之上，加"按用户隔离的会话命名空间 + WS auth 首帧绑定（全入站路径门控）+ 全 session-key REST/WS 门控 + unified_session fail-closed"。操作员/工程师各自只看到/只写到属于自己的会话；legacy 无命名空间会话静默拒绝。

**Architecture:** namespace `"{role}:{user_id}"` 存入 `.jsonl` `metadata.namespace`（key 不变）。**WS 入站最外层** auth 门控：未绑定前只放行 `auth` envelope，raw 文本/其它帧一律拒并 `await connection.close(code=1008)`。**auth 成功只绑定身份 + 发 `auth_ok`（不含 chat_id、不建会话）**；会话由显式 `new_chat` 创建（`stamp_namespace → _attach → hydrate`）。绑定 keyed by connection，`_cleanup_connection` 清理。业务帧每帧用 bound token `UserSessionStore.check()` 验活（撤销即关连接）。所有 session-key 读/写校验 `metadata.namespace`，不符/缺失 → REST `404 session not available` / WS `session_not_available` 错误帧（**连接保持 + 零副作用**）。`stamp_namespace` write-once。list 经 `session_list_index.py` 缓存（行加 ns + 过滤 + 版本 2→3）。`unified_session` 从真实 config 显式注入 channel（必填形参，取不到即 fail-closed）。

**Tech Stack:** Python 3.11+, asyncio, pytest (`asyncio_mode=auto`), ruff (E/F/I/N/W, E501 ignored, line 100). 复用切片① `UserSessionStore`/`UserRegistry`/`process_auth_login`（零改动）。WS 测试复用 `tests/channels/test_websocket_channel.py` 的 `build_gateway_services` 夹具模式。

**关联:** spec `docs/superpowers/specs/2026-07-12-robot-unified-login-session-namespace-design.md`。rev 3 修复用户 5 项正文阻塞：①集成测试不得 skip（真实夹具）；②删重复测试块；③auth 不建默认 chat；④new_chat 顺序 stamp→attach→hydrate；⑤跨 ns 断言零副作用。

---

## ⚠️ 硬约束（覆盖 skill 默认）

1. **全程 NO GIT**（memory `no-git-commit-unified-later`）：禁止 `git add/commit/push`、建分支。每任务以"跑测试验证"收尾。
2. **venv + bash**：`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest ...` / `-m ruff check ...`。Shell 是 Git Bash（unix 语法）。
3. **切片① 鉴权零改动**。
4. **新测试放 `tests/robot_ai/`**。WS 帧级测试用真实 `build_gateway_services` 夹具（本计划提供完整可运行代码），**禁止 `pytest.skip`**。
5. **不破坏既有 525 测试**（B8 的 `unified_session` 必填会要求更新所有 `WebSocketChannel(` 调用点——见 B8）。

---

## 文件结构

| 文件 | 责任 | 动作 |
|---|---|---|
| `nanobot/session/namespace.py` (新) | `derive_namespace`/`SessionNotAvailableError`/`NamespaceAlreadyBoundError` | 增 |
| `nanobot/session/manager.py` | `stamp_namespace`(write-once)/`assert_namespace_owner`/`list_sessions(namespace)` | 改 |
| `nanobot/webui/session_list_index.py` | 缓存行加 ns + `list_webui_sessions(namespace)` + 版本 2→3 | 改 |
| `nanobot/channels/websocket.py` | 入站最外层 auth 门控；绑定 keyed by connection + `_cleanup_connection` 清理；`_dispatch_bound_envelope` ns 校验（fail-closed/async）；new_chat `stamp→attach→hydrate`；`__init__` 必填 `unified_session` | 改 |
| `nanobot/webui/ws_http.py` | session 路由 ns 门控 + list 派生过滤 + `?namespace=` 校验 | 改 |
| WS channel 构造点（生产 + 所有 tests/channels/） | 显式传 `unified_session` | 改 |
| `nanobot/cli/commands.py` (`_run_gateway`) | 启动 fail-closed 检查 | 改 |
| `robot_ai/library/users.py` | `assert_unified_session_disabled` | 改 |
| `tests/robot_ai/test_session_namespace.py`/`test_ws_auth_binding.py`/`test_ws_http_session_namespace.py`/`test_unified_session_failclosed.py` (新) | 单测 + 真实夹具帧级集成 | 增 |

---

## Task B1: namespace 工具模块

**Files:** Create `nanobot/session/namespace.py`, `tests/robot_ai/test_session_namespace.py`

- [ ] **Step 1: 写失败测试**
```python
# tests/robot_ai/test_session_namespace.py
import pytest
from nanobot.session.namespace import (
    derive_namespace, SessionNotAvailableError, NamespaceAlreadyBoundError,
)

def test_derive_namespace_format():
    assert derive_namespace("engineer", "AbCd1234") == "engineer:AbCd1234"
    assert derive_namespace("operator", "Zx9Y") == "operator:Zx9Y"

def test_derive_namespace_rejects_bad_role():
    with pytest.raises(ValueError):
        derive_namespace("admin", "uid")

def test_exception_types():
    assert issubclass(SessionNotAvailableError, Exception)
    assert issubclass(NamespaceAlreadyBoundError, ValueError)
```
- [ ] **Step 2: 跑确认失败** — `cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_session_namespace.py -q` → FAIL (ImportError)
- [ ] **Step 3: 写实现**
```python
# nanobot/session/namespace.py
"""Session namespace helpers for multi-user isolation (slice ②).

namespace = "{role}:{user_id}", stored in session.metadata["namespace"].
Server-derived only; never trusted from clients.
"""
from __future__ import annotations

_VALID_ROLES = ("operator", "engineer")


class SessionNotAvailableError(Exception):
    """Session absent OR not owned by caller's namespace. Uniformly REST 404 /
    WS session_not_available (no existence leak)."""


class NamespaceAlreadyBoundError(ValueError):
    """Session already bound to a different namespace (stamp_namespace guard).
    Only a future audited claim/migration tool may reassign ownership."""


def derive_namespace(role: str, user_id: str) -> str:
    if role not in _VALID_ROLES:
        raise ValueError(f"Invalid role {role!r}; must be one of {_VALID_ROLES}.")
    if not user_id:
        raise ValueError("user_id must not be empty.")
    return f"{role}:{user_id}"
```
- [ ] **Step 4: 跑确认通过** — 同上命令 → PASS (3)
- [ ] **Step 5: 验证（不提交）** — `ruff check nanobot/session/namespace.py` clean

---

## Task B2: `stamp_namespace`（write-once）+ legacy 向后兼容

**Files:** Modify `nanobot/session/manager.py`（`save()` :647 已序列化 `metadata`）；Test 追加。

- [ ] **Step 1: 写失败测试（追加到 test_session_namespace.py）**
```python
from pathlib import Path
import json
from datetime import datetime
from nanobot.session.manager import SessionManager

@pytest.fixture()
def manager(tmp_path: Path) -> SessionManager:
    return SessionManager(tmp_path)

def test_stamp_namespace_sets_metadata(manager):
    manager.stamp_namespace("websocket:c1", "engineer:AbCd1234")
    assert manager.get_or_create("websocket:c1").metadata.get("namespace") == "engineer:AbCd1234"

def test_stamp_namespace_idempotent_same_value(manager):
    manager.stamp_namespace("websocket:c2", "operator:Zx9Y")
    manager.stamp_namespace("websocket:c2", "operator:Zx9Y")
    assert manager.get_or_create("websocket:c2").metadata.get("namespace") == "operator:Zx9Y"

def test_stamp_namespace_rejects_different_value(manager):
    manager.stamp_namespace("websocket:c3", "engineer:AbCd1234")
    with pytest.raises(NamespaceAlreadyBoundError):
        manager.stamp_namespace("websocket:c3", "engineer:ATTACKER")
    assert manager.get_or_create("websocket:c3").metadata.get("namespace") == "engineer:AbCd1234"

def test_legacy_session_loads_without_namespace(manager):
    key = "websocket:legacy-1"
    path = manager._get_session_path(key)  # noqa: SLF001
    path.write_text(json.dumps({"_type": "metadata", "key": key,
        "created_at": datetime.now().isoformat(), "updated_at": datetime.now().isoformat(),
        "metadata": {}}) + "\n", encoding="utf-8")
    assert manager.get_or_create(key).metadata.get("namespace") is None
```
- [ ] **Step 2: 跑确认失败** — `pytest tests/robot_ai/test_session_namespace.py -q` → FAIL
- [ ] **Step 3: 写实现** — `SessionManager` 内紧邻 `save`（约 :680）：
```python
    def stamp_namespace(self, key: str, namespace: str) -> Session:
        """Bind a session to *namespace* at creation (write-once).

        Same value idempotent; different existing namespace raises
        NamespaceAlreadyBoundError (never overwrite — only a future audited
        claim/migration tool may reassign ownership).
        """
        from nanobot.session.namespace import NamespaceAlreadyBoundError
        session = self.get_or_create(key)
        existing = session.metadata.get("namespace")
        if existing is not None and existing != namespace:
            raise NamespaceAlreadyBoundError(
                f"session {key!r} already bound to namespace {existing!r}")
        session.metadata["namespace"] = namespace
        self.save(session)
        return session
```
- [ ] **Step 4: 跑确认通过** → PASS (7)
- [ ] **Step 5: 验证（不提交）** — `ruff check nanobot/session/manager.py` clean

---

## Task B3: `assert_namespace_owner` + `list_sessions(namespace)` 过滤

**Files:** Modify `manager.py`（`list_sessions` :861 + 新增 `assert_namespace_owner`）；Test 追加。

- [ ] **Step 1: 写失败测试（追加）**
```python
from nanobot.session.namespace import SessionNotAvailableError

def _write_legacy(manager, key):
    path = manager._get_session_path(key)  # noqa: SLF001
    path.write_text(json.dumps({"_type": "metadata", "key": key,
        "created_at": datetime.now().isoformat(), "updated_at": datetime.now().isoformat(),
        "metadata": {}}) + "\n", encoding="utf-8")

def test_assert_owner_ok(manager):
    manager.stamp_namespace("websocket:o", "engineer:AbCd1234")
    manager.assert_namespace_owner("websocket:o", "engineer:AbCd1234")

def test_assert_owner_cross_user_raises(manager):
    manager.stamp_namespace("websocket:s", "engineer:AbCd1234")
    with pytest.raises(SessionNotAvailableError):
        manager.assert_namespace_owner("websocket:s", "engineer:OTHER")

def test_assert_owner_legacy_raises(manager):
    _write_legacy(manager, "websocket:lg")
    with pytest.raises(SessionNotAvailableError):
        manager.assert_namespace_owner("websocket:lg", "engineer:AbCd1234")

def test_assert_owner_missing_key_indistinguishable(manager):
    with pytest.raises(SessionNotAvailableError):
        manager.assert_namespace_owner("websocket:ghost", "engineer:AbCd1234")

def test_list_sessions_filters_by_namespace(manager):
    manager.stamp_namespace("websocket:a", "engineer:AbCd1234")
    manager.stamp_namespace("websocket:b", "operator:Zx9Y")
    _write_legacy(manager, "websocket:legacy-3")
    eng = manager.list_sessions(namespace="engineer:AbCd1234")
    op = manager.list_sessions(namespace="operator:Zx9Y")
    assert [s["key"] for s in eng] == ["websocket:a"]
    assert [s["key"] for s in op] == ["websocket:b"]
    assert not any(s["key"] == "websocket:legacy-3" for s in eng + op)

def test_list_sessions_no_filter_returns_all(manager):
    manager.stamp_namespace("websocket:c", "engineer:AbCd1234")
    _write_legacy(manager, "websocket:legacy-4")
    rows = manager.list_sessions()
    keys = {s["key"] for s in rows}
    assert "websocket:c" in keys and "websocket:legacy-4" in keys
```
- [ ] **Step 2: 跑确认失败** → FAIL
- [ ] **Step 3: 写实现**
(a) `list_sessions`（:861）签名加 `namespace: str | None = None`；在 `metadata = data.get("metadata", {})`（:881）后、`sessions.append(...)` 前插：
```python
                        if namespace is not None and metadata.get("namespace") != namespace:
                            continue
```
（`_repair` 分支 append 前同过滤。）
(b) 新增 `assert_namespace_owner`（紧邻 `stamp_namespace`）：
```python
    def assert_namespace_owner(self, key: str, namespace: str) -> None:
        """Raise SessionNotAvailableError if *key* absent or not owned by *namespace*.
        Legacy (no namespace) never matches; absent ≈ not-owned (no leak)."""
        from nanobot.session.namespace import SessionNotAvailableError
        path = self._get_session_path(key)
        if not path.exists():
            raise SessionNotAvailableError(key)
        try:
            with open(path, encoding="utf-8") as f:
                first = f.readline().strip()
            data = json.loads(first) if first else {}
        except Exception:
            raise SessionNotAvailableError(key)
        meta = data.get("metadata", {}) if isinstance(data, dict) else {}
        meta_ns = meta.get("namespace") if isinstance(meta, dict) else None
        if meta_ns != namespace:
            raise SessionNotAvailableError(key)
```
- [ ] **Step 4: 跑确认通过** → PASS (13)
- [ ] **Step 5: 验证（不提交）** — `ruff check nanobot/session/` clean

---

## Task B4: WS 入站最外层 auth 门控（修 P0）+ 真实夹具（修阻塞①）+ auth 不建默认 chat（修③）

**目标**：auth 门控在 `_connection_loop` 的 `async for raw` 循环体最外层，envelope 与 raw 文本都过门控；**auth 成功只绑定身份 + 发 `auth_ok`（无 chat_id、不建会话）**；绑定 keyed by connection，`_cleanup_connection` 清理；关连接 `await connection.close(code=1008)`。**测试用真实 `build_gateway_services` 夹具，全部 `@pytest.mark.asyncio` 真跑，禁止 skip。**

**Files:** Modify `nanobot/channels/websocket.py`（`__init__` :277 加 `_connection_bindings`、`_cleanup_connection` :316 清理、`_connection_loop` :517 重写、`_dispatch_envelope` :648 → `_dispatch_bound_envelope`、顶部加纯逻辑层）；Create `tests/robot_ai/test_ws_auth_binding.py`（真实夹具 + `FrameConn`）。

> **执行者一次须知：** channel 经 `self.gateway.session_manager`（:335）取 SessionManager；`UserSessionStore` 经 `robot_ai.library.auth.get_user_session_store()`。`connection.close` 是 `websockets` 协程 `async def close(code=1000, reason="")`。先完整读 `_connection_loop`（:517-576）与 `_dispatch_envelope`（:648-760）。WS 夹具照搬 `tests/channels/test_websocket_channel.py` 的 `build_gateway_services` 模式（本任务 Step 1 给出完整可运行代码）。

- [ ] **Step 1: 写失败测试（完整可运行，无 skip）**

```python
# tests/robot_ai/test_ws_auth_binding.py
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
    # NOTE: B4 does NOT add the unified_session kwarg (that is B8). Construct
    # WITHOUT it here. B8 will update this fixture to pass unified_session=False
    # once it makes the kwarg required.
    return WebSocketChannel(cfg, b, gateway=gateway)


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


# ---- 纯逻辑层（Step 3 定义：resolve_bound_identity / frame_gate_decision / FrameDecision）----
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


# ---- 集成：真实 _connection_loop 驱动 ----
@pytest.fixture()
def store():
    return get_user_session_store()

@pytest.mark.asyncio
async def test_raw_text_before_auth_closes(tmp_path):
    """P0: 未 auth 的 raw 文本不得绕过门控进 _handle_message。"""
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
    """修③：auth 成功只发 auth_ok(role,user_id)，不建/不 stamp 默认 chat，不污染会话列表。"""
    ch = _build_channel(tmp_path)
    tok = store.issue({"user_id": "u1", "username": "o", "role": "operator"})
    conn = FrameConn([json.dumps({"type": "auth", "user_token": tok})])
    await ch._connection_loop(conn)
    ev = _events(conn)
    assert "auth_ok" in ev
    assert "chat_id" not in ev["auth_ok"]  # 无默认 chat
    assert ev["auth_ok"]["role"] == "operator"
    # 无任何会话落盘
    assert ch.gateway.session_manager.list_sessions(namespace="operator:u1") == []

@pytest.mark.asyncio
async def test_cleanup_clears_binding(tmp_path, store):
    tok = store.issue({"user_id": "u2", "username": "e", "role": "engineer"})
    conn = FrameConn([json.dumps({"type": "auth", "user_token": tok})])
    ch = _build_channel(tmp_path)
    await ch._connection_loop(conn)
    assert conn not in ch._connection_bindings  # finally → _cleanup_connection 清理

@pytest.mark.asyncio
async def test_reconnect_requires_reauth(tmp_path, store):
    """新连接无继承绑定；直接发业务帧 → 关连接。"""
    ch = _build_channel(tmp_path)
    conn = FrameConn([json.dumps({"type": "new_chat"})])  # 未 auth
    await ch._connection_loop(conn)
    assert conn.closed is True

@pytest.mark.asyncio
async def test_revoked_token_next_frame_closes(tmp_path, store):
    """已绑定后 token 被 revoke（禁用/改密）→ 下一业务帧验活失败 → 关连接。"""
    ch = _build_channel(tmp_path)
    tok = store.issue({"user_id": "u3", "username": "e", "role": "engineer"})
    conn = FrameConn([
        json.dumps({"type": "auth", "user_token": tok}),
        json.dumps({"type": "new_chat"}),  # 第二帧前会被 revoke
    ])
    # 在两帧之间 revoke：用 monkeypatch 在第一帧处理后注入 revoke。
    orig_resolve = None
    from nanobot.channels import websocket as wsmod
    real = wsmod.resolve_bound_identity
    call = {"n": 0}
    def spy(s, t):
        call["n"] += 1
        if call["n"] == 2:  # 第二次验活（new_chat 业务帧）前 revoke
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
    """修 rev4-①：已绑定后再发 auth 帧 → bound 分支 gate 判定 REJECT_AND_CLOSE → 关连接（防重绑定劫持）。"""
    ch = _build_channel(tmp_path)
    tok = store.issue({"user_id": "u4", "username": "e", "role": "engineer"})
    conn = FrameConn([
        json.dumps({"type": "auth", "user_token": tok}),
        json.dumps({"type": "auth", "user_token": tok}),  # 已绑定再 auth → 必关
    ])
    await ch._connection_loop(conn)
    assert conn.closed is True
```

- [ ] **Step 2: 跑确认失败** — `pytest tests/robot_ai/test_ws_auth_binding.py -q` → FAIL（ImportError + P0/auth 集成红）
- [ ] **Step 3: 写实现**

(a) 顶部加纯逻辑层 + import：
```python
import enum
from typing import Optional
from robot_ai.library.auth import UserSessionStore, get_user_session_store
from nanobot.session.namespace import derive_namespace


class FrameDecision(enum.Enum):
    PROCESS = "process"
    REJECT_AND_CLOSE = "reject_and_close"


_AUTH_TYPE = "auth"


def resolve_bound_identity(store: "UserSessionStore", user_token: str) -> Optional[dict]:
    """Validate *user_token* → {role,user_id,namespace,user_token} or None.
    Called on auth frame (bind) AND every business frame (liveness)."""
    session = store.check(user_token) if user_token else None
    if session is None:
        return None
    return {"role": session["role"], "user_id": session["user_id"],
            "namespace": derive_namespace(session["role"], session["user_id"]),
            "user_token": user_token}


def frame_gate_decision(*, bound: Optional[dict], envelope_type: str) -> FrameDecision:
    if envelope_type == _AUTH_TYPE:
        return FrameDecision.PROCESS if bound is None else FrameDecision.REJECT_AND_CLOSE
    return FrameDecision.PROCESS if bound is not None else FrameDecision.REJECT_AND_CLOSE
```

(b) `__init__`（:277，`self._conn_default` 之后）加：
```python
        self._connection_bindings: dict[Any, dict[str, str]] = {}
```

(c) `_cleanup_connection`（:316 末尾）加：
```python
        self._connection_bindings.pop(connection, None)
```

(d) **`_connection_loop`（:517）重写**——删 pre-auth 默认 chat（:529, :543-545），auth 门控放 `async for raw` 最外层，**auth 成功不建 chat**（修③）。替换 :529 与 :542-572 为：
```python
        # slice ②: NO default chat on connect or on auth — sessions are created
        # only by an explicit new_chat envelope (keeps the session list clean).
        try:
            await connection.send(json.dumps(
                {"event": "ready", "client_id": client_id}, ensure_ascii=False))

            async for raw in connection:
                if isinstance(raw, bytes):
                    try:
                        raw = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        self.logger.warning("ignoring non-utf8 binary frame")
                        continue

                bound = self._connection_bindings.get(connection)
                store = get_user_session_store()

                # ---- 最外层 AUTH 门控 ----
                if bound is None:
                    env = _parse_envelope(raw)
                    if env is None or env.get("type") != _AUTH_TYPE:
                        await self._send_event(connection, "error", detail="auth_required")
                        await connection.close(code=1008, reason="auth required")
                        return
                    ident = resolve_bound_identity(store, env.get("user_token", ""))
                    if ident is None:
                        await self._send_event(connection, "error", detail="auth_failed")
                        await connection.close(code=1008, reason="auth failed")
                        return
                    self._connection_bindings[connection] = ident
                    await self._send_event(connection, "auth_ok",
                                           role=ident["role"], user_id=ident["user_id"])
                    continue

                # ---- 已绑定：每帧验活（撤销/过期即关）----
                refreshed = resolve_bound_identity(store, bound["user_token"])
                if refreshed is None:
                    await self._send_event(connection, "error", detail="auth_expired")
                    self._connection_bindings.pop(connection, None)
                    await connection.close(code=1008, reason="auth expired")
                    return

                envelope = _parse_envelope(raw)
                if envelope is not None:
                    # 已绑定后再 auth（重绑定劫持）等 → gate 判定关连接（修 rev4-①）
                    if frame_gate_decision(
                        bound=refreshed,
                        envelope_type=str(envelope.get("type", "")),
                    ) is FrameDecision.REJECT_AND_CLOSE:
                        await self._send_event(connection, "error", detail="auth_required")
                        await connection.close(code=1008, reason="auth required")
                        return
                    await self._dispatch_bound_envelope(connection, client_id, envelope, refreshed)
                    continue
                # raw 文本：slice ② 无默认 chat，raw 文本无路由目标 → 忽略
                # （客户端须用 new_chat/message envelope）
                content = _parse_inbound_payload(raw)
                if content is None:
                    continue
                await self._send_event(connection, "error", detail="no_active_chat")
        except Exception as e:
            self.logger.debug("connection ended: {}", e)
        finally:
            self._cleanup_connection(connection)
```

(e) 原 `_dispatch_envelope`（:648）→ 重命名 `_dispatch_bound_envelope(self, connection, client_id, envelope, bound)`，签名加 `bound`，既有 new_chat/attach/message/fork_chat/set_workspace_scope/transcribe_audio 分支整体迁入（B5 在此加 ns 校验与 new_chat stamp）。删除原方法对 auth 的处理（auth 现由门控层负责）。

- [ ] **Step 4: 跑确认通过** — `pytest tests/robot_ai/test_ws_auth_binding.py -q` → PASS（纯逻辑 7 + 集成 7，共 14，**无 skip**）
- [ ] **Step 5: 验证（不提交）** — `ruff check nanobot/channels/websocket.py` clean；`pytest tests/robot_ai/ -q`（既有 WS 用例因 auth 门控红 → B6 Step 4 统一修夹具）

---

## Task B5: WS 业务帧 ns 归属（fail-closed + async + 真实帧级 + 零副作用，修④⑤）

**Files:** Modify `websocket.py`（`_dispatch_bound_envelope` 各分支 + async `_namespace_allows`）；Test 追加到 `test_ws_auth_binding.py`。

- [ ] **Step 1: 写失败测试（追加，真实帧级 + 零副作用断言）**
```python
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
    """attach 他人 session → session_not_available 错误帧 + 连接保持 + 未订阅。"""
    ch = _build_channel(tmp_path)
    # other 建 chat
    tok_o = store.issue({"user_id": "other", "username": "e", "role": "engineer"})
    c_o = FrameConn([json.dumps({"type": "auth", "user_token": tok_o}),
                     json.dumps({"type": "new_chat"})])
    await ch._connection_loop(c_o)
    other_chat = next(e["chat_id"] for e in c_o.sent if e.get("event") == "attached")
    # me 尝试 attach other 的 chat
    tok_m = store.issue({"user_id": "me", "username": "e", "role": "engineer"})
    c_m = FrameConn([json.dumps({"type": "auth", "user_token": tok_m}),
                     json.dumps({"type": "attach", "chat_id": other_chat})])
    await ch._connection_loop(c_m)
    assert any(e.get("code") == "session_not_available" for e in c_m.sent)
    assert c_m.closed is False
    # 副作用：me 未被订阅到 other_chat
    assert c_m not in ch._subs.get(other_chat, set())


@pytest.mark.asyncio
async def test_message_cross_namespace_no_publish_no_write(tmp_path, store):
    """message 他人 session → 错误帧 + 连接保持 + 不发布到 bus + 不写 session。"""
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
    # 零副作用：bus 未发布；session 消息不变
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
                     json.dumps({"type": "fork_chat", "chat_id": other_chat,
                                 "before_user_index": 0})])
    await ch._connection_loop(c_m)
    assert any(e.get("code") == "session_not_available" for e in c_m.sent)
    assert c_m.closed is False
    # 零副作用：me 命名空间下未新增会话
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
    tok_m = store.issue({"user_id": "m4", "username": "e", "role": "engineer"})
    c_m = FrameConn([json.dumps({"type": "auth", "user_token": tok_m}),
                     json.dumps({"type": "set_workspace_scope", "chat_id": other_chat,
                                 "project_path": "/x"})])
    await ch._connection_loop(c_m)
    assert any(e.get("code") == "session_not_available" for e in c_m.sent)
    assert c_m.closed is False
    assert not any(cid == other_chat for cid, _ in persist_calls)  # 未持久化他人 scope


@pytest.mark.asyncio
async def test_namespace_allows_failclosed_without_manager(tmp_path, store):
    """session_manager 缺失 → fail-closed（不得 True）。"""
    ch = _build_channel(tmp_path)
    ch.gateway.session_manager = None  # 模拟缺失
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
    """修 rev4-②：scope 校验失败 → 不 stamp、不建会话、不发 attached（无空 session 残留）。"""
    ch = _build_channel(tmp_path)
    tok = store.issue({"user_id": "sf", "username": "e", "role": "engineer"})

    def _boom(*a, **k):
        raise ValueError("scope fail")  # _workspace_scope_or_error 捕获 → scope None → 提前 return

    monkeypatch.setattr(ch._workspaces, "scope_for_new_chat", _boom)
    conn = FrameConn([json.dumps({"type": "auth", "user_token": tok}),
                      json.dumps({"type": "new_chat", "project_path": "/x"})])
    await ch._connection_loop(conn)
    assert not any(e.get("event") == "attached" for e in conn.sent)
    assert ch.gateway.session_manager.list_sessions(namespace="engineer:sf") == []
```

- [ ] **Step 2: 跑确认失败** — `pytest tests/robot_ai/test_ws_auth_binding.py -q` → FAIL（跨 ns 未发错误帧/有副作用/fail-open）
- [ ] **Step 3: 写实现**

(a) `_namespace_allows` **async + fail-closed**：
```python
    async def _namespace_allows(self, connection, chat_id: str, bound: dict) -> bool:
        """True if *chat_id* belongs to bound namespace; else send a
        session_not_available error frame (connection kept) and return False.
        Fail-closed: no session_manager → False (never True)."""
        from nanobot.session.namespace import SessionNotAvailableError
        mgr = self.gateway.session_manager
        if mgr is None:
            await self._send_event(connection, "error", code="session_not_available")
            return False
        try:
            mgr.assert_namespace_owner(f"websocket:{chat_id}", bound["namespace"])
        except SessionNotAvailableError:
            await self._send_event(connection, "error", code="session_not_available")
            return False
        return True
```

(b) `_dispatch_bound_envelope` 各分支（**校验必须放在任何副作用之前**，确保零副作用）：
- `new_chat`（修 rev4-②顺序）：mint `new_id` → `scope_for_new_chat`（经 `_workspace_scope_or_error`，**`scope is None` 立即 return，不 stamp、不建会话、不发 attached**）→ `stamp_namespace(f"websocket:{new_id}", bound["namespace"])` → `persist_scope` → `_attach` → `_send_event attached`/`session_updated` → `_hydrate_after_subscribe`。即原 :656-678 代码，仅在 `if scope is None: return` 之后、`persist_scope` 之前插一行 stamp（顺序 **scope→stamp→persist→attach→hydrate**）。
- `attach`（:682）：`_is_valid_chat_id(cid)` 后 → `if not await self._namespace_allows(connection, cid, bound): return`（在 `_attach` 前）。
- `message`（:721）：`_is_valid_chat_id` 后、media 解析前 → 同上 `if not await self._namespace_allows(...): return`。
- `fork_chat`（:679）：取 source chat_id（`envelope.get("chat_id")`），`if not await self._namespace_allows(connection, source, bound): return`（在 `handle_webui_fork_chat` 前）。
- `set_workspace_scope`（:691）：`_is_valid_chat_id(cid)` 后 → `if not await self._namespace_allows(connection, cid, bound): return`（在 `scope_for_set_request`/`persist_scope` 前）。
- `transcribe_audio`（:717）：无 session 目标，免校验。

- [ ] **Step 4: 跑确认通过** — `pytest tests/robot_ai/test_ws_auth_binding.py tests/robot_ai/test_session_namespace.py -q` → PASS（含 7 个跨 ns 零副作用集成）
- [ ] **Step 5: 验证（不提交）** — `ruff check nanobot/channels/websocket.py` clean

---

## Task B6: REST session 路由 ns 门控 + 修既有 WS 测试夹具

**Files:** Modify `nanobot/webui/ws_http.py`（`_dispatch_session_routes` :381 + 各 `_handle_session_*` :803+ + 纯辅助）；Create `tests/robot_ai/test_ws_http_session_namespace.py`；修受 B4 auth 门控影响的既有 WS 集成测试夹具。

- [ ] **Step 1: 写失败测试**
```python
# tests/robot_ai/test_ws_http_session_namespace.py
import pytest
from nanobot.session.namespace import derive_namespace, SessionNotAvailableError

@pytest.fixture()
def store():
    from robot_ai.library.auth import get_user_session_store
    return get_user_session_store()

def test_derive_namespace_from_user_token(store):
    from nanobot.webui.ws_http import derive_namespace_from_user_token
    tok = store.issue({"user_id": "AbCd1234", "username": "e", "role": "engineer"})
    assert derive_namespace_from_user_token(tok) == "engineer:AbCd1234"

def test_derive_namespace_rejects_missing(store):
    from nanobot.webui.ws_http import derive_namespace_from_user_token
    assert derive_namespace_from_user_token("") is None
    assert derive_namespace_from_user_token("bogus") is None

def test_enforce_owner_raises_cross_namespace(tmp_path, store):
    from nanobot.session.manager import SessionManager
    from nanobot.webui.ws_http import enforce_session_owner
    mgr = SessionManager(tmp_path)
    mgr.stamp_namespace("websocket:vic", "engineer:OWNER")
    with pytest.raises(SessionNotAvailableError):
        enforce_session_owner(mgr, "websocket:vic", "engineer:ATTACKER")

def test_validate_namespace_param():
    from nanobot.webui.ws_http import validate_namespace_param
    assert validate_namespace_param(derived="engineer:X", supplied="engineer:X")
    assert not validate_namespace_param(derived="engineer:X", supplied="engineer:Y")
    assert validate_namespace_param(derived="engineer:X", supplied=None)
```
- [ ] **Step 2: 跑确认失败** → FAIL (ImportError)
- [ ] **Step 3: 写实现** — `ws_http.py` 顶部：
```python
from nanobot.session.namespace import SessionNotAvailableError, derive_namespace

def derive_namespace_from_user_token(user_token: str) -> str | None:
    if not user_token:
        return None
    from robot_ai.library.auth import get_user_session_store
    session = get_user_session_store().check(user_token)
    if session is None:
        return None
    return derive_namespace(session["role"], session["user_id"])

def enforce_session_owner(session_manager, key: str, namespace: str) -> None:
    session_manager.assert_namespace_owner(key, namespace)

def validate_namespace_param(*, derived: str, supplied: str | None) -> bool:
    return supplied is None or supplied == derived

def _user_token_from_request(request) -> str:
    return (request.headers.get("X-Nanobot-User-Token", "") or "").strip()
```
每个 `_handle_session_*`（messages :803 / webui-thread :822 / file-preview / automations / delete :936），`check_api_token` 通过后插：
```python
        ns = derive_namespace_from_user_token(_user_token_from_request(request))
        if ns is None:
            return _http_error(401, "user token required")
        try:
            enforce_session_owner(self.session_manager, _decode_session_key(key), ns)
        except SessionNotAvailableError:
            return _http_error(404, "session not available")
```
（`_decode_session_key(key)`：handler 形参 key 是 URL 段；既有 handler 内已有反解——搜 handler 内 `decode`/`unquote`/`safe_filename` 定位并抽出 `_decode_session_key` 复用；形如 `websocket:<chat_id>`。）
- [ ] **Step 4: 修既有 WS 测试夹具** — `pytest tests/robot_ai/ -q` 找因 B4 auth 门控红的 WS 集成用例；在帧序列首帧补 `{type:"auth", user_token:<issue>}`，或夹具预置 `channel._connection_bindings[conn] = {...}`（最小改动）。
- [ ] **Step 5: 跑确认通过** — `pytest tests/robot_ai/test_ws_http_session_namespace.py tests/robot_ai/test_ws_auth_binding.py tests/robot_ai/test_session_namespace.py -q` → PASS；`ruff check nanobot/webui/ws_http.py` clean

---

## Task B7: list 派生过滤 —— 含 `session_list_index.py` 缓存行（修⑤）

**Files:** Modify `nanobot/webui/session_list_index.py`（缓存行加 ns + `list_webui_sessions(namespace)` + 版本 2→3）、`ws_http.py`（`_handle_sessions_list` :775 / `_sessions_list_payload` :783）；Test 追加到 `test_ws_http_session_namespace.py`。

- [ ] **Step 1: 写失败测试（追加）**
```python
def test_list_webui_sessions_filters_by_namespace(tmp_path):
    from nanobot.session.manager import SessionManager
    from nanobot.webui.session_list_index import list_webui_sessions
    mgr = SessionManager(tmp_path)
    mgr.stamp_namespace("websocket:mine", "engineer:AbCd1234")
    mgr.stamp_namespace("websocket:yours", "engineer:OTHER")
    rows = list_webui_sessions(mgr, namespace="engineer:AbCd1234")
    assert [r["key"] for r in rows] == ["websocket:mine"]

def test_index_version_bumped_forces_rebuild(tmp_path):
    import json as _json
    from nanobot.session.manager import SessionManager
    from nanobot.webui.session_list_index import _INDEX_VERSION, _INDEX_FILENAME, list_webui_sessions
    assert _INDEX_VERSION >= 3
    mgr = SessionManager(tmp_path)
    mgr.stamp_namespace("websocket:x", "engineer:AbCd1234")
    (mgr.sessions_dir / _INDEX_FILENAME).write_text(_json.dumps(
        {"version": 2, "sessions": [{"key": "websocket:x", "created_at": "x",
         "updated_at": "x", "title": "", "preview": "", "file": "x"}]}) + "\n", encoding="utf-8")
    rows = list_webui_sessions(mgr, namespace="engineer:AbCd1234")
    assert any(r["key"] == "websocket:x" for r in rows)  # 旧 v2 缓存被忽略重建
```
- [ ] **Step 2: 跑确认失败** → FAIL
- [ ] **Step 3: 写实现**
(a) `session_list_index.py`：`_INDEX_VERSION = 3`（:29）；`list_webui_sessions(session_manager, namespace: str | None = None)`（:36），`sorted` 前加：
```python
    if namespace is not None:
        sessions = [s for s in sessions if s.get("_namespace") == namespace]
```
`_public_row`（:134）加 `"_namespace": row.get("namespace")`；`_scan_session_row`（:266 返回 dict）加 `"namespace": (data.get("metadata", {}) or {}).get("namespace")`；`_indexed_row_for_session`（:244 返回 dict）加 `"namespace": (session.metadata or {}).get("namespace")`。（签名比对 `_indexed_row_matches_file` 不变——靠版本号一次性重建补 ns。）
(b) `ws_http.py` `_handle_sessions_list`（:775）：
```python
    async def _handle_sessions_list(self, request: WsRequest) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        ns = derive_namespace_from_user_token(_user_token_from_request(request))
        if ns is None:
            return _http_error(401, "user token required")
        supplied = None
        try:
            supplied = request.query.get("namespace")
        except Exception:
            supplied = None
        if not validate_namespace_param(derived=ns, supplied=supplied):
            return _http_error(400, "namespace mismatch")
        payload = await asyncio.to_thread(self._sessions_list_payload, ns)
        return _http_json_response(payload)
```
`_sessions_list_payload`（:783）签名加 `namespace`，透传 `list_webui_sessions(self.session_manager, namespace=namespace)`，`cleaned` 行剥离内部键：`row = {k: v for k, v in s.items() if k not in ("path", "_namespace")}`。
- [ ] **Step 4: 跑确认通过** → PASS
- [ ] **Step 5: 验证（不提交）** — `ruff check nanobot/webui/session_list_index.py nanobot/webui/ws_http.py` clean

---

## Task B8: `unified_session` fail-closed（真实 config 注入 + 真实构造测试，无 skip，修⑥）

**目标**：`unified_session` 为 `WebSocketChannel.__init__` **必填**形参（不传 → TypeError，即 fail-closed，绝不默认 False）；从真实 config 显式传入；启动 + new_chat 双查。**所有 `WebSocketChannel(` 调用点（生产 + tests/channels/）必须更新传值。**

**Files:** Modify `robot_ai/library/users.py`、`nanobot/channels/websocket.py`（`__init__` 必填形参 + 启动检查 + new_chat 检查）、生产构造点（`grep -rn "WebSocketChannel(" nanobot-main-1/nanobot/`）、`tests/channels/test_websocket_channel.py` 等（`_ch`/`_basic_handler` + 直接构造点）、`nanobot/cli/commands.py`；Create `tests/robot_ai/test_unified_session_failclosed.py`。

- [ ] **Step 1: 写失败测试（真实构造，无 skip）**
```python
# tests/robot_ai/test_unified_session_failclosed.py
import pytest

def test_unified_true_raises():
    from robot_ai.library.users import assert_unified_session_disabled
    with pytest.raises(RuntimeError, match="unified_session"):
        assert_unified_session_disabled(True)

def test_unified_false_ok():
    from robot_ai.library.users import assert_unified_session_disabled
    assert_unified_session_disabled(False)

def test_unified_none_ok():
    from robot_ai.library.users import assert_unified_session_disabled
    assert_unified_session_disabled(None)

def test_channel_init_failclosed_on_unified_true(tmp_path):
    """WebSocketChannel(unified_session=True) 构造即抛 RuntimeError（真实夹具）。"""
    from nanobot.bus.queue import MessageBus
    from nanobot.channels.websocket import WebSocketChannel, WebSocketConfig
    from nanobot.session.manager import SessionManager
    from nanobot.webui.gateway_services import build_gateway_services
    cfg = WebSocketConfig.model_validate({
        "enabled": True, "allowFrom": ["*"], "host": "127.0.0.1", "port": 29878,
        "path": "/ws", "websocketRequiresToken": False})
    gw = build_gateway_services(config=cfg, bus=MessageBus(),
        session_manager=SessionManager(tmp_path), static_dist_path=None,
        workspace_path=tmp_path, default_restrict_to_workspace=False,
        runtime_model_name=None, runtime_surface="browser", runtime_capabilities_overrides=None)
    with pytest.raises(RuntimeError, match="unified_session"):
        WebSocketChannel(cfg, MessageBus(), gateway=gw, unified_session=True)

def test_channel_init_requires_unified_session_kwarg(tmp_path):
    """缺 unified_session 形参 → TypeError（fail-closed，无默认值）。"""
    from nanobot.bus.queue import MessageBus
    from nanobot.channels.websocket import WebSocketChannel, WebSocketConfig
    from nanobot.webui.gateway_services import build_gateway_services
    cfg = WebSocketConfig.model_validate({
        "enabled": True, "allowFrom": ["*"], "host": "127.0.0.1", "port": 29879,
        "path": "/ws", "websocketRequiresToken": False})
    gw = build_gateway_services(config=cfg, bus=MessageBus(), session_manager=None,
        static_dist_path=None, workspace_path=tmp_path, default_restrict_to_workspace=False,
        runtime_model_name=None, runtime_surface="browser", runtime_capabilities_overrides=None)
    with pytest.raises(TypeError):
        WebSocketChannel(cfg, MessageBus(), gateway=gw)  # 漏 unified_session
```
- [ ] **Step 2: 跑确认失败** → FAIL (ImportError / 形参不存在)
- [ ] **Step 3: 写实现**
(a) `robot_ai/library/users.py` 新增：
```python
def assert_unified_session_disabled(unified_session: bool | None) -> None:
    """slice ②: unified_session=True is incompatible with per-user namespace
    isolation. Fail closed — never fall back to shared unified:default."""
    if unified_session:
        raise RuntimeError(
            "unified_session=True is incompatible with multi-user session "
            "namespace isolation (slice ②). Set agents.defaults.unified_session=false.")
```
(b) `WebSocketChannel.__init__`（:277）签名加**必填**形参（无默认值）：
```python
    def __init__(self, config: Any, bus: MessageBus, *, gateway: GatewayServices,
                 unified_session: bool):
```
体内 super().__init__ 前：
```python
        from robot_ai.library.users import assert_unified_session_disabled
        assert_unified_session_disabled(unified_session)
        self._unified_session = bool(unified_session)
```
(c) **更新所有 `WebSocketChannel(` 调用点传 `unified_session=`**：
- 生产构造点：`grep -rn "WebSocketChannel(" nanobot-main-1/nanobot/`（大概率 `nanobot/webui/gateway.py` 或 `nanobot/cli/commands.py`）→ 传 `unified_session=config.agents.defaults.unified_session`。
- `tests/channels/test_websocket_channel.py`：`_ch()`（:85）、`_basic_handler()` 间接、以及所有直接 `WebSocketChannel({...}, bus, gateway=...)`（:811/:837/:884/:907/:916/:931/:985/:1033/:1058/:1072/:1095/:1186/:1207/:1221/:1243/:1255 等）→ 加 `unified_session=False`（或 `unified_session=kw.get("unified_session", False)` 经 helper 透传）。
- `tests/channels/test_websocket_integration.py:46`、`test_websocket_http_routes.py:107`、`test_websocket_envelope_media.py:59`、`test_websocket_media_route.py:70` → 同。
- `tests/robot_ai/test_ws_auth_binding.py` 的 `_build_channel`：B4 版本**未传** `unified_session`（B4 尚未加该形参）；**B8 必须把 `_build_channel` 改为传 `unified_session=False`**，否则 B8 加必填形参后 B4/B5 的测试会 TypeError。
> 建议把 `_ch`/`_basic_handler` 加 `unified_session: bool = False` 形参透传，覆盖大多数；再 grep 补直接构造点。
(d) `_dispatch_bound_envelope` 的 `new_chat` 分支首行加：
```python
        if t == "new_chat":
            from robot_ai.library.users import assert_unified_session_disabled
            assert_unified_session_disabled(self._unified_session)
            ...
```
(e) `_run_gateway`（`nanobot/cli/commands.py`，搜 `initialize_user_identity(` 处）前加：
```python
    from robot_ai.library.users import assert_unified_session_disabled
    assert_unified_session_disabled(config.agents.defaults.unified_session)
```
- [ ] **Step 4: 跑确认通过** — `pytest tests/robot_ai/test_unified_session_failclosed.py tests/channels/test_websocket_channel.py -q` → PASS（含真实构造 fail-closed 两测试，**无 skip**）
- [ ] **Step 5: 验证（不提交）** — `grep -rn "WebSocketChannel(" nanobot-main-1/` 每处都传 `unified_session`（漏一处 → 启动/测试 TypeError）；`ruff check` clean

---

## Task B9: 全量回归 + ruff（收尾）

- [ ] **Step 1: robot_ai/config/cli 全量** — `cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/ nanobot/config/ nanobot/cli/ -q` → PASS，总数 = 525 + 新增。既有红 → 回 B6 Step 4 修夹具，不回退门控。
- [ ] **Step 2: session/webui/channel 既有测试** — `cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/ -q -k "session or websocket or ws_http or webui"` → 既有不因 ns 改动红（默认 `namespace=None` 行为不变；门控仅 user_token 存在时触发；B8 已更新所有 channel 调用点）。
- [ ] **Step 3: ruff 全量** — `cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m ruff check nanobot/ robot_ai/` → clean。
- [ ] **Step 4: 手工冒烟（可选）** — `nanobot gateway` → curl：`GET /webui/bootstrap` → `GET /api/auth/login`（`Authorization: Bearer <ws>` + `X-Nanobot-Robot-Body`）→ user_token → `GET /api/webui/sessions`（`Authorization: Bearer <ws>` + `X-Nanobot-User-Token: <user>`）只回该 user 会话。
- [ ] **Step 5: 不提交，记录** — Plan A 完成，不 git commit。更新 memory `b1a-backend-in-progress`：切片② 后端 Plan A 已实施 + 测试数 + 改动文件，待 Plan B（前端）。

---

## 自查（rev3 vs spec + 用户 5 修正）

| spec / 修正 | 任务 |
|---|---|
| §5 WS 1b 绑定 + 每帧验活 | B4 `resolve_bound_identity` 每帧调 |
| **①集成测试不得 skip** | B4/B5 用真实 `build_gateway_services` + `FrameConn` + `@pytest.mark.asyncio`；B8 真实构造；**全计划 0 处 `pytest.skip`** |
| **②删重复测试块** | B4 纯逻辑 7 函数各出现一次（rev3 重写核对） |
| **③auth 不建默认 chat** | B4 Step 3(d)：auth_ok 只发 role/user_id，不 mint/stamp/attach；会话仅 new_chat 创建；`test_auth_ok_carries_no_chat_and_creates_no_session` 断言 |
| **④new_chat 顺序** | B5 Step 3(b)：`scope→stamp→persist→attach→hydrate`；scope 失败不 stamp/不建会话（`test_new_chat_scope_failure_creates_no_session` 断言无 attached + 列表空） |
| **⑥gate 接入 bound 分支（rev4-①）** | B4 Step 3(d)：bound 分支解析 envelope 后调 `frame_gate_decision`，再 auth → REJECT_AND_CLOSE → `await close(1008)`；`test_reauth_while_bound_closes` 断言 auth→auth 关连接 |
| **⑤跨 ns 零副作用** | B5：message 断言 `bus.publish.assert_not_called()` + session 消息不变；fork 断言 list 不增；set_workspace_scope 断言 `persist_scope` 未调用他人 chat |
| §6.2 强制点 1-5 | B2/B3/B5/B6/B7 |
| §7 legacy 静默 404/session_not_available | B3 + B5（错误帧连接保持）+ B6 |
| §8 unified fail-closed | B8 |
| §11 撤销即踢 | B4 `test_revoked_token_next_frame_closes`（真实 spy 注入 revoke） |

**类型一致性**：`resolve_bound_identity`→`{role,user_id,namespace,user_token}`（B4/B5 一致）；`FrameDecision` B4 定义/测试引用一致；`_build_channel(tmp_path, *, bus, unified_session)` 跨 B4/B5/B8 一致；`derive_namespace_from_user_token`/`enforce_session_owner`/`validate_namespace_param`（B6 定义、B7 复用）；`list_webui_sessions(session_manager, namespace=None)`（B7 签名）；`assert_unified_session_disabled`（B8）；`WebSocketChannel(..., unified_session)` 必填（B8 改、B4/B5 测试已传）。

**0 处 `pytest.skip`、0 处占位 WebSocketChannel(...)。** 真实夹具来自 `tests/channels/test_websocket_channel.py` 的 `build_gateway_services` 模式。
