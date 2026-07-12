# Identity & Multi-User Management — Slice ① Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace B1a's single-engineer-password model with a unified multi-user identity backend — `users.json` store, in-memory `UserSessionStore` (8h, no refresh), `/api/auth/*` + `/api/users/*`, role authorization (operator/engineer), B1a credential migration, CLI bootstrap, B1a engineer API compat aliases, and full audit — with gateway token demoted to transport-only.

**Architecture:** `UserRegistry` (`robot_ai/library/users.py`, mirrors `VersionedCommandRegistry` outbox pattern) owns `users.json`; `UserSessionStore` (`auth.py`, replaces `EngineerTokenStore`) owns in-memory tokens bound to `{user_id, username, role, expiry}`; `process_auth_*` / `process_users_*` in `robot_routes.py` are the transport-agnostic layer; aiohttp `handle_*` + ws_http `_dispatch_*` mount them (GET+body-header on ws_http). B1a `EngineerTokenStore`/`process_engineer_login` are removed only after all 8 engineer endpoints switch to `_require_user_role(token_store, user_token, "engineer")`. Migration runs in a separate `initialize_user_identity()` after `initialize_robot_libraries()`.

**Tech Stack:** Python 3.11, aiohttp + websockets (ws_http GET-only), pydantic v2, pytest + pytest-asyncio, ruff (E/F/I/N/W, line 100).

**Spec:** `docs/superpowers/specs/2026-07-12-robot-engineer-identity-design.md`
**Prior:** B1a backend committed (`b02e3491`).

**No-git rule:** No `git add`/`commit`/`push`/`branch`. Each step ends with a **verify-checkpoint** (pytest + ruff), not a commit.

**Test env:** `.venv-robot-desktop/Scripts/python.exe -m pytest ... -q` and `... -m ruff check ...` (shell cwd is `nanobot-main-1`). Base python lacks pytest/aiohttp.

**Hard scope:** Backend only (no frontend — that's slice ②/③). Don't break B1a command-management business logic; only its auth layer changes (Task 7).

---

## File Structure

**New:**
- `robot_ai/library/users.py` — `normalize_username`, `UserRegistry` (storage + CRUD + outbox + drain), `migrate_users_if_needed`, `initialize_user_identity`, module constants `DEFAULT_USERS_PATH`.
- `tests/robot_ai/test_users.py` — `UserRegistry` + `normalize_username`.
- `tests/robot_ai/test_user_session.py` — `UserSessionStore`.
- `tests/robot_ai/test_auth_login.py` — `process_auth_login`/`logout`.
- `tests/robot_ai/test_users_api.py` — `process_users_*` + role gate.
- `tests/robot_ai/test_identity_migration.py` — migration + `initialize_user_identity`.
- `tests/robot_ai/test_identity_cli.py` — CLI bootstrap + `engineer set-password` alias.
- `tests/robot_ai/test_engineer_alias.py` — B1a login/header compat aliases.

**Modified:**
- `robot_ai/library/auth.py` — add `UserSessionStore` + `_USER_SESSION_STORE`/`get_user_session_store` (keep `EngineerTokenStore` until Task 7, then remove).
- `nanobot/api/robot_routes.py` — `_require_user_role`, `process_auth_login`/`logout`, `process_users_*`, `_user_deps`/`_user_token`/`_user_response`, `handle_auth_*`/`handle_users_*`, `register_auth_routes`/`register_users_routes`; switch 8 `process_engineer_*` + handlers + `_dispatch_robot_engineer_routes` to user-token+role (Task 7); remove `_require_engineer_token`/`process_engineer_login`/`logout` (Task 7).
- `nanobot/webui/ws_http.py` — `_dispatch_auth_routes`/`_dispatch_users_routes`; engineer dispatcher reads `X-Nanobot-User-Token` (Task 7).
- `nanobot/cli/commands.py` — `users_app` + `set-bootstrap-password`; `engineer set-password` deprecated alias; `_run_gateway` calls `initialize_user_identity()` after `initialize_robot_libraries()`.

---

## Task 1: `normalize_username` + `UserRegistry` (storage + CRUD + outbox)

**Files:** Create `robot_ai/library/users.py`; Test `tests/robot_ai/test_users.py`.

### Step 1: Write failing tests

Create `tests/robot_ai/test_users.py`:
```python
from __future__ import annotations

import json
from pathlib import Path

from robot_ai.library.users import UserRegistry, normalize_username


def test_normalize_username_strip_casefold() -> None:
    assert normalize_username("Admin") == "admin"
    assert normalize_username("  Alice  ") == "alice"
    assert normalize_username("ADMIN") == "admin"
    assert normalize_username(None) == ""  # type: ignore[arg-type]


def test_normalize_username_independent_of_normalize_id() -> None:
    """Changing normalize_username must NOT affect command-id normalization."""
    from robot_ai.library.models import normalize_id
    assert normalize_username("Pick Place") == "pick place"     # space preserved (casefold only)
    assert normalize_id("Pick Place") == "pick-place"            # command-id collapses whitespace


def _reg(tmp_path: Path) -> UserRegistry:
    return UserRegistry(tmp_path / "users.json", audit_path=tmp_path / "audit.jsonl")


def test_create_user(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    u = reg.create("Admin", "engineer", "pbkdf2_sha256$x$y$z")
    assert u["username"] == "Admin"
    assert u["role"] == "engineer"
    assert u["enabled"] is True
    assert u["user_id"]
    assert reg.get_by_username("admin")["user_id"] == u["user_id"]


def test_create_rejects_duplicate_normalized_username(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create("Admin", "engineer", "h1")
    try:
        reg.create(" ADMIN ", "operator", "h2")  # same normalization -> conflict
        assert False
    except ValueError:
        pass


def test_persists_and_reloads(tmp_path: Path) -> None:
    path = tmp_path / "users.json"
    UserRegistry(path, audit_path=tmp_path / "audit.jsonl").create("admin", "engineer", "h")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0"
    assert "pending_audits" in payload
    reg = UserRegistry(path, audit_path=tmp_path / "audit.jsonl")
    assert reg.get_by_username("admin") is not None


def test_outbox_drains_to_audit(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create("admin", "engineer", "h")
    lines = [ln for ln in (tmp_path / "audit.jsonl").read_text("utf-8").splitlines() if ln.strip()]
    assert any(json.loads(ln)["action"] == "user_create" for ln in lines)
    assert reg._data["pending_audits"] == []


def test_create_rejects_empty_username(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    for bad in ["", "   "]:
        try:
            reg.create(bad, "engineer", "h")
            assert False
        except ValueError:
            pass


def test_bootstrap_set_password_atomic_enable_and_password(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    u = reg.create("admin", "engineer", "placeholder", enabled=False)
    reg.bootstrap_set_password(u["user_id"], "newhash")
    reloaded = UserRegistry(reg.path, audit_path=reg.audit_path).get(u["user_id"])
    assert reloaded["enabled"] is True and reloaded["password_hash"] == "newhash"
    actions = [json.loads(ln)["action"]
               for ln in reg.audit_path.read_text("utf-8").splitlines() if ln.strip()]
    assert actions.count("user_bootstrap_password") == 1  # single atomic write


def test_enabled_engineer_count_and_last_engineer_protection(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    a = reg.create("admin", "engineer", "h")
    assert reg.enabled_engineer_count() == 1
    try:
        reg.update(a["user_id"], enabled=False)
        assert False
    except Exception as e:  # ConflictError-shaped
        assert "last_engineer" in str(e).lower() or "engineer" in str(e).lower()
```

### Step 2: Run to verify fail
`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_users.py -q`
Expected: FAIL — `ImportError: cannot import name 'UserRegistry'`.

### Step 3: Implement `users.py`

Create `robot_ai/library/users.py`:
```python
"""Multi-user identity store (schema 1.0).

Mirrors VersionedCommandRegistry: users.json + pending_audits outbox, atomic
writes, idempotent drain. Replaces B1a's single-engineer-password model.
"""
from __future__ import annotations

import json
import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any

from robot_ai.library.storage import atomic_write_json

DEFAULT_USERS_PATH = "~/.nanobot/robot_ai/users.json"
DEFAULT_AUDIT_PATH = "~/.nanobot/robot_ai/audit.jsonl"


def normalize_username(name: str | None) -> str:
    """Independent of normalize_id (command-id domain). strip + casefold only."""
    return (name or "").strip().casefold()


class LastEngineerError(Exception):
    """Raised when an op would leave zero enabled engineers."""


class UserRegistry:

    def __init__(self, path: str | Path, *, audit_path: str | Path | None = None) -> None:
        self.path = Path(path)
        self.audit_path = Path(os.path.expanduser(audit_path or DEFAULT_AUDIT_PATH))
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._data = {"schema_version": "1.0", "users": {}, "pending_audits": []}
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if raw.get("schema_version") != "1.0":
            raise ValueError(f"Expected users.json schema 1.0, got {raw.get('schema_version')!r}.")
        raw.setdefault("users", {})
        raw.setdefault("pending_audits", [])
        self._data = raw

    def _save(self) -> None:
        self._data["updated_at"] = datetime.now().isoformat()
        atomic_write_json(self.path, self._data)

    def _commit_with_audit(self, action: str, actor: dict[str, Any], target: dict[str, Any],
                            payload: dict[str, Any]) -> str:
        audit_id = secrets.token_urlsafe(16)
        entry = {
            "audit_id": audit_id, "action": action, "timestamp": datetime.now().isoformat(),
            "actor": actor.get("actor", "system"),
            "actor_user_id": actor.get("actor_user_id"),
            "actor_username": actor.get("actor_username"),
            "actor_role": actor.get("actor_role"),
            "target": target, "payload": payload,
        }
        self._data["pending_audits"].append(entry)
        self._save()
        self.drain_pending_audits()
        return audit_id

    def drain_pending_audits(self) -> list[str]:
        from robot_ai.library.migration import _audit_append
        pending = self._data.get("pending_audits", [])
        if not pending:
            return []
        existing: set[str] = set()
        if self.audit_path.exists():
            for line in self.audit_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    eid = json.loads(line).get("audit_id") or json.loads(line).get("migration_id")
                    if eid:
                        existing.add(eid)
                except json.JSONDecodeError:
                    continue
        written: list[str] = []
        remaining: list[dict[str, Any]] = []
        for item in pending:
            aid = item.get("audit_id")
            if aid and aid in existing:
                continue
            try:
                _audit_append(self.audit_path, item)
                written.append(aid)
            except OSError:
                remaining.append(item)
        self._data["pending_audits"] = remaining
        if len(remaining) != len(pending):
            self._save()
        return written

    # -- queries --

    def get(self, user_id: str) -> dict[str, Any] | None:
        return self._data["users"].get(user_id)

    def get_by_username(self, username: str) -> dict[str, Any] | None:
        target = normalize_username(username)
        for u in self._data["users"].values():
            if normalize_username(u["username"]) == target:
                return u
        return None

    def list_all(self) -> list[dict[str, Any]]:
        return [dict(u) for u in self._data["users"].values()]

    def enabled_engineer_count(self) -> int:
        return sum(1 for u in self._data["users"].values()
                   if u["role"] == "engineer" and u["enabled"])

    # -- mutations --

    def create(self, username: str, role: str, password_hash: str, *,
               enabled: bool = True, actor: dict[str, Any] | None = None) -> dict[str, Any]:
        if role not in ("operator", "engineer"):
            raise ValueError(f"Invalid role {role!r}.")
        if not normalize_username(username):
            raise ValueError("Username must not be empty.")
        if self.get_by_username(username) is not None:
            raise ValueError(f"Username {username!r} already exists.")
        now = datetime.now().isoformat()
        user_id = secrets.token_urlsafe(8)
        user = {"user_id": user_id, "username": username, "role": role,
                "password_hash": password_hash, "enabled": enabled,
                "created_at": now, "updated_at": now}
        self._data["users"][user_id] = user
        self._commit_with_audit(
            "user_create", actor or {"actor": "system"}, {"user_id": user_id},
            {"username": username, "role": role, "enabled": enabled})
        return user

    def update(self, user_id: str, *, enabled: bool | None = None, role: str | None = None,
               actor: dict[str, Any] | None = None) -> dict[str, Any]:
        user = self.get(user_id)
        if user is None:
            raise ValueError(f"User {user_id!r} not found.")
        # Last-engineer protection
        will_lose_engineer = (
            (enabled is False or (role == "operator" and user["role"] == "engineer"))
            and user["role"] == "engineer" and user["enabled"]
            and self.enabled_engineer_count() <= 1
        )
        if will_lose_engineer:
            raise LastEngineerError("Refusing: would leave zero enabled engineers.")
        before = {"enabled": user["enabled"], "role": user["role"]}
        if enabled is not None:
            user["enabled"] = enabled
        if role is not None:
            if role not in ("operator", "engineer"):
                raise ValueError(f"Invalid role {role!r}.")
            user["role"] = role
        user["updated_at"] = datetime.now().isoformat()
        action = ("user_disable" if enabled is False
                  else "user_enable" if enabled is True
                  else "user_role_change" if role is not None else "user_update")
        self._commit_with_audit(action, actor or {"actor": "system"},
                                 {"user_id": user_id}, {"before": before, "after": {"enabled": user["enabled"], "role": user["role"]}})
        return user

    def set_password(self, user_id: str, password_hash: str, *, actor: dict[str, Any] | None = None,
                     action: str = "user_password_change") -> dict[str, Any]:
        user = self.get(user_id)
        if user is None:
            raise ValueError(f"User {user_id!r} not found.")
        user["password_hash"] = password_hash
        user["updated_at"] = datetime.now().isoformat()
        self._commit_with_audit(action, actor or {"actor": "system"}, {"user_id": user_id}, {})
        return user

    def bootstrap_set_password(self, user_id: str, password_hash: str, *,
                                actor: dict[str, Any] | None = None) -> dict[str, Any]:
        """Atomic: set password hash AND enable in ONE write + ONE outbox/audit entry.
        Used by CLI set-bootstrap-password and the deprecated engineer set-password alias
        (spec §6: 'password + enable same atomic write')."""
        user = self.get(user_id)
        if user is None:
            raise ValueError(f"User {user_id!r} not found.")
        user["password_hash"] = password_hash
        user["enabled"] = True
        user["updated_at"] = datetime.now().isoformat()
        self._commit_with_audit("user_bootstrap_password", actor or {"actor": "system"},
                                 {"user_id": user_id}, {"enabled": True})
        return user
```

### Step 4: Run + checkpoint
`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_users.py -q && .venv-robot-desktop/Scripts/python.exe -m ruff check robot_ai/library/users.py`
Expected: all pass; ruff clean.

---

## Task 2: `UserSessionStore` (add; keep `EngineerTokenStore` until Task 7)

**Files:** Modify `robot_ai/library/auth.py`; Test `tests/robot_ai/test_user_session.py`.

### Step 1: Write failing tests

Create `tests/robot_ai/test_user_session.py`:
```python
from __future__ import annotations

from robot_ai.library.auth import UserSessionStore


def _user(uid="u1", username="admin", role="engineer"):
    return {"user_id": uid, "username": username, "role": role}


def test_issue_check_revoke() -> None:
    store = UserSessionStore(ttl_seconds=3600)
    tok = store.issue(_user())
    session = store.check(tok)
    assert session is not None and session["user_id"] == "u1" and session["role"] == "engineer"
    store.revoke(tok)
    assert store.check(tok) is None


def test_check_rejects_unknown() -> None:
    assert UserSessionStore().check("bogus") is None


def test_revoke_by_user_id() -> None:
    store = UserSessionStore()
    t1 = store.issue(_user("u1"))
    t2 = store.issue(_user("u1"))
    store.issue(_user("u2"))
    store.revoke_by_user_id("u1")
    assert store.check(t1) is None and store.check(t2) is None


def test_expired_rejected() -> None:
    import robot_ai.library.auth as auth
    store = UserSessionStore(ttl_seconds=3600)
    tok = store.issue(_user())
    store._sessions[tok] = {**store._sessions[tok], "expiry": auth.time.monotonic() - 1}
    assert store.check(tok) is None


def test_no_refresh_api() -> None:
    """UserSessionStore exposes no refresh method (no refresh tokens)."""
    assert not hasattr(UserSessionStore(), "refresh")
```

### Step 2: Run to verify fail
`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_user_session.py -q`
Expected: FAIL — `ImportError: cannot import name 'UserSessionStore'`.

### Step 3: Add `UserSessionStore` to `auth.py`

Append (before the singletons block) to `robot_ai/library/auth.py`:
```python
@dataclass
class UserSessionStore:
    """In-memory user session tokens bound to {user_id, username, role, expiry}.

    TTL 8h; no refresh. Replaces EngineerTokenStore (B1a) once endpoints migrate.
    """
    ttl_seconds: int = 8 * 3600
    _sessions: dict[str, dict] = field(default_factory=dict)

    def issue(self, user: dict) -> str:
        self._purge()
        token = secrets.token_urlsafe(32)
        self._sessions[token] = {
            "user_id": user["user_id"], "username": user["username"],
            "role": user["role"], "expiry": time.monotonic() + self.ttl_seconds,
        }
        return token

    def check(self, token: str) -> dict | None:
        self._purge()
        session = self._sessions.get(token)
        if session is None or time.monotonic() > session["expiry"]:
            self._sessions.pop(token, None)
            return None
        return session

    def revoke(self, token: str) -> None:
        self._sessions.pop(token, None)

    def revoke_by_user_id(self, user_id: str) -> None:
        for tok in [t for t, s in self._sessions.items() if s["user_id"] == user_id]:
            self._sessions.pop(tok, None)

    def _purge(self) -> None:
        now = time.monotonic()
        for tok in [t for t, s in self._sessions.items() if now > s["expiry"]]:
            self._sessions.pop(tok, None)
```
And add a singleton + accessor next to the existing ones (do NOT remove `EngineerTokenStore`/`_ENGINEER_TOKEN_STORE` yet — Task 7 does that):
```python
_USER_SESSION_STORE = UserSessionStore()


def get_user_session_store() -> "UserSessionStore":
    return _USER_SESSION_STORE
```

### Step 4: Run + checkpoint
`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_user_session.py -q && .venv-robot-desktop/Scripts/python.exe -m ruff check robot_ai/library/auth.py`
Expected: 5 passed; ruff clean. (B1a engineer tests still green — `EngineerTokenStore` still present.)

---

## Task 3: `process_auth_login` / `process_auth_logout`

**Files:** Modify `nanobot/api/robot_routes.py`; Test `tests/robot_ai/test_auth_login.py`.

### Step 1: Write failing tests

Create `tests/robot_ai/test_auth_login.py`:
```python
from __future__ import annotations

import json
from pathlib import Path

from robot_ai.library.auth import LoginThrottle, UserSessionStore, hash_password
from robot_ai.library.users import UserRegistry


def _seed(tmp_path: Path, *, username="admin", role="engineer", pw="s3cret", enabled=True):
    reg = UserRegistry(tmp_path / "users.json", audit_path=tmp_path / "audit.jsonl")
    user = reg.create(username, role, hash_password(pw, iterations=100_000), enabled=enabled)
    return reg, user


def test_login_success_issues_user_token_and_audits(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_auth_login
    _seed(tmp_path)
    store = UserSessionStore()
    status, body = process_auth_login(
        {"username": "admin", "password": "s3cret", "role": "engineer"},
        users_path=str(tmp_path / "users.json"), audit_path=str(tmp_path / "audit.jsonl"),
        token_store=store, throttle=LoginThrottle(), client_key="k")
    assert status == 200
    tok = body["data"]["user_token"]
    assert store.check(tok)["role"] == "engineer"
    entries = [json.loads(ln) for ln in (tmp_path / "audit.jsonl").read_text("utf-8").splitlines() if ln.strip()]
    assert any(e["action"] == "user_login" and e["result"] == "success" for e in entries)
    raw = (tmp_path / "audit.jsonl").read_text("utf-8")
    assert "s3cret" not in raw and tok not in raw
    assert any(e.get("actor") == f"user:{e['actor_user_id']}" and e.get("actor_role") == "engineer" for e in entries)


def test_login_wrong_password_401_no_token(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_auth_login
    _seed(tmp_path)
    store = UserSessionStore()
    before = len(store._sessions)
    status, _ = process_auth_login(
        {"username": "admin", "password": "wrong", "role": "engineer"},
        users_path=str(tmp_path / "users.json"), audit_path=str(tmp_path / "audit.jsonl"),
        token_store=store, throttle=LoginThrottle(), client_key="k")
    assert status == 401 and len(store._sessions) == before


def test_login_role_mismatch_401_no_user_leak(tmp_path: Path) -> None:
    """User exists as engineer but client asks role=operator -> 401 (not 403, no existence leak)."""
    from nanobot.api.robot_routes import process_auth_login
    _seed(tmp_path)
    status, _ = process_auth_login(
        {"username": "admin", "password": "s3cret", "role": "operator"},
        users_path=str(tmp_path / "users.json"), audit_path=str(tmp_path / "audit.jsonl"),
        token_store=UserSessionStore(), throttle=LoginThrottle(), client_key="k")
    assert status == 401


def test_login_disabled_403(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_auth_login
    _seed(tmp_path, enabled=False)
    status, _ = process_auth_login(
        {"username": "admin", "password": "s3cret", "role": "engineer"},
        users_path=str(tmp_path / "users.json"), audit_path=str(tmp_path / "audit.jsonl"),
        token_store=UserSessionStore(), throttle=LoginThrottle(), client_key="k")
    assert status == 403


def test_login_throttle_429_retry_after(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_auth_login
    _seed(tmp_path)
    throttle = LoginThrottle(max_attempts=3)
    store = UserSessionStore()
    for _ in range(3):
        process_auth_login({"username": "admin", "password": "x", "role": "engineer"},
                            users_path=str(tmp_path / "users.json"), audit_path=str(tmp_path / "audit.jsonl"),
                            token_store=store, throttle=throttle, client_key="k")
    status, body = process_auth_login({"username": "admin", "password": "x", "role": "engineer"},
                                       users_path=str(tmp_path / "users.json"), audit_path=str(tmp_path / "audit.jsonl"),
                                       token_store=store, throttle=throttle, client_key="k")
    assert status == 429 and body["data"]["retry_after"] >= 1


def test_login_success_audit_failure_fail_closed_503(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_auth_login
    _seed(tmp_path)
    blocker = tmp_path / "b"; blocker.write_text("x", encoding="utf-8")
    status, body = process_auth_login(
        {"username": "admin", "password": "s3cret", "role": "engineer"},
        users_path=str(tmp_path / "users.json"), audit_path=str(blocker / "audit.jsonl"),
        token_store=UserSessionStore(), throttle=LoginThrottle(), client_key="k")
    assert status == 503 and "user_token" not in body.get("data", {})


def test_logout_revokes_first_then_best_effort_audit(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_auth_login, process_auth_logout
    _seed(tmp_path)
    store = UserSessionStore()
    _, body = process_auth_login({"username": "admin", "password": "s3cret", "role": "engineer"},
                                  users_path=str(tmp_path / "users.json"), audit_path=str(tmp_path / "audit.jsonl"),
                                  token_store=store, throttle=LoginThrottle(), client_key="k")
    tok = body["data"]["user_token"]
    blocker = tmp_path / "b"; blocker.write_text("x", encoding="utf-8")
    status, _ = process_auth_logout(tok, token_store=store, audit_path=str(blocker / "audit.jsonl"))
    assert status == 200 and store.check(tok) is None
```

### Step 2: Run to verify fail
`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_auth_login.py -q`
Expected: FAIL — `ImportError: cannot import name 'process_auth_login'`.

### Step 3: Implement `process_auth_login` / `process_auth_logout`

Append to `nanobot/api/robot_routes.py` (after `_best_effort_audit`):
```python
def _resolve_users_path(users_path: str | None) -> str:
    return os.path.expanduser(users_path or "~/.nanobot/robot_ai/users.json")


def _actor_dict(user: dict[str, Any]) -> dict[str, Any]:
    return {"actor": f"user:{user['user_id']}", "actor_user_id": user["user_id"],
            "actor_username": user["username"], "actor_role": user["role"]}


def process_auth_login(body: Any, *, users_path: str | None = None, audit_path: str | None = None,
                       token_store, throttle, client_key: str | None = None) -> tuple[int, dict[str, Any]]:
    """Unified login: throttle -> verify -> fail-closed success audit -> issue user token."""
    import secrets
    from robot_ai.library.auth import verify_password
    from robot_ai.library.migration import _audit_append
    from robot_ai.library.users import UserRegistry

    key = client_key or "anon"
    if throttle.is_throttled(key):
        return 429, {"ok": False, "data": {"retry_after": throttle.retry_after(key)},
                     "error": {"code": "too_many_attempts", "message": "Too many login attempts."}}

    body = body or {}
    username = str(body.get("username", ""))
    password = str(body.get("password", ""))
    role = str(body.get("role", ""))
    if role not in ("operator", "engineer"):
        throttle.record_failure(key)
        _best_effort_audit(_resolve_audit_path(audit_path),
                           {"action": "user_login", "actor": "anon", "result": "failure",
                            "reason": "bad_role", "audit_id": secrets.token_urlsafe(16),
                            "timestamp": _now_iso()})
        return 401, {"error": {"code": "invalid_credentials", "message": "Invalid credentials."}}

    reg = UserRegistry(_resolve_users_path(users_path), audit_path=_resolve_audit_path(audit_path))
    user = reg.get_by_username(username)
    if user is None or user["role"] != role:
        throttle.record_failure(key)
        _best_effort_audit(_resolve_audit_path(audit_path),
                           {"action": "user_login", "actor": "anon", "result": "failure",
                            "reason": "bad_user_or_role", "audit_id": secrets.token_urlsafe(16),
                            "timestamp": _now_iso()})
        return 401, {"error": {"code": "invalid_credentials", "message": "Invalid credentials."}}
    if not user["enabled"]:
        return 403, {"error": {"code": "user_disabled", "message": "Account is disabled."}}
    if not verify_password(password, user["password_hash"]):
        throttle.record_failure(key)
        _best_effort_audit(_resolve_audit_path(audit_path),
                           {"action": "user_login", "actor": f"user:{user['user_id']}",
                            "actor_user_id": user["user_id"], "actor_username": user["username"],
                            "actor_role": user["role"], "result": "failure", "reason": "bad_password",
                            "audit_id": secrets.token_urlsafe(16), "timestamp": _now_iso()})
        return 401, {"error": {"code": "invalid_credentials", "message": "Invalid credentials."}}

    throttle.reset(key)
    token = token_store.issue({"user_id": user["user_id"], "username": user["username"], "role": user["role"]})
    success = {"action": "user_login", **_actor_dict(user), "result": "success",
               "audit_id": secrets.token_urlsafe(16), "timestamp": _now_iso()}
    try:
        _audit_append(_resolve_audit_path(audit_path), success)
    except OSError:
        token_store.revoke(token)
        return 503, {"error": {"code": "audit_write_failed", "message": "Login audit could not be recorded."}}
    return 200, {"ok": True,
                 "data": {"user_token": token, "expires_in": token_store.ttl_seconds,
                          "user": {"user_id": user["user_id"], "username": user["username"], "role": user["role"]}}}


def process_auth_logout(user_token, *, token_store, audit_path: str | None = None,
                        session: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    """Revoke FIRST (safety > audit), then best-effort audit."""
    import secrets
    from robot_ai.library.migration import _audit_append
    token_store.revoke(user_token or "")
    actor = (_actor_dict(session) if session
             else {"actor": "user:?", "actor_role": None})
    try:
        _audit_append(_resolve_audit_path(audit_path),
                      {"action": "user_logout", **actor, "result": "success",
                       "audit_id": secrets.token_urlsafe(16), "timestamp": _now_iso()})
    except OSError:
        pass
    return 200, {"ok": True, "data": {"revoked": True}}
```

### Step 4: Run + checkpoint
`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_auth_login.py -q && .venv-robot-desktop/Scripts/python.exe -m ruff check nanobot/api/robot_routes.py`
Expected: all pass; ruff clean.

---

## Task 4: `process_users_*` (CRUD + outbox + last-engineer + session revoke + self_id guard)

**Files:** Modify `nanobot/api/robot_routes.py`; Test `tests/robot_ai/test_users_api.py`.

### Step 1: Write failing tests

Create `tests/robot_ai/test_users_api.py`:
```python
from __future__ import annotations

from pathlib import Path

from robot_ai.library.auth import UserSessionStore, hash_password
from robot_ai.library.users import UserRegistry


def _boot(tmp_path: Path):
    reg = UserRegistry(tmp_path / "users.json", audit_path=tmp_path / "audit.jsonl")
    admin = reg.create("admin", "engineer", hash_password("pw", iterations=100_000))
    op = reg.create("operator", "operator", hash_password("pw", iterations=100_000))
    store = UserSessionStore()
    admin_tok = store.issue({"user_id": admin["user_id"], "username": "admin", "role": "engineer"})
    op_tok = store.issue({"user_id": op["user_id"], "username": "operator", "role": "operator"})
    return reg, admin, admin_tok, op_tok


def _actor_of(store, tok):
    s = store.check(tok); return {"actor": f"user:{s['user_id']}", "actor_user_id": s["user_id"],
                                  "actor_username": s["username"], "actor_role": s["role"]}


def test_list_excludes_password_hash(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_users_list
    reg, admin, atok, _ = _boot(tmp_path)
    s, body = process_users_list(users_path=str(tmp_path / "users.json"),
                                  token_store=UserSessionStore.__new__(UserSessionStore), user_token=atok)
    # (token_store here is just for the gate; use the real store:)
    store = UserSessionStore(); store._sessions[atok] = store.check(atok) or {}
    s, body = process_users_list(users_path=str(tmp_path / "users.json"), token_store=store, user_token=atok)
    assert s == 200
    assert all("password_hash" not in u for u in body["data"]["users"])


def test_create_and_duplicate(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_users_create
    reg, admin, atok, _ = _boot(tmp_path)
    store = UserSessionStore()
    s, body = process_users_create({"username": "Bob", "password": "p", "role": "engineer"},
                                    users_path=str(tmp_path / "users.json"), audit_path=str(tmp_path / "audit.jsonl"),
                                    token_store=store, user_token=atok, actor=_actor_of(store, atok))
    assert s == 201 and body["data"]["username"] == "Bob"
    s, _ = process_users_create({"username": "bob", "password": "p", "role": "engineer"},
                                  users_path=str(tmp_path / "users.json"), audit_path=str(tmp_path / "audit.jsonl"),
                                  token_store=store, user_token=atok, actor=_actor_of(store, atok))
    assert s == 409  # normalized dup


def test_disable_last_engineer_blocked(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_users_patch
    reg, admin, atok, _ = _boot(tmp_path)
    store = UserSessionStore()
    s, _ = process_users_patch(admin["user_id"], {"enabled": False},
                                users_path=str(tmp_path / "users.json"), audit_path=str(tmp_path / "audit.jsonl"),
                                token_store=store, user_token=atok, actor=_actor_of(store, atok))
    assert s == 409  # last engineer


def test_reset_password_revokes_target_sessions(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_users_reset_password
    reg, admin, atok, optok = _boot(tmp_path)
    store = UserSessionStore()
    s, _ = process_users_reset_password(reg.get_by_username("operator")["user_id"], {"new_password": "n"},
                                         users_path=str(tmp_path / "users.json"), audit_path=str(tmp_path / "audit.jsonl"),
                                         token_store=store, user_token=atok, actor=_actor_of(store, atok))
    assert s == 200 and store.check(optok) is None  # operator session revoked


def test_reset_password_rejects_self(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_users_reset_password
    reg, admin, atok, _ = _boot(tmp_path)
    store = UserSessionStore()
    s, body = process_users_reset_password(admin["user_id"], {"new_password": "n"},
                                            users_path=str(tmp_path / "users.json"), audit_path=str(tmp_path / "audit.jsonl"),
                                            token_store=store, user_token=atok, actor=_actor_of(store, atok))
    assert s == 409 and body["error"]["code"] == "use_me_password"


def test_me_password_verifies_old_and_revokes_self(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_users_me_password
    reg, admin, atok, _ = _boot(tmp_path)
    store = UserSessionStore()
    s, _ = process_users_me_password({"old_password": "wrong", "new_password": "n"},
                                      users_path=str(tmp_path / "users.json"), audit_path=str(tmp_path / "audit.jsonl"),
                                      token_store=store, user_token=atok, actor=_actor_of(store, atok))
    assert s == 401
    s, _ = process_users_me_password({"old_password": "pw", "new_password": "n"},
                                      users_path=str(tmp_path / "users.json"), audit_path=str(tmp_path / "audit.jsonl"),
                                      token_store=store, user_token=atok, actor=_actor_of(store, atok))
    assert s == 200 and store.check(atok) is None  # self revoked


def test_operator_forbidden_from_users_admin(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_users_create
    reg, admin, atok, optok = _boot(tmp_path)
    store = UserSessionStore()
    s, _ = process_users_create({"username": "x", "password": "p", "role": "engineer"},
                                  users_path=str(tmp_path / "users.json"), audit_path=str(tmp_path / "audit.jsonl"),
                                  token_store=store, user_token=optok, actor=_actor_of(store, optok))
    assert s == 403
```

### Step 2: Run to verify fail
`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_users_api.py -q`
Expected: FAIL — `ImportError: cannot import name 'process_users_list'`.

### Step 3: Implement `_require_user_role` + `process_users_*`

Append to `nanobot/api/robot_routes.py`:
```python
def _require_user_role(token_store, user_token, role: str | None) -> tuple[bool, dict, dict | None]:
    """Returns (ok, error_body, session). session=None on failure. role=None = any authenticated user."""
    session = token_store.check(user_token) if user_token else None
    if session is None:
        return False, {"error": {"code": "unauthorized", "message": "Valid user token required."}}, None
    if role is not None and session["role"] != role:
        return False, {"error": {"code": "forbidden", "message": f"role={role!r} required."}}, None
    return True, {}, session


def process_users_list(*, users_path: str | None = None, token_store=None, user_token=None):
    ok, err, _ = _require_user_role(token_store, user_token, "engineer")
    if not ok:
        return 403 if err["error"]["code"] == "forbidden" else 401, err
    from robot_ai.library.users import UserRegistry
    users = [{"user_id": u["user_id"], "username": u["username"], "role": u["role"],
              "enabled": u["enabled"], "created_at": u["created_at"], "updated_at": u["updated_at"]}
             for u in UserRegistry(_resolve_users_path(users_path)).list_all()]
    return 200, {"ok": True, "data": {"users": users}}


def process_users_create(body, *, users_path=None, audit_path=None, token_store=None,
                          user_token=None, actor=None):
    ok, err, _ = _require_user_role(token_store, user_token, "engineer")
    if not ok:
        return 403 if err["error"]["code"] == "forbidden" else 401, err
    from robot_ai.library.auth import hash_password
    from robot_ai.library.users import UserRegistry
    body = body or {}
    try:
        user = UserRegistry(_resolve_users_path(users_path), audit_path=_resolve_audit_path(audit_path)).create(
            str(body.get("username", "")), str(body.get("role", "")),
            hash_password(str(body.get("password", ""))), actor=actor)
    except ValueError as e:
        return 409, {"error": {"code": "user_exists", "message": str(e)}}
    return 201, {"ok": True, "data": {k: v for k, v in user.items() if k != "password_hash"}}


def process_users_patch(user_id, body, *, users_path=None, audit_path=None, token_store=None,
                         user_token=None, actor=None):
    ok, err, _ = _require_user_role(token_store, user_token, "engineer")
    if not ok:
        return 403 if err["error"]["code"] == "forbidden" else 401, err
    from robot_ai.library.users import LastEngineerError, UserRegistry
    body = body or {}
    reg = UserRegistry(_resolve_users_path(users_path), audit_path=_resolve_audit_path(audit_path))
    try:
        user = reg.update(user_id, enabled=body.get("enabled"), role=body.get("role"), actor=actor)
    except LastEngineerError as e:
        return 409, {"error": {"code": "last_engineer_protected", "message": str(e)}}
    except ValueError as e:
        return 404, {"error": {"code": "user_not_found", "message": str(e)}}
    if body.get("enabled") is False or body.get("role") is not None:
        token_store.revoke_by_user_id(user_id)  # disable or role-change -> kick
    return 200, {"ok": True, "data": {k: v for k, v in user.items() if k != "password_hash"}}


def process_users_reset_password(user_id, body, *, users_path=None, audit_path=None, token_store=None,
                                  user_token=None, actor=None):
    ok, err, session = _require_user_role(token_store, user_token, "engineer")
    if not ok:
        return 403 if err["error"]["code"] == "forbidden" else 401, err
    if session["user_id"] == user_id:
        return 409, {"error": {"code": "use_me_password",
                                "message": "Use /api/users/me/password to change your own password."}}
    from robot_ai.library.auth import hash_password
    from robot_ai.library.users import UserRegistry
    try:
        UserRegistry(_resolve_users_path(users_path), audit_path=_resolve_audit_path(audit_path)).set_password(
            user_id, hash_password(str((body or {}).get("new_password", ""))), actor=actor,
            action="user_password_reset")
    except ValueError as e:
        return 404, {"error": {"code": "user_not_found", "message": str(e)}}
    token_store.revoke_by_user_id(user_id)
    return 200, {"ok": True, "data": {"reset": user_id}}


def process_users_me_password(body, *, users_path=None, audit_path=None, token_store=None,
                               user_token=None, actor=None):
    ok, err, session = _require_user_role(token_store, user_token, None)  # any authenticated
    if not ok:
        return 401, err
    from robot_ai.library.auth import hash_password, verify_password
    from robot_ai.library.users import UserRegistry
    body = body or {}
    reg = UserRegistry(_resolve_users_path(users_path), audit_path=_resolve_audit_path(audit_path))
    user = reg.get(session["user_id"])
    if user is None or not verify_password(str(body.get("old_password", "")), user["password_hash"]):
        return 401, {"error": {"code": "invalid_credentials", "message": "Old password incorrect."}}
    reg.set_password(session["user_id"], hash_password(str(body.get("new_password", ""))), actor=actor)
    token_store.revoke_by_user_id(session["user_id"])  # self revoked -> re-login
    return 200, {"ok": True, "data": {"changed": True}}
```

### Step 4: Run + checkpoint
`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_users_api.py -q && .venv-robot-desktop/Scripts/python.exe -m ruff check nanobot/api/robot_routes.py`
Expected: all pass; ruff clean.

---

## Task 5: Migration + `initialize_user_identity` + CLI bootstrap

**Files:** Modify `robot_ai/library/users.py`, `nanobot/cli/commands.py`; Test `tests/robot_ai/test_identity_migration.py`, `tests/robot_ai/test_identity_cli.py`.

### Step 1: Write failing tests (migration)

Create `tests/robot_ai/test_identity_migration.py`:
```python
from __future__ import annotations

import json
from pathlib import Path


def _b1a_config(tmp_path: Path, *, engineer_hash="h_admin", gateway_secret="legacy-secret"):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"robotAi": {"engineer": {"passwordHash": engineer_hash,
                                                          "pbkdf2Iterations": 200_000}}}), encoding="utf-8")
    return cfg


def test_migrate_creates_admin_from_b1a_hash_and_operator_from_secret(tmp_path: Path) -> None:
    from robot_ai.library.users import migrate_users_if_needed
    cfg = _b1a_config(tmp_path)
    users = tmp_path / "users.json"
    migrated = migrate_users_if_needed(users_path=str(users), b1a_config_path=cfg,
                                        gateway_secret="legacy-secret", audit_path=str(tmp_path / "a.jsonl"))
    assert migrated is True
    data = json.loads(users.read_text("utf-8"))
    admin = next(u for u in data["users"].values() if u["username"] == "admin")
    assert admin["role"] == "engineer" and admin["enabled"] is True and admin["password_hash"] == "h_admin"
    op = next(u for u in data["users"].values() if u["username"] == "operator")
    assert op["role"] == "operator" and op["enabled"] is True
    from robot_ai.library.auth import verify_password
    assert verify_password("legacy-secret", op["password_hash"]) is True


def test_migrate_disabled_operator_placeholder_when_no_secret(tmp_path: Path) -> None:
    from robot_ai.library.users import migrate_users_if_needed
    cfg = _b1a_config(tmp_path)
    users = tmp_path / "users.json"
    migrate_users_if_needed(users_path=str(users), b1a_config_path=cfg,
                             gateway_secret="", audit_path=str(tmp_path / "a.jsonl"))  # no secret
    data = json.loads(users.read_text("utf-8"))
    op = next(u for u in data["users"].values() if u["username"] == "operator")
    assert op["enabled"] is False  # placeholder, NOT hash of any API token
    assert op["password_hash"] != ""


def test_migrate_admin_disabled_placeholder_when_no_b1a_hash(tmp_path: Path) -> None:
    from robot_ai.library.users import migrate_users_if_needed
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"robotAi": {"engineer": {"passwordHash": "", "pbkdf2Iterations": 200_000}}}),
                   encoding="utf-8")
    users = tmp_path / "users.json"
    migrate_users_if_needed(users_path=str(users), b1a_config_path=cfg,
                             gateway_secret="", audit_path=str(tmp_path / "a.jsonl"))
    admin = next(u for u in json.loads(users.read_text("utf-8"))["users"].values() if u["username"] == "admin")
    assert admin["enabled"] is False


def test_migrate_idempotent(tmp_path: Path) -> None:
    from robot_ai.library.users import migrate_users_if_needed
    cfg = _b1a_config(tmp_path)
    users = tmp_path / "users.json"
    migrate_users_if_needed(users_path=str(users), b1a_config_path=cfg, gateway_secret="s",
                             audit_path=str(tmp_path / "a.jsonl"))
    assert migrate_users_if_needed(users_path=str(users), b1a_config_path=cfg, gateway_secret="s",
                                    audit_path=str(tmp_path / "a.jsonl")) is False


def test_initialize_user_identity_separate_from_libraries(tmp_path: Path, monkeypatch) -> None:
    """initialize_user_identity is its own function (identity domain), idempotent + drains."""
    from unittest.mock import patch
    from robot_ai.library.users import initialize_user_identity
    cfg = _b1a_config(tmp_path)
    users = tmp_path / "users.json"; audit = tmp_path / "a.jsonl"
    with patch("robot_ai.library.users.UserRegistry.drain_pending_audits", return_value=[]) as m:
        initialize_user_identity(users_path=str(users), audit_path=str(audit),
                                  b1a_config_path=cfg, gateway_secret="s")
        assert m.call_count == 1
    assert json.loads(users.read_text("utf-8"))["schema_version"] == "1.0"
```

### Step 2: Run to verify fail
`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_identity_migration.py -q`
Expected: FAIL — `ImportError: cannot import name 'migrate_users_if_needed'`.

### Step 3: Implement migration + `initialize_user_identity`

Append to `robot_ai/library/users.py`:
```python
def migrate_users_if_needed(*, users_path: str | Path | None = None, b1a_config_path=None,
                             gateway_secret: str = "", audit_path: str | Path | None = None) -> bool:
    """Create users.json on first run from B1a engineer hash + gateway secret. Idempotent.

    admin (engineer): B1a password_hash if present, else disabled placeholder (CLI bootstrap).
    operator: hash_password(secret) if secret readable, else disabled placeholder.
    NEVER uses a gateway API token as a password."""
    import secrets as _secrets

    upath = Path(os.path.expanduser(users_path or DEFAULT_USERS_PATH))
    if upath.exists():
        return False
    apath = Path(os.path.expanduser(audit_path or DEFAULT_AUDIT_PATH))

    admin_hash = ""
    if b1a_config_path is not None:
        try:
            from nanobot.config.loader import load_config
            admin_hash = (load_config(Path(b1a_config_path)).robot_ai.engineer.password_hash or "")
        except Exception:
            admin_hash = ""

    reg = UserRegistry(upath, audit_path=apath)
    reg.create("admin", "engineer",
               admin_hash if admin_hash else _secrets.token_urlsafe(16),
               enabled=bool(admin_hash),
               actor={"actor": "system:migration", "actor_role": "system"})
    if gateway_secret:  # persisted config field token_issue_secret/token, NOT an API token
        from robot_ai.library.auth import hash_password
        reg.create("operator", "operator", hash_password(gateway_secret), enabled=True,
                   actor={"actor": "system:migration", "actor_role": "system"})
    else:
        reg.create("operator", "operator", _secrets.token_urlsafe(16), enabled=False,
                   actor={"actor": "system:migration", "actor_role": "system"})
    reg.drain_pending_audits()
    from robot_ai.library.migration import _audit_append
    try:
        _audit_append(apath, {"action": "users_migration", "actor": "system:migration",
                              "actor_role": "system", "audit_id": _secrets.token_urlsafe(16),
                              "timestamp": datetime.now().isoformat(),
                              "payload": {"admin_from_b1a_hash": bool(admin_hash),
                                          "operator_from_secret": bool(gateway_secret)}})
    except OSError:
        pass
    return True


def initialize_user_identity(*, users_path: str | Path | None = None,
                              audit_path: str | Path | None = None,
                              b1a_config_path=None, gateway_secret: str = "") -> None:
    """Identity-domain startup: migrate_users_if_needed -> drain. Idempotent. Separate from
    initialize_robot_libraries (command-library domain). Called by _run_gateway AFTER it."""
    upath = os.path.expanduser(users_path or DEFAULT_USERS_PATH)
    apath = os.path.expanduser(audit_path or DEFAULT_AUDIT_PATH)
    migrate_users_if_needed(users_path=upath, b1a_config_path=b1a_config_path,
                             gateway_secret=gateway_secret, audit_path=apath)
    UserRegistry(upath, audit_path=apath).drain_pending_audits()
```

### Step 4: Run migration tests + checkpoint
`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_identity_migration.py -q && .venv-robot-desktop/Scripts/python.exe -m ruff check robot_ai/library/users.py`
Expected: all pass; ruff clean.

### Step 5: Write failing tests (CLI bootstrap)

Create `tests/robot_ai/test_identity_cli.py`:
```python
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner


def _disabled_admin_install(tmp_path: Path) -> Path:
    """A users.json where admin is a disabled placeholder (no B1a hash)."""
    from robot_ai.library.users import UserRegistry
    reg = UserRegistry(tmp_path / "users.json", audit_path=tmp_path / "a.jsonl")
    reg.create("admin", "engineer", "placeholder", enabled=False,
               actor={"actor": "system:migration", "actor_role": "system"})
    return tmp_path / "users.json"


def test_set_bootstrap_password_enables_admin(tmp_path: Path) -> None:
    from nanobot.cli.commands import users_app
    users_json = _disabled_admin_install(tmp_path)
    runner = CliRunner()
    with patch("getpass.getpass", side_effect=["newpw", "newpw"]):
        result = runner.invoke(users_app, ["set-bootstrap-password", "--username", "admin",
                                            "--users-path", str(users_json),
                                            "--audit-path", str(tmp_path / "a.jsonl")])
    assert result.exit_code == 0, result.output
    admin = next(u for u in json.loads(users_json.read_text("utf-8"))["users"].values()
                 if u["username"] == "admin")
    assert admin["enabled"] is True
    from robot_ai.library.auth import verify_password
    assert verify_password("newpw", admin["password_hash"]) is True


def test_set_bootstrap_password_no_password_arg(tmp_path: Path) -> None:
    """--password is NOT accepted (password must not appear in args)."""
    from nanobot.cli.commands import users_app
    users_json = _disabled_admin_install(tmp_path)
    runner = CliRunner()
    result = runner.invoke(users_app, ["set-bootstrap-password", "--username", "admin",
                                        "--password", "x", "--users-path", str(users_json),
                                        "--audit-path", str(tmp_path / "a.jsonl")])
    assert result.exit_code != 0  # unknown option rejected


def test_set_bootstrap_password_unknown_username(tmp_path: Path) -> None:
    from nanobot.cli.commands import users_app
    users_json = _disabled_admin_install(tmp_path)
    runner = CliRunner()
    with patch("getpass.getpass", side_effect=["p", "p"]):
        result = runner.invoke(users_app, ["set-bootstrap-password", "--username", "ghost",
                                            "--users-path", str(users_json),
                                            "--audit-path", str(tmp_path / "a.jsonl")])
    assert result.exit_code != 0
```

### Step 6: Run to verify fail
`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_identity_cli.py -q`
Expected: FAIL — `ImportError: cannot import name 'users_app'`.

### Step 7: Implement `users_app` + `set-bootstrap-password`

In `nanobot/cli/commands.py`, after the `engineer_app` block, add:
```python
users_app = typer.Typer(help="User account bootstrap (identity layer).")
app.add_typer(users_app, name="users")


@users_app.command("set-bootstrap-password")
def users_set_bootstrap_password(
    username: str = typer.Option(..., "--username", help="Existing username to enable/reset"),
    users_path: str | None = typer.Option(None, "--users-path", help="Path to users.json"),
    audit_path: str | None = typer.Option(None, "--audit-path", help="Path to audit.jsonl"),
) -> None:
    """Enable + set password for an existing user (getpass only; no --password arg)."""
    from pathlib import Path as _Path
    from robot_ai.library.auth import hash_password
    from robot_ai.library.users import UserRegistry
    upath = _Path(users_path).expanduser() if users_path else _Path("~/.nanobot/robot_ai/users.json").expanduser()
    apath = _Path(audit_path).expanduser() if audit_path else _Path("~/.nanobot/robot_ai/audit.jsonl").expanduser()
    reg = UserRegistry(upath, audit_path=apath)
    user = reg.get_by_username(username)
    if user is None:
        console.print(f"[red]User {username!r} not found.[/red]")
        raise typer.Exit(1)
    pw = getpass.getpass(f"New password for {username}: ")
    pw2 = getpass.getpass("Confirm password: ")
    if pw != pw2:
        console.print("[red]Passwords do not match.[/red]")
        raise typer.Exit(1)
    if not pw:
        console.print("[red]Password must not be empty.[/red]")
        raise typer.Exit(1)
    reg.bootstrap_set_password(user["user_id"], hash_password(pw),
                                actor={"actor": "system:cli", "actor_role": "system"})
    console.print(f"[green]Password set and {username!r} enabled.[/green]")
```

### Step 8: Wire `_run_gateway` with the REAL gateway secret + config path

`initialize_user_identity()` MUST receive the actual gateway secret and config path — empty params would make the operator migration always see an empty secret and create a disabled placeholder **even when a real secret exists**.

Add helper `_read_gateway_secret(config)` in `nanobot/cli/commands.py` — same source as `ws_http._handle_bootstrap` (`self.config.token_issue_secret or self.config.token`, ws_http.py:327), i.e. the **websocket channel config** (`nanobot/channels/websocket.py:88/90` `WebsocketChannelConfig`):
```python
def _read_gateway_secret(config: Config) -> str:
    """Gateway bootstrap secret for operator migration (same source as
    ws_http._handle_bootstrap). '' when unset -> operator becomes a disabled placeholder."""
    ws = getattr(config.channels, "websocket", None)
    if ws is None:
        ws = (getattr(config.channels, "model_extra", None) or {}).get("websocket")  # extra='allow'
    if ws is None:
        return ""
    return ((getattr(ws, "token_issue_secret", "") or "").strip()
            or (getattr(ws, "token", "") or "").strip())
```
(The implementer verifies the websocket-channel-config access path on `config.channels` — `ChannelsConfig` uses `extra='allow'`; the config may be an attribute or in `model_extra`. The secret source MUST match `ws_http.py:327` exactly. If neither `token_issue_secret` nor `token` is set, return `''` — operator becomes a disabled placeholder; NEVER fall back to an API token.)

Then in `_run_gateway`, immediately after `initialize_robot_libraries()` (line ~921), add:
```python
    from robot_ai.library.users import initialize_user_identity
    from nanobot.config.loader import get_config_path
    initialize_user_identity(b1a_config_path=get_config_path(),
                              gateway_secret=_read_gateway_secret(config))
```

### Step 9: Run + checkpoint
`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_identity_cli.py -q && .venv-robot-desktop/Scripts/python.exe -m ruff check nanobot/cli/commands.py`
Expected: all pass; ruff clean.

---

## Task 6: B1a compat aliases (`engineer set-password` deprecated + `/api/robot/engineer/login` alias + header alias)

**Files:** Modify `nanobot/cli/commands.py`, `nanobot/api/robot_routes.py`; Test `tests/robot_ai/test_engineer_alias.py`.

### Step 1: Write failing tests

Create `tests/robot_ai/test_engineer_alias.py`:
```python
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from robot_ai.library.auth import UserSessionStore, hash_password
from robot_ai.library.users import UserRegistry
from typer.testing import CliRunner


def test_engineer_set_password_alias_updates_admin_user(tmp_path: Path) -> None:
    """B1a `nanobot engineer set-password` is a DEPRECATED alias: updates admin in users.json,
    prints a migration notice, and does NOT only change config hash."""
    from nanobot.cli.commands import engineer_app
    reg = UserRegistry(tmp_path / "users.json", audit_path=tmp_path / "a.jsonl")
    reg.create("admin", "engineer", hash_password("oldpw", iterations=100_000))
    runner = CliRunner()
    with patch("getpass.getpass", side_effect=["newpw", "newpw"]):
        result = runner.invoke(engineer_app, ["set-password", "--users-path", str(tmp_path / "users.json"),
                                               "--audit-path", str(tmp_path / "a.jsonl")])
    assert result.exit_code == 0
    assert "deprecated" in result.output.lower() or "migration" in result.output.lower()
    admin = next(u for u in json.loads((tmp_path / "users.json").read_text("utf-8"))["users"].values()
                 if u["username"] == "admin")
    from robot_ai.library.auth import verify_password
    assert verify_password("newpw", admin["password_hash"]) is True


def test_engineer_login_alias_returns_user_token(tmp_path: Path) -> None:
    """B1a /api/robot/engineer/login alias -> process_auth_login(admin/engineer) -> user token."""
    from nanobot.api.robot_routes import process_engineer_login
    reg = UserRegistry(tmp_path / "users.json", audit_path=tmp_path / "a.jsonl")
    reg.create("admin", "engineer", hash_password("s3cret", iterations=100_000))
    store = UserSessionStore()
    status, body = process_engineer_login({"password": "s3cret"},
                                           users_path=str(tmp_path / "users.json"), audit_path=str(tmp_path / "a.jsonl"),
                                           token_store=store, throttle=__import__("robot_ai.library.auth", fromlist=["LoginThrottle"]).LoginThrottle())
    assert status == 200
    tok = body["data"]["user_token"]
    assert store.check(tok)["role"] == "engineer"
```

### Step 2: Run to verify fail
`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_engineer_alias.py -q`
Expected: FAIL — `engineer set-password` still writes config hash; `process_engineer_login` signature mismatch.

### Step 3: Retire B1a `engineer_set_password` → deprecated alias rewriting `users.json`

Replace the body of `engineer_set_password` in `nanobot/cli/commands.py` (lines ~2062-2085) with:
```python
@engineer_app.command("set-password")
def engineer_set_password(
    config: str | None = typer.Option(None, "--config", "-c", help="(deprecated) ignored"),
    users_path: str | None = typer.Option(None, "--users-path", help="Path to users.json"),
    audit_path: str | None = typer.Option(None, "--audit-path", help="Path to audit.jsonl"),
) -> None:
    """[DEPRECATED] Use `nanobot users set-bootstrap-password` or the engineer settings UI.

    Alias kept for backward compatibility: updates the `admin` user's password in users.json
    (does NOT only write config.robot_ai.engineer.password_hash anymore)."""
    from pathlib import Path as _Path
    from robot_ai.library.auth import hash_password
    from robot_ai.library.users import UserRegistry
    console.print("[yellow]Deprecated: this command now updates the 'admin' user in users.json. "
                  "Prefer `nanobot users set-bootstrap-password` or the engineer settings UI.[/yellow]")
    upath = _Path(users_path).expanduser() if users_path else _Path("~/.nanobot/robot_ai/users.json").expanduser()
    apath = _Path(audit_path).expanduser() if audit_path else _Path("~/.nanobot/robot_ai/audit.jsonl").expanduser()
    reg = UserRegistry(upath, audit_path=apath)
    admin = reg.get_by_username("admin")
    if admin is None:
        console.print("[red]'admin' user not found. Run `nanobot users set-bootstrap-password --username admin`.[/red]")
        raise typer.Exit(1)
    pw = getpass.getpass("Enter engineer password: ")
    pw2 = getpass.getpass("Confirm password: ")
    if pw != pw2 or not pw:
        console.print("[red]Passwords do not match or empty.[/red]")
        raise typer.Exit(1)
    if admin["enabled"]:
        reg.set_password(admin["user_id"], hash_password(pw),
                         actor={"actor": "system:cli", "actor_role": "system"})
    else:
        reg.bootstrap_set_password(admin["user_id"], hash_password(pw),
                                    actor={"actor": "system:cli", "actor_role": "system"})
    console.print("[green]admin password updated.[/green]")
```

### Step 4: Retire `process_engineer_login` → alias calling `process_auth_login`

In `nanobot/api/robot_routes.py`, replace `process_engineer_login` (lines ~921-988) with a thin alias:
```python
def process_engineer_login(body: Any, *, token_store=None, throttle=None,
                            users_path: str | None = None, audit_path: str | None = None,
                            config_path=None, client_key: str | None = None) -> tuple[int, dict[str, Any]]:
    """DEPRECATED alias: B1a engineer login -> unified login as admin/engineer.

    Returns a user_token (keyed `user_token`; also mirrored as `engineer_token` for old clients)."""
    status, result = process_auth_login(
        {"username": "admin", "password": str((body or {}).get("password", "")), "role": "engineer"},
        users_path=users_path, audit_path=audit_path, token_store=token_store, throttle=throttle,
        client_key=client_key)
    if status == 200:
        result["data"]["engineer_token"] = result["data"]["user_token"]  # compat mirror
    return status, result


def process_engineer_logout(engineer_token, *, token_store, audit_path=None, **_kw) -> tuple[int, dict[str, Any]]:
    """DEPRECATED alias -> unified logout."""
    return process_auth_logout(engineer_token, token_store=token_store, audit_path=audit_path)
```
(Keep the 8 `process_engineer_*` business functions for now — they still gate on `_require_engineer_token` until Task 7. Login/logout aliases route to unified auth.)

### Step 5: Run + checkpoint
`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_engineer_alias.py -q && .venv-robot-desktop/Scripts/python.exe -m ruff check nanobot/cli/commands.py nanobot/api/robot_routes.py`
Expected: all pass; ruff clean. (B1a `test_engineer_login.py` may need its fixtures updated to seed `users.json` instead of config — if it breaks here, update its `_write_config` helper to seed a UserRegistry admin; do NOT delete those tests.)

---

## Task 7: Switch B1a engineer endpoints to user-token + role; remove `EngineerTokenStore`

**Files:** Modify `nanobot/api/robot_routes.py`, `nanobot/webui/ws_http.py`, `robot_ai/library/auth.py`; update `tests/robot_ai/test_engineer_login.py` + Task-6/7 tests.

### Step 1: Update B1a engineer tests to the new auth model

Update `tests/robot_ai/test_engineer_login.py` fixtures: replace any `config`-hash login setup with a `UserRegistry` admin user + `UserSessionStore` token; replace `engineer_token`/`X-Nanobot-Engineer-Token` usages with `user_token`/`X-Nanobot-User-Token` (the header alias still works, but tests should use the new header). Keep the throttle / fail-closed / timing assertions; re-point them at `process_engineer_login` alias (still returns user_token) and `_require_user_role`. Run to see failures:
`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_engineer_login.py -q`

### Step 2: Add `_require_user_role` gate to the 8 `process_engineer_*` business functions

In `nanobot/api/robot_routes.py`, for each of `process_engineer_commands`, `process_engineer_command`, `process_engineer_create_command`, `process_engineer_update_draft`, `process_engineer_start_draft`, `process_engineer_publish`, `process_engineer_archive`, `process_engineer_audit`: replace the `ok, err = _require_engineer_token(token_store, engineer_token); if not ok: return 401, err` block with:
```python
    ok, err, _session = _require_user_role(token_store, engineer_token, "engineer")
    if not ok:
        return (403 if err["error"]["code"] == "forbidden" else 401), err
```
(Keep the `engineer_token` kwarg name on these functions for minimal diff — it now carries a user token; the handler/dispatcher reads `X-Nanobot-User-Token` and may also accept the `X-Nanobot-Engineer-Token` alias.)

Then delete `_require_engineer_token` (no remaining callers).

### Step 3: Update handlers + ws_http to read `X-Nanobot-User-Token` (header alias kept)

In `nanobot/api/robot_routes.py`:
- Add `_USER_TOKEN_HEADER = "X-Nanobot-User-Token"` constant.
- Change `_eng_token(request)` to return `request.headers.get(_USER_TOKEN_HEADER) or request.headers.get(_ENGINEER_TOKEN_HEADER)` (alias fallback).
- `_eng_deps`: change the `token_store` resolution from `get_engineer_token_store` to `get_user_session_store` (`from robot_ai.library.auth import get_user_session_store`), app key `"user_session_store"` (fallback old `"engineer_token_store"` app key optional).

In `nanobot/webui/ws_http.py` `_dispatch_robot_engineer_routes`:
- Change the store import to `get_user_session_store`; `store = getattr(self, "_user_session_store", None) or get_user_session_store()`.
- `etok = _case_insensitive_header(request.headers, robot_routes._USER_TOKEN_HEADER) or _case_insensitive_header(request.headers, robot_routes._ENGINEER_TOKEN_HEADER)`.

### Step 4: Remove `EngineerTokenStore` + old singletons

In `robot_ai/library/auth.py`: delete the `EngineerTokenStore` class, `_ENGINEER_TOKEN_STORE`, `get_engineer_token_store` (no callers remain after Step 3). Keep `UserSessionStore`, `_USER_SESSION_STORE`, `get_user_session_store`, `LoginThrottle`, hash/verify/extract.

### Step 5: Add `/api/auth/*` + `/api/users/*` transport mounting (aiohttp + ws_http) — full code

**Header alias constant** — add to `nanobot/api/robot_routes.py` (near `_ENGINEER_TOKEN_HEADER`):
```python
_USER_TOKEN_HEADER = "X-Nanobot-User-Token"
```
And change `_eng_token(request)` to accept the alias (defined in Step 3):
```python
def _eng_token(request):
    return request.headers.get(_USER_TOKEN_HEADER) or request.headers.get(_ENGINEER_TOKEN_HEADER)
```

**aiohttp handlers + register** — append to `nanobot/api/robot_routes.py`:
```python
def _user_deps(request):
    """Resolve (token_store, users_path, audit_path) for auth/users endpoints."""
    from robot_ai.library.auth import get_user_session_store, get_login_throttle
    store = request.app.get("user_session_store") or get_user_session_store()
    request.app["user_session_store"] = store
    return (store, request.app.get("robot_users_path"), request.app.get("robot_audit_path"))


def _user_throttle(request):
    from robot_ai.library.auth import get_login_throttle
    return request.app.get("user_login_throttle") or get_login_throttle()


def _user_tok(request):
    return request.headers.get(_USER_TOKEN_HEADER) or request.headers.get(_ENGINEER_TOKEN_HEADER)


def _actor_from(store, tok):
    s = store.check(tok) if tok else None
    if s is None:
        return {"actor": "user:?"}
    return {"actor": f"user:{s['user_id']}", "actor_user_id": s["user_id"],
            "actor_username": s["username"], "actor_role": s["role"]}


async def handle_auth_login(request):
    store, _up, audit_path = _user_deps(request)
    client_key = (request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
                  or request.query.get("token") or "anon")
    status, body = process_auth_login(await _eng_body(request), audit_path=audit_path,
                                       token_store=store, throttle=_user_throttle(request),
                                       client_key=client_key)
    return _eng_response(body, status)


async def handle_auth_logout(request):
    store, _up, audit_path = _user_deps(request)
    tok = _user_tok(request)
    session = store.check(tok) if tok else None
    status, body = process_auth_logout(tok, token_store=store, audit_path=audit_path, session=session)
    return _eng_response(body, status)


async def handle_users_collection(request):
    store, users_path, audit_path = _user_deps(request)
    tok = _user_tok(request)
    if request.method == "POST":
        status, body = process_users_create(await _eng_body(request), users_path=users_path,
                                             audit_path=audit_path, token_store=store, user_token=tok,
                                             actor=_actor_from(store, tok))
    else:
        status, body = process_users_list(users_path=users_path, token_store=store, user_token=tok)
    return _eng_response(body, status)


async def handle_users_item(request):
    store, users_path, audit_path = _user_deps(request)
    tok = _user_tok(request)
    status, body = process_users_patch(request.match_info["user_id"], await _eng_body(request),
                                        users_path=users_path, audit_path=audit_path,
                                        token_store=store, user_token=tok, actor=_actor_from(store, tok))
    return _eng_response(body, status)


async def handle_users_item_password(request):
    store, users_path, audit_path = _user_deps(request)
    tok = _user_tok(request)
    status, body = process_users_reset_password(request.match_info["user_id"], await _eng_body(request),
                                                 users_path=users_path, audit_path=audit_path,
                                                 token_store=store, user_token=tok, actor=_actor_from(store, tok))
    return _eng_response(body, status)


async def handle_users_me_password(request):
    store, users_path, audit_path = _user_deps(request)
    tok = _user_tok(request)
    status, body = process_users_me_password(await _eng_body(request), users_path=users_path,
                                              audit_path=audit_path, token_store=store, user_token=tok,
                                              actor=_actor_from(store, tok))
    return _eng_response(body, status)


def register_auth_routes(app):
    app.router.add_post("/api/auth/login", handle_auth_login)
    app.router.add_get("/api/auth/login", handle_auth_login)   # ws_http GET+body-header mirror
    app.router.add_post("/api/auth/logout", handle_auth_logout)
    app.router.add_get("/api/auth/logout", handle_auth_logout)


def register_users_routes(app):
    app.router.add_get("/api/users", handle_users_collection)
    app.router.add_post("/api/users", handle_users_collection)
    app.router.add_patch("/api/users/{user_id}", handle_users_item)
    app.router.add_post("/api/users/{user_id}/password", handle_users_item_password)
    app.router.add_post("/api/users/me/password", handle_users_me_password)
    app.router.add_get("/api/users", handle_users_collection)           # GET+body-header mirror
    app.router.add_get("/api/users/me/password", handle_users_me_password)
```

**ws_http dispatchers** — add to `nanobot/webui/ws_http.py` and wire both into `_dispatch_resolved` (call before/after `_dispatch_robot_engineer_routes`, return first non-None):
```python
_AUTH_PATH_PREFIX = "/api/auth/"
_USERS_PATH_PREFIX = "/api/users/"


def _dispatch_auth_routes(self, request, got):
    if not got.startswith(_AUTH_PATH_PREFIX):
        return None
    if not self.check_api_token(request):
        return _http_error(401, "Unauthorized")
    from nanobot.api import robot_routes as R
    from robot_ai.library.auth import get_user_session_store, get_login_throttle
    from nanobot.webui.http_utils import http_json_response
    store = getattr(self, "_user_session_store", None) or get_user_session_store()
    throttle = getattr(self, "_user_login_throttle", None) or get_login_throttle()
    audit_path = getattr(self, "_robot_audit_path", None)
    body = _robot_body_from_request(request)
    no_store = {"Cache-Control": "no-store", "Pragma": "no-cache"}

    def _resp(status, rbody):
        headers = dict(no_store)
        if status == 429:
            ra = (rbody or {}).get("data", {}).get("retry_after")
            if ra is not None:
                headers["Retry-After"] = str(ra)
        return http_json_response(rbody, status=status, headers=headers)

    if got == "/api/auth/login":
        client_key = ((_case_insensitive_header(request.headers, "Authorization") or "")
                      .removeprefix("Bearer ").strip() or "anon")
        return _resp(*R.process_auth_login(body, audit_path=audit_path, token_store=store,
                                            throttle=throttle, client_key=client_key))
    if got == "/api/auth/logout":
        tok = (_case_insensitive_header(request.headers, R._USER_TOKEN_HEADER)
               or _case_insensitive_header(request.headers, R._ENGINEER_TOKEN_HEADER))
        session = store.check(tok) if tok else None
        return _resp(*R.process_auth_logout(tok, token_store=store, audit_path=audit_path, session=session))
    return None


def _dispatch_users_routes(self, request, got):
    if not got.startswith(_USERS_PATH_PREFIX):
        return None
    if not self.check_api_token(request):
        return _http_error(401, "Unauthorized")
    from nanobot.api import robot_routes as R
    from robot_ai.library.auth import get_user_session_store
    from nanobot.webui.http_utils import http_json_response
    store = getattr(self, "_user_session_store", None) or get_user_session_store()
    users_path = getattr(self, "_robot_users_path", None)
    audit_path = getattr(self, "_robot_audit_path", None)
    body = _robot_body_from_request(request)
    action = _case_insensitive_header(request.headers, R._ENGINEER_ACTION_HEADER) or None
    tok = (_case_insensitive_header(request.headers, R._USER_TOKEN_HEADER)
           or _case_insensitive_header(request.headers, R._ENGINEER_TOKEN_HEADER))
    actor = R._actor_from(store, tok) if hasattr(R, "_actor_from") else {"actor": "user:?"}
    no_store = {"Cache-Control": "no-store", "Pragma": "no-cache"}

    def _resp(status, rbody):
        headers = dict(no_store)
        if status == 429:
            ra = (rbody or {}).get("data", {}).get("retry_after")
            if ra is not None:
                headers["Retry-After"] = str(ra)
        return http_json_response(rbody, status=status, headers=headers)

    kw = dict(users_path=users_path, audit_path=audit_path, token_store=store, user_token=tok, actor=actor)
    if got == "/api/users":
        if action == "create":
            return _resp(*R.process_users_create(body, **kw))
        return _resp(*R.process_users_list(users_path=users_path, token_store=store, user_token=tok))
    if got == "/api/users/me/password":
        return _resp(*R.process_users_me_password(body, **kw))
    if got.startswith("/api/users/"):
        parts = got[len("/api/users/"):].split("/")
        if len(parts) == 2 and parts[1] == "password":
            return _resp(*R.process_users_reset_password(parts[0], body, **kw))
        if len(parts) == 1 and parts[0]:
            return _resp(*R.process_users_patch(parts[0], body, **kw))
    return None
```
Wire call sites in `_dispatch_resolved` (mirror the existing `_dispatch_robot_engineer_routes` call at line ~258):
```python
response = await asyncio.to_thread(self._dispatch_auth_routes, request, got)
if response is not None:
    return response
response = await asyncio.to_thread(self._dispatch_users_routes, request, got)
if response is not None:
    return response
```
(`_actor_from` lives in `robot_routes.py`; the ws_http dispatcher reaches it via `R._actor_from`. If ruff flags the cross-module helper access, hoist `_actor_from` to a module-level function — same behavior.)

### Step 6: Run the full auth/users/engineer suite + ruff
`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_users.py tests/robot_ai/test_user_session.py tests/robot_ai/test_auth_login.py tests/robot_ai/test_users_api.py tests/robot_ai/test_identity_migration.py tests/robot_ai/test_identity_cli.py tests/robot_ai/test_engineer_alias.py tests/robot_ai/test_engineer_login.py tests/robot_ai/test_engineer_api.py tests/robot_ai/test_engineer_audit.py tests/robot_ai/test_engineer_routes.py -q && .venv-robot-desktop/Scripts/python.exe -m ruff check robot_ai/library/auth.py robot_ai/library/users.py nanobot/api/robot_routes.py nanobot/webui/ws_http.py nanobot/cli/commands.py`
Expected: all pass (B1a command-business tests green under user-token+role auth); ruff clean.

---

## Task 8: Final verification

### Step 1: Full suite
`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/ nanobot/config/ nanobot/cli/ -q`
Expected: all green (B1a + slice ①). Note `test_confirm_code` time-flake if present (pre-existing).

### Step 2: Ruff sweep on all slice-① + B1a files
`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m ruff check robot_ai/library/auth.py robot_ai/library/users.py robot_ai/library/migration.py robot_ai/library/versioned_registry.py nanobot/api/robot_routes.py nanobot/webui/ws_http.py nanobot/cli/commands.py nanobot/config/schema.py nanobot/config/loader.py tests/robot_ai/test_users.py tests/robot_ai/test_user_session.py tests/robot_ai/test_auth_login.py tests/robot_ai/test_users_api.py tests/robot_ai/test_identity_migration.py tests/robot_ai/test_identity_cli.py tests/robot_ai/test_engineer_alias.py`
Expected: All checks passed.

### Step 3: Acceptance scenario checklist (scripted, no new code)
1. Fresh install (no B1a hash, no gateway secret): `initialize_user_identity` → admin disabled + operator disabled placeholders.
2. `nanobot users set-bootstrap-password --username admin` (getpass) → admin enabled + login works.
3. `POST /api/auth/login` admin/engineer → user_token; `POST /api/users` (engineer) creates operator; operator login.
4. Disable operator → operator session revoked. Reset another user's password → their sessions revoked. `me/password` → self revoked.
5. `POST /api/users/{self_id}/password` → 409 `use_me_password`.
6. Disable last engineer → 409 `last_engineer_protected`.
7. `POST /api/robot/engineer/login` (alias) → user_token; command endpoints accept `X-Nanobot-User-Token` (and `X-Nanobot-Engineer-Token` alias).
8. operator user_token on `/api/users` POST or `/api/robot/engineer/commands` POST → 403.
9. Audit: `actor="user:<id>"` + `actor_user_id/username/role`; no password/token in audit.

Record results; do not commit.

---

## Self-Review

**Spec coverage (§1-§14 + decisions 1-21):**
- §2 user model + `users.json` + outbox → Task 1 (`UserRegistry`).
- §2 `normalize_username` independent of `normalize_id` (decision 15) → Task 1 Step 1/3 + isolation test.
- §3 `UserSessionStore` (issue/check/revoke/revoke_by_user_id, no refresh, decision 3/11) → Task 2.
- §3 `_require_user_role` gate + role matrix → Task 4 (`_require_user_role`) + Task 7 (8 endpoints).
- §5 API surface (no DELETE; self_id→409 `use_me_password`, decision 18) → Task 4.
- §6 outbox atomic + last-engineer protection + session revoke (reset/me/any-role/disable, decision 13) → Task 1 + Task 4.
- §7 migration (admin from B1a hash / disabled placeholder; operator from secret / disabled placeholder; never API token, decision 6/19) + `initialize_user_identity` separate domain (decision 17) + CLI bootstrap (decision 16) → Task 5.
- §7 CLI bootstrap getpass-only, no `--password` (decision 20) → Task 5 Step 5/7 + test.
- §8 B1a compat: `/api/robot/engineer/login` alias → unified login returning user_token (decision 7); `X-Nanobot-Engineer-Token` alias; `engineer set-password` deprecated alias → admin users.json (decision 21) → Task 6.
- §9 audit actor compat string + structured fields (decision 8) → Task 1 `_commit_with_audit` + Task 3 login audit.
- §11 security (timing/throttle/fail-closed/no-refresh/self_id/last-engineer/revoke) → Tasks 2/3/4.
- §12 tests → each task's test file.

**Placeholder scan:** Step 5 of Task 7 says "mirror the B1a `handle_engineer_*`/`_dispatch_robot_engineer_routes` structure 1:1" — this is a deliberate, scoped reuse of a verified pattern (the implementer reads the B1a code, lines cited), not a vague "add appropriate handlers". All other steps have concrete code or exact commands.

**Type consistency:** `UserRegistry(users_path, audit_path=...)` consistent across Tasks 1/3/4/5; `UserSessionStore.issue(dict)/check(token)->session|None/revoke/revoke_by_user_id` consistent (Task 2) with callers (Tasks 3/4/7); `_require_user_role(token_store, user_token, role) -> (ok, err, session)` defined Task 4, used Task 7; `_actor_dict(user)` Task 3, reused Task 4; `process_auth_login`/`logout` signatures Task 3, reused by Task 6 alias; `_resolve_users_path` Task 3, reused Task 4/5.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-12-robot-engineer-identity.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, two-stage review between tasks.
2. **Inline Execution** — executing-plans, batch with checkpoints.

Both keep the **no-git** rule (verify-checkpoints, no commits) until slice ① passes Task 8 final verification. (Slice ② unified-login UI + session namespace is a separate later brainstorm/spec/plan.)
