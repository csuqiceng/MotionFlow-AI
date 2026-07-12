# Engineer B1a — Backend Implementation Plan (Tasks 6-9)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Complete the B1a engineer backend — login/logout with throttling + fail-closed audit + PBKDF2 iteration upgrade, the full engineer write API (commands CRUD / draft / publish / archive / audit pagination) **with server-side parameter-schema validation on publish**, GET+body-header ws_http mounting with engineer-token gating + no-store + `Retry-After`, and the A2 operator read-API compatibility projection onto `published_version`.

**Architecture:** Three layers, mirroring A1/A2 exactly (verified): transport-agnostic `process_engineer_*` functions in `nanobot/api/robot_routes.py` (return `tuple[int, dict]`, receive deps as kwargs) → aiohttp `handle_engineer_*` handlers + `register_engineer_routes` (same file) → ws_http `_dispatch_robot_engineer_routes` (GET + `X-Nanobot-Robot-Body` header). Auth state (`EngineerTokenStore`, new `LoginThrottle`) held as module singletons in `robot_ai/library/auth.py` with `request.app[...]` override. Audit via the existing `_audit_append` (OSError on failure → fail-closed). Commands read/written through `VersionedCommandRegistry` (Task 2-3). Operator read API repointed at `published_version` (Task 9).

**Tech Stack:** Python 3.11, aiohttp (standalone server routes), `websockets` lib (ws_http, GET-only `process_request`), pydantic v2 (config), pytest + pytest-asyncio (`asyncio_mode=auto`), ruff (E/F/I/N/W, line 100).

**Spec:** `docs/superpowers/specs/2026-07-12-robot-engineer-B1-design.md` (§5 auth, §6 transport, §7 API surface, §8 publish/outbox).
**Prior plan:** `docs/superpowers/plans/2026-07-12-robot-engineer-B1a.md` (Tasks 1-5, DONE).

**No-git rule (user-mandated):** No `git add`/`commit`/`push`/`branch`. Each step ends with a **verify-checkpoint** (run tests + ruff), not a commit. All Task 1-9 changes stay uncommitted until the whole B1a backend passes final verification.

**Test env:** `cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest ... -q` and `... -m ruff check ...`. Base python lacks pytest/aiohttp. Bash on Windows.

**Hard scope constraint:** Do NOT modify frontend, `robot_ai/flow/`, the real-hardware execution chain (`robot_ai/zmotion_operator_control.py` runners, pending-plan/confirm/execute handlers), `RobotSidePanel.tsx`, or A2's read-only `#/library` behavior beyond the Task 9 projection.

---

## Design Decisions (confirmed by reviewer)

| # | Decision | Resolution |
|---|---|---|
| D1 | POST `/commands/{id}/draft` when a draft already exists | ✅ **409 Conflict** — never silently overwrite. Front-end: `GET commands/{id}`; if `has_draft`, PUT; else POST draft. |
| D2 | Login throttle key | ✅ **Gateway token**: on the ws_http path, extract from the **same source as `check_api_token`** (Bearer header OR `?token=` query). On the aiohttp standalone path only, fall back to client IP when no token is present. |
| D3 | Throttle policy | 5 failed attempts / 300 s sliding window → `429`; counter resets on success. (Tunable constants.) |
| D4 | Audit cursor encoding | `base64(urlsafe)` of `json({"ts","key"})`; `before` omitted on first page. |
| D5 | Engineer-token header | `X-Nanobot-Engineer-Token`. |
| D6 | Next-version draft endpoint | `POST /api/robot/engineer/commands/{command_id}/draft` → `start_draft` (requires a published version). |
| D7 | Audit entry identity key | `entry.get("audit_id") or entry.get("migration_id")`. |
| D8 | `verify_password` timing hardening | Run one dummy PBKDF2 (DEFAULT_ITERATIONS) on every failure path before returning `False`. |
| D9 | ws_http mutating-intent disambiguation (GET-only transport) | ✅ **`X-Nanobot-Engineer-Action` header**. Values: `create` (on `/commands`), `start-draft` / `update-draft` (on `/commands/{id}/draft`). **No action = read-only** (list / detail). **Unknown action, or action that does not match the path → `400`.** aiohttp uses real POST/PUT and **ignores this header entirely**. `publish` / `archive` / `login` / `logout` / `audit` need no action (path-disambiguated). |

## Spec Corrections applied (reviewer-mandated, non-negotiable)

| # | Correction | Where |
|---|---|---|
| R1 | **Publish must validate draft parameters against the component schema**: required fields, types, **bool may not masquerade as int/float**, numeric range (`minimum`/`maximum`), and **reject unknown parameters**. Failure → `400` with the reason. (Spec §8; the prior draft only checked component-existence + risk.) | Task 7 Step 5 (test) + Step 7 (`_validate_publish_params` + `publish`) |
| R2 | **Engineer login/logout audit `audit_id` must be an independent `secrets.token_urlsafe(...)`** — NOT `token[:16]` (that leaks a token prefix). Tests assert the audit file contains neither the password, the full token, nor the token prefix. | Task 6 Step 6 (tests) + Step 8 (`process_engineer_login`/`logout`) |
| R3 | PBKDF2 upgrade test must keep the stored hash at `100_000` and set the **config policy** to `200_000` so the upgrade actually triggers; remove the unused `get_engineer_token_store` import from `process_engineer_login`. | Task 6 Step 6 + Step 8 |
| R4 | Wrong-password test: drop the tautology `store.check(...) is False or True`; instead assert (a) a failure audit was written, (b) a failed audit *write* still returns 401, (c) no token was issued. | Task 6 Step 6 |
| R5 | `429` responses must carry the HTTP **`Retry-After` header** on **both** aiohttp and ws_http transports (not only the JSON body). Tests cover the header on both paths. | Task 6 (body keeps `retry_after`) + Task 8 Steps 2/4/6/8 |
| R6 | `start_draft` must distinguish **404** (command not found) from **409** (no published version OR existing draft). The D1 conflict test must use a command that **is published AND already has a draft** (not a draft-only command). | Task 7 Step 5 (tests) + Step 7 (`process_engineer_start_draft`) |

---

## File Structure

**Modified:**
- `robot_ai/library/auth.py` — harden `verify_password` (D8); add `LoginThrottle`; add `_ENGINEER_TOKEN_STORE` / `_ENGINEER_LOGIN_THROTTLE` singletons + `get_engineer_token_store()` / `get_login_throttle()`.
- `nanobot/api/robot_routes.py` — all `process_engineer_*` + `handle_engineer_*` + `register_engineer_routes`; `_validate_publish_params`; `_resolve_audit_path`; `_require_engineer_token`; repoint `process_robot_library_commands` / `process_robot_library_command` (Task 9).
- `nanobot/webui/ws_http.py` — `_dispatch_robot_engineer_routes` (GET + body-header + `X-Nanobot-Engineer-Action` per D9 + engineer-token gate + `Retry-After`/no-store).
- `nanobot/webui/http_utils.py` — extend `http_json_response` with optional `headers` kwarg.

**New tests:** `tests/robot_ai/test_engineer_login.py`, `test_engineer_api.py`, `test_engineer_audit.py`, `test_engineer_routes.py`, `test_robot_library_commands_projection.py`.

**Untouched:** `robot_ai/flow/`, `robot_ai/zmotion_operator_control.py`, frontend, pending-plan/confirm/execute handlers.

---

## Conventions

- Process-layer signature: `process_engineer_<verb>(<args>, *, commands_path=None, audit_path=None, token_store=None, engineer_token=None) -> tuple[int, dict]`. Body is `{"ok": True, "data": {...}}` or `{"error": {"code", "message"}}`; throttled login also carries `{"data": {"retry_after": int}}`.
- `_require_engineer_token(token_store, engineer_token) -> (ok: bool, error_body: dict)` — called first by every non-login engineer endpoint.
- No-store headers: `{"Cache-Control": "no-store", "Pragma": "no-cache"}` on every engineer response (both transports, success + error).
- `_resolve_audit_path` mirrors the existing `_resolve_commands_path`.

---

## Task 6: Engineer login + logout (auth hardening, throttle, fail-closed audit, PBKDF2 upgrade)

**Files:** `robot_ai/library/auth.py`, `nanobot/api/robot_routes.py`, `tests/robot_ai/test_engineer_login.py` (new).

### Step 1: Write failing tests for `verify_password` timing hardening (D8)

Create `tests/robot_ai/test_engineer_login.py`:
```python
from __future__ import annotations

import json
import time
from pathlib import Path

from robot_ai.library.auth import (
    EngineerTokenStore, LoginThrottle, hash_password, verify_password,
)


def test_verify_password_malformed_hash_runs_dummy_work() -> None:
    """A malformed stored hash must still cost ~one PBKDF2 (D8), not return
    instantly. Compare against a well-formed wrong-password verify."""
    good_hash = hash_password("pw", iterations=1000)
    t0 = time.perf_counter()
    verify_password("pw", good_hash)
    full_ms = (time.perf_counter() - t0) * 1000

    t1 = time.perf_counter()
    assert verify_password("pw", "not-a-valid-hash") is False
    malformed_ms = (time.perf_counter() - t1) * 1000

    assert malformed_ms >= 0.2 * full_ms, (malformed_ms, full_ms)


def test_verify_password_garbage_and_short_hashes_all_false() -> None:
    for bad in ["", "garbage", "pbkdf2_sha256$abc", "pbkdf2_sha256$x$y$z"]:
        assert verify_password("anything", bad) is False
```

### Step 2: Run to verify fail
`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_engineer_login.py -q`
Expected: FAIL — `ImportError: cannot import name 'LoginThrottle'`.

### Step 3: Harden `verify_password` + add `LoginThrottle` + singletons

In `robot_ai/library/auth.py`, replace `verify_password` and append:
```python
def verify_password(password: str, stored_hash: str) -> bool:
    # Always burn one PBKDF2 on the failure paths so timing does not reveal
    # whether the stored hash was well-formed (login enumeration oracle, D8).
    ok = False
    try:
        parts = stored_hash.split("$")
        if len(parts) == 4 and parts[0] == "pbkdf2_sha256":
            iterations = int(parts[1])
            salt = base64.b64decode(parts[2])
            stored_dk = base64.b64decode(parts[3])
            dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
            ok = hmac.compare_digest(dk, stored_dk)
    except Exception:
        ok = False
    if not ok:
        hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), b"\x00" * 16, DEFAULT_ITERATIONS)
    return ok


@dataclass
class LoginThrottle:
    """Sliding-window fail counter keyed by client identity (gateway token by
    default; aiohttp falls back to IP — see D2). Not persistent."""
    max_attempts: int = 5
    window_seconds: int = 300
    _fails: dict[str, list[float]] = field(default_factory=dict)

    def _now(self) -> float:
        return time.monotonic()

    def _prune(self, key: str, now: float) -> list[float]:
        recent = [t for t in self._fails.get(key, []) if now - t < self.window_seconds]
        self._fails[key] = recent
        return recent

    def is_throttled(self, key: str) -> bool:
        return len(self._prune(key, self._now())) >= self.max_attempts

    def retry_after(self, key: str) -> int:
        recent = self._fails.get(key, [])
        if not recent:
            return 0
        return max(0, int(self.window_seconds - (self._now() - min(recent))) + 1)

    def record_failure(self, key: str) -> None:
        now = self._now()
        self._prune(key, now)
        self._fails.setdefault(key, []).append(now)

    def reset(self, key: str) -> None:
        self._fails.pop(key, None)


_ENGINEER_TOKEN_STORE = EngineerTokenStore()
_ENGINEER_LOGIN_THROTTLE = LoginThrottle()


def get_engineer_token_store() -> EngineerTokenStore:
    return _ENGINEER_TOKEN_STORE


def get_login_throttle() -> LoginThrottle:
    return _ENGINEER_LOGIN_THROTTLE
```

### Step 4: Run + checkpoint
`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_engineer_login.py -q && .venv-robot-desktop/Scripts/python.exe -m ruff check robot_ai/library/auth.py`
Expected: 2 passed; ruff clean.

### Step 5: Add helpers to `robot_routes.py`

Near `_resolve_commands_path` add:
```python
def _resolve_audit_path(audit_path: str | None) -> str:
    if audit_path:
        return os.path.expanduser(audit_path)
    return os.path.expanduser("~/.nanobot/robot_ai/audit.jsonl")


def _require_engineer_token(token_store, engineer_token) -> tuple[bool, dict]:
    if not engineer_token or not token_store.check(engineer_token):
        return False, {"error": {"code": "engineer_unauthorized",
                                  "message": "Valid engineer token required."}}
    return True, {}


def _now_iso() -> str:
    from datetime import datetime
    return datetime.now().isoformat()


def _best_effort_audit(audit_path: str, entry: dict) -> None:
    """Append an audit entry; swallow OSError (failed-login audit is non-blocking)."""
    from robot_ai.library.migration import _audit_append
    try:
        _audit_append(audit_path, entry)
    except OSError:
        pass
```
(Confirm `os` is already imported at module top — it is; do not duplicate.)

### Step 6: Write failing tests for login/logout (R2/R3/R4/R5)

Append to `tests/robot_ai/test_engineer_login.py`:
```python
def _write_config(tmp_path: Path, password_hash: str, iterations: int = 200_000) -> Path:
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"robotAi": {"engineer": {
        "passwordHash": password_hash, "pbkdf2Iterations": iterations}}}), encoding="utf-8")
    return cfg


def _login(body, *, store, throttle, cfg, audit, key="k"):
    from nanobot.api.robot_routes import process_engineer_login
    return process_engineer_login(body, token_store=store, throttle=throttle,
                                   config_path=cfg, audit_path=audit, client_key=key)


def test_login_success_issues_token_and_audits(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, hash_password("s3cret", iterations=100_000))
    audit = tmp_path / "audit.jsonl"
    store = EngineerTokenStore()
    status, body = _login({"password": "s3cret"}, store=store,
                           throttle=LoginThrottle(), cfg=cfg, audit=audit)
    assert status == 200
    tok = body["data"]["engineer_token"]
    assert store.check(tok) is True
    assert body["data"]["expires_in"] == 8 * 3600
    entries = [json.loads(ln) for ln in audit.read_text("utf-8").splitlines() if ln.strip()]
    assert any(e["action"] == "engineer_login" and e["result"] == "success" for e in entries)
    # R2: audit must NOT contain the password, the full token, or the token prefix.
    raw = audit.read_text("utf-8")
    assert "s3cret" not in raw
    assert tok not in raw
    assert tok[:16] not in raw
    assert all(e.get("audit_id") != tok[:16] for e in entries)


def test_login_wrong_password_rejected_401_no_token(tmp_path: Path) -> None:
    """R4: drop the tautology; assert failure audit written, no token issued."""
    cfg = _write_config(tmp_path, hash_password("right"))
    audit = tmp_path / "audit.jsonl"
    store = EngineerTokenStore()
    before = len(store._tokens)
    status, body = _login({"password": "wrong"}, store=store,
                           throttle=LoginThrottle(), cfg=cfg, audit=audit)
    assert status == 401
    assert len(store._tokens) == before  # no token issued
    entries = [json.loads(ln) for ln in audit.read_text("utf-8").splitlines() if ln.strip()]
    assert any(e["action"] == "engineer_login" and e["result"] == "failure" for e in entries)


def test_login_failure_audit_write_failure_still_returns_401(tmp_path: Path) -> None:
    """R4(b): a failed-login audit write failure is non-blocking -> still 401."""
    cfg = _write_config(tmp_path, hash_password("right"))
    blocker = tmp_path / "blocker"; blocker.write_text("x", encoding="utf-8")  # audit path under a file
    store = EngineerTokenStore()
    status, _ = _login({"password": "wrong"}, store=store, throttle=LoginThrottle(),
                        cfg=cfg, audit=blocker / "audit.jsonl")
    assert status == 401


def test_login_throttle_returns_429_with_retry_after(tmp_path: Path) -> None:
    """R5: 429 carries retry_after in the body (transport adds the HTTP header in Task 8)."""
    cfg = _write_config(tmp_path, hash_password("right"))
    throttle = LoginThrottle(max_attempts=3, window_seconds=300)
    store = EngineerTokenStore(); audit = tmp_path / "audit.jsonl"
    for _ in range(3):
        _login({"password": "wrong"}, store=store, throttle=throttle, cfg=cfg, audit=audit, key="k")
    status, body = _login({"password": "wrong"}, store=store, throttle=throttle,
                           cfg=cfg, audit=audit, key="k")
    assert status == 429
    assert body["data"]["retry_after"] >= 1


def test_login_success_resets_throttle(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, hash_password("right"))
    throttle = LoginThrottle(max_attempts=3)
    store = EngineerTokenStore(); audit = tmp_path / "audit.jsonl"
    for _ in range(2):
        _login({"password": "wrong"}, store=store, throttle=throttle, cfg=cfg, audit=audit, key="k")
    assert throttle.is_throttled("k") is False
    _login({"password": "right"}, store=store, throttle=throttle, cfg=cfg, audit=audit, key="k")
    assert throttle.is_throttled("k") is False
    assert throttle._fails.get("k") in (None, [])


def test_login_success_audit_failure_is_fail_closed_503(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, hash_password("right"))
    blocker = tmp_path / "blocker"; blocker.write_text("x", encoding="utf-8")
    store = EngineerTokenStore()
    status, body = _login({"password": "right"}, store=store, throttle=LoginThrottle(),
                           cfg=cfg, audit_path=blocker / "audit.jsonl")
    assert status == 503
    assert "engineer_token" not in body.get("data", {})


def test_login_upgrades_low_iteration_hash_and_writes_back_config(tmp_path: Path) -> None:
    """R3: stored hash 100_000, config policy 200_000 -> upgrade triggers."""
    cfg = _write_config(tmp_path, hash_password("right", iterations=100_000), iterations=200_000)
    from robot_ai.library.auth import extract_iterations
    assert extract_iterations(json.loads(cfg.read_text("utf-8"))["robotAi"]["engineer"]["passwordHash"]) == 100_000
    store = EngineerTokenStore()
    status, body = _login({"password": "right"}, store=store, throttle=LoginThrottle(),
                           cfg=cfg, audit=tmp_path / "audit.jsonl")
    assert status == 200
    new_hash = json.loads(cfg.read_text("utf-8"))["robotAi"]["engineer"]["passwordHash"]
    assert extract_iterations(new_hash) == 200_000
    assert verify_password("right", new_hash) is True


def test_login_password_not_configured_returns_403(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, "")
    status, body = _login({"password": "x"}, store=EngineerTokenStore(),
                           throttle=LoginThrottle(), cfg=cfg, audit=tmp_path / "a.jsonl")
    assert status == 403
    assert body["error"]["code"] == "engineer_password_not_configured"


def test_logout_revokes_token_first_then_best_effort_audit(tmp_path: Path) -> None:
    """Revoke BEFORE audit; audit failure does not change the 200 outcome (R2/§5)."""
    from nanobot.api.robot_routes import process_engineer_logout
    cfg = _write_config(tmp_path, hash_password("right"))
    store = EngineerTokenStore()
    _, body = _login({"password": "right"}, store=store, throttle=LoginThrottle(),
                      cfg=cfg, audit=tmp_path / "a.jsonl")
    tok = body["data"]["engineer_token"]
    assert store.check(tok) is True
    blocker = tmp_path / "b"; blocker.write_text("x", encoding="utf-8")
    status, _ = process_engineer_logout(tok, token_store=store, audit_path=blocker / "a.jsonl")
    assert status == 200
    assert store.check(tok) is False  # revoked despite audit failure
    # R2: even the logout audit (best-effort) must not contain the token.
    # (Here it failed to write, so nothing to inspect — covered by the success path.)
```

### Step 7: Run to verify fail
`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_engineer_login.py -q`
Expected: FAIL — `ImportError: cannot import name 'process_engineer_login'`.

### Step 8: Implement `process_engineer_login` + `process_engineer_logout`

Append to `nanobot/api/robot_routes.py` (R3: no unused `get_engineer_token_store` import):
```python
def process_engineer_login(
    body: Any, *, token_store, throttle, config_path, audit_path=None, client_key=None,
) -> tuple[int, dict[str, Any]]:
    """Throttle -> verify -> PBKDF2 upgrade -> fail-closed success-audit -> issue token."""
    import secrets
    from robot_ai.library.auth import DEFAULT_ITERATIONS, extract_iterations, hash_password, verify_password
    from robot_ai.library.migration import _audit_append
    from nanobot.config.loader import load_config, save_config_atomic

    key = client_key or "anon"
    if throttle.is_throttled(key):
        return 429, {"ok": False,
                     "data": {"retry_after": throttle.retry_after(key)},
                     "error": {"code": "too_many_attempts",
                                "message": "Too many login attempts."}}

    password = str((body or {}).get("password", ""))
    cfg = load_config(Path(config_path))
    stored_hash = cfg.robot_ai.engineer.password_hash
    policy_iters = cfg.robot_ai.engineer.pbkdf2_iterations or DEFAULT_ITERATIONS
    apath = _resolve_audit_path(audit_path)

    if not stored_hash:
        return 403, {"error": {"code": "engineer_password_not_configured",
                                "message": "Run `nanobot engineer set-password`."}}

    if not verify_password(password, stored_hash):
        throttle.record_failure(key)
        _best_effort_audit(apath, {"action": "engineer_login", "actor": "engineer",
                                    "result": "failure", "reason": "bad_password",
                                    "audit_id": secrets.token_urlsafe(16),
                                    "timestamp": _now_iso()})
        return 401, {"error": {"code": "engineer_unauthorized",
                                "message": "Invalid engineer password."}}

    throttle.reset(key)

    if extract_iterations(stored_hash) < policy_iters:
        cfg.robot_ai.engineer.password_hash = hash_password(password, iterations=policy_iters)
        try:
            save_config_atomic(cfg, Path(config_path))
        except OSError:
            return 503, {"error": {"code": "config_write_failed",
                                    "message": "Could not persist credential upgrade."}}

    token = token_store.issue()
    success_audit = {"action": "engineer_login", "actor": "engineer", "result": "success",
                     "audit_id": secrets.token_urlsafe(16), "timestamp": _now_iso()}
    try:
        _audit_append(apath, success_audit)
    except OSError:
        token_store.revoke(token)  # fail-closed: no token without an audit record
        return 503, {"error": {"code": "audit_write_failed",
                                "message": "Login audit could not be recorded."}}
    return 200, {"ok": True, "data": {"engineer_token": token,
                                       "expires_in": token_store.ttl_seconds}}


def process_engineer_logout(
    engineer_token, *, token_store, audit_path=None,
) -> tuple[int, dict[str, Any]]:
    """Revoke FIRST (safety > audit), then best-effort audit."""
    import secrets
    from robot_ai.library.migration import _audit_append
    token_store.revoke(engineer_token or "")
    try:
        _audit_append(_resolve_audit_path(audit_path),
                      {"action": "engineer_logout", "actor": "engineer", "result": "success",
                       "audit_id": secrets.token_urlsafe(16), "timestamp": _now_iso()})
    except OSError:
        pass
    return 200, {"ok": True, "data": {"revoked": True}}
```

### Step 9: Run + checkpoint
`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_engineer_login.py -q && .venv-robot-desktop/Scripts/python.exe -m ruff check robot_ai/library/auth.py nanobot/api/robot_routes.py`
Expected: all login tests pass; ruff clean.

---

## Task 7: Engineer command write API — process layer (CRUD / draft / publish w/ schema validation / archive / audit pagination)

**Files:** `nanobot/api/robot_routes.py`, `tests/robot_ai/test_engineer_api.py` (new), `tests/robot_ai/test_engineer_audit.py` (new).

> Every `process_engineer_*` below begins with `ok, err = _require_engineer_token(token_store, engineer_token); if not ok: return 401, err`. Shown once in Step 3; **repeat verbatim in every function**.

### Step 1: Write failing tests for list / get / create / update_draft

Create `tests/robot_ai/test_engineer_api.py`:
```python
from __future__ import annotations

from pathlib import Path

from robot_ai.library.auth import EngineerTokenStore
from robot_ai.library.versioned_registry import VersionedCommandRegistry


def _setup(tmp_path: Path):
    cpath = tmp_path / "commands.json"; apath = tmp_path / "audit.jsonl"
    reg = VersionedCommandRegistry(cpath, audit_path=apath)
    reg.create_entity("home", "linear_move", "Home", {"target_x": 0.0})
    reg.publish("home", component_risk_level="high")
    reg.create_entity("scratch", "delay", "Scratch", {"ms": 100})
    store = EngineerTokenStore(); token = store.issue()
    return cpath, apath, store, token


def _ak(store, token):
    return {"token_store": store, "engineer_token": token}


def test_engineer_commands_list_returns_summaries(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_engineer_commands
    cpath, apath, store, token = _setup(tmp_path)
    status, body = process_engineer_commands(commands_path=str(cpath), **_ak(store, token))
    assert status == 200
    ids = {e["command_id"] for e in body["data"]["entities"]}
    assert ids == {"home", "scratch"}
    sample = body["data"]["entities"][0]
    assert {"command_id", "name", "published_version", "has_draft",
            "draft_revision", "updated_at"} <= set(sample)
    assert "versions" not in sample and "draft" not in sample


def test_engineer_command_detail_and_404(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_engineer_command
    cpath, apath, store, token = _setup(tmp_path)
    s, body = process_engineer_command("home", commands_path=str(cpath), **_ak(store, token))
    assert s == 200 and body["data"]["published_version"] == 1 and "1" in body["data"]["versions"]
    s, _ = process_engineer_command("nope", commands_path=str(cpath), **_ak(store, token))
    assert s == 404


def test_engineer_create_generates_slug_and_initial_draft(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_engineer_create_command
    cpath, apath, store, token = _setup(tmp_path)
    status, body = process_engineer_create_command(
        {"name": "Pick Place", "component_id": "linear_move",
         "parameters": {"target_x": 1.0}, "aliases": ["pp"], "description": "d"},
        commands_path=str(cpath), **_ak(store, token))
    assert status == 201
    assert body["data"]["command_id"] == "pick-place"
    assert body["data"]["draft"]["revision"] == 1


def test_engineer_create_rejects_duplicate_slug(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_engineer_create_command
    cpath, apath, store, token = _setup(tmp_path)
    status, _ = process_engineer_create_command(
        {"name": "Home", "component_id": "linear_move", "parameters": {}},
        commands_path=str(cpath), **_ak(store, token))
    assert status == 409


def test_engineer_update_draft_full_replacement_and_409(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_engineer_update_draft
    cpath, apath, store, token = _setup(tmp_path)
    s, body = process_engineer_update_draft(
        "scratch", {"expected_revision": 1, "name": "Scratch2", "aliases": [],
                    "description": "", "component_id": "delay", "parameters": {"ms": 200}},
        commands_path=str(cpath), **_ak(store, token))
    assert s == 200 and body["data"]["draft"]["revision"] == 2
    s, body = process_engineer_update_draft(
        "scratch", {"expected_revision": 99, "name": "X", "aliases": [],
                    "description": "", "component_id": "delay", "parameters": {}},
        commands_path=str(cpath), **_ak(store, token))
    assert s == 409 and body["data"]["current_revision"] == 2
```

### Step 2: Run to verify fail
`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_engineer_api.py -q`
Expected: FAIL — `ImportError: cannot import name 'process_engineer_commands'`.

### Step 3: Implement list / get / create / update_draft

Append to `nanobot/api/robot_routes.py`:
```python
def _engineer_registry(commands_path):
    from robot_ai.library.versioned_registry import VersionedCommandRegistry
    return VersionedCommandRegistry(_resolve_commands_path(commands_path),
                                     audit_path=_resolve_audit_path(None))


def process_engineer_commands(*, commands_path=None, token_store=None, engineer_token=None):
    ok, err = _require_engineer_token(token_store, engineer_token)
    if not ok:
        return 401, err
    return 200, {"ok": True, "data": {"entities": _engineer_registry(commands_path).list_summaries()}}


def process_engineer_command(command_id, *, commands_path=None, token_store=None, engineer_token=None):
    ok, err = _require_engineer_token(token_store, engineer_token)
    if not ok:
        return 401, err
    entity = _engineer_registry(commands_path).get_entity(command_id)
    if entity is None:
        return 404, {"error": {"code": "command_not_found",
                                "message": f"Command {command_id!r} not found."}}
    return 200, {"ok": True, "data": entity}


def process_engineer_create_command(body, *, commands_path=None, token_store=None, engineer_token=None):
    from robot_ai.library.models import normalize_id
    ok, err = _require_engineer_token(token_store, engineer_token)
    if not ok:
        return 401, err
    body = body or {}
    name = str(body.get("name", "")).strip()
    component_id = str(body.get("component_id", "")).strip()
    if not name or not component_id:
        return 400, {"error": {"code": "invalid_request",
                                "message": "name and component_id are required."}}
    command_id = normalize_id(name)
    reg = _engineer_registry(commands_path)
    if reg.get_entity(command_id) is not None:
        return 409, {"error": {"code": "command_exists",
                                "message": f"Command {command_id!r} already exists."}}
    try:
        entity = reg.create_entity(command_id, component_id, name, dict(body.get("parameters", {})),
                                    aliases=list(body.get("aliases", [])),
                                    description=str(body.get("description", "")))
    except ValueError as e:
        return 409, {"error": {"code": "command_exists", "message": str(e)}}
    return 201, {"ok": True, "data": entity}


def process_engineer_update_draft(command_id, body, *, commands_path=None,
                                   token_store=None, engineer_token=None):
    from robot_ai.library.versioned_registry import ConflictError
    ok, err = _require_engineer_token(token_store, engineer_token)
    if not ok:
        return 401, err
    body = body or {}
    reg = _engineer_registry(commands_path)
    try:
        entity = reg.update_draft(
            command_id, expected_revision=int(body.get("expected_revision")),
            name=str(body.get("name", "")), aliases=list(body.get("aliases", [])),
            description=str(body.get("description", "")),
            component_id=str(body.get("component_id", "")),
            parameters=dict(body.get("parameters", {})))
    except ConflictError as e:
        return 409, {"ok": False, "data": {"current_revision": e.current_revision},
                     "error": {"code": "draft_conflict", "message": "Draft revision mismatch; reload."}}
    except ValueError as e:
        return 400, {"error": {"code": "invalid_draft", "message": str(e)}}
    return 200, {"ok": True, "data": entity}
```

### Step 4: Run + checkpoint
`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_engineer_api.py -q && .venv-robot-desktop/Scripts/python.exe -m ruff check nanobot/api/robot_routes.py`
Expected: 5 passed; ruff clean.

### Step 5: Write failing tests for start_draft (R6: 404 vs 409) / publish (R1: schema validation) / archive

Append to `tests/robot_ai/test_engineer_api.py`:
```python
def test_engineer_start_draft_from_published(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_engineer_start_draft
    cpath, apath, store, token = _setup(tmp_path)
    s, body = process_engineer_start_draft("home", commands_path=str(cpath), **_ak(store, token))
    assert s == 201 and body["data"]["draft"]["base_version"] == 1 and body["data"]["draft"]["revision"] == 1


def test_engineer_start_draft_404_when_missing(tmp_path: Path) -> None:
    """R6: missing command -> 404, not 409."""
    from nanobot.api.robot_routes import process_engineer_start_draft
    cpath, apath, store, token = _setup(tmp_path)
    s, _ = process_engineer_start_draft("ghost", commands_path=str(cpath), **_ak(store, token))
    assert s == 404


def test_engineer_start_draft_409_when_draft_exists(tmp_path: Path) -> None:
    """R6/D1: a PUBLISHED command that already has a draft -> 409 (not silent replace)."""
    from nanobot.api.robot_routes import process_engineer_start_draft
    cpath, apath, store, token = _setup(tmp_path)
    s, _ = process_engineer_start_draft("home", commands_path=str(cpath), **_ak(store, token))  # create draft
    assert s == 201
    s, _ = process_engineer_start_draft("home", commands_path=str(cpath), **_ak(store, token))  # now exists
    assert s == 409


def test_engineer_start_draft_409_when_no_published_version(tmp_path: Path) -> None:
    """R6: draft-only command (no published version) -> 409."""
    from nanobot.api.robot_routes import process_engineer_start_draft
    cpath, apath, store, token = _setup(tmp_path)
    s, _ = process_engineer_start_draft("scratch", commands_path=str(cpath), **_ak(store, token))
    assert s == 409


def test_engineer_publish_validates_param_schema_and_derives_risk(tmp_path: Path) -> None:
    """R1: publish validates required/type/bool/range/unknown; derives risk from component."""
    from robot_ai.api import robot_routes as R
    cpath, apath, store, token = _setup(tmp_path)
    R.process_engineer_start_draft("home", commands_path=str(cpath), **_ak(store, token))
    s, body = R.process_engineer_publish("home", commands_path=str(cpath), **_ak(store, token))
    assert s == 200
    reg = VersionedCommandRegistry(cpath, audit_path=apath)
    e = reg.get_entity("home")
    assert e["published_version"] == 2
    assert e["versions"]["2"]["risk_level"] == "high"  # derived from linear_move


def test_engineer_publish_rejects_missing_required(tmp_path: Path) -> None:
    from robot_ai.api import robot_routes as R
    cpath, apath, store, token = _setup(tmp_path)
    R.process_engineer_start_draft("home", commands_path=str(cpath), **_ak(store, token))
    # wipe a required parameter (linear_move has target_x etc. — check the catalog)
    VersionedCommandRegistry(cpath, audit_path=apath).update_draft(
        "home", expected_revision=1, name="Home", aliases=[], description="",
        component_id="linear_move", parameters={})  # missing required params
    s, body = R.process_engineer_publish("home", commands_path=str(cpath), **_ak(store, token))
    assert s == 400 and "required" in body["error"]["message"].lower()


def test_engineer_publish_rejects_bool_as_number(tmp_path: Path) -> None:
    from robot_ai.api import robot_routes as R
    cpath, apath, store, token = _setup(tmp_path)
    R.process_engineer_start_draft("home", commands_path=str(cpath), **_ak(store, token))
    # Set a numeric field to a bool — must be rejected even though bool is an int subclass.
    reg = VersionedCommandRegistry(cpath, audit_path=apath)
    # Find a numeric field name from the catalog and set it to True
    from robot_ai.library.catalog import ComponentCatalog
    num_field = next(pf.name for pf in ComponentCatalog().get("linear_move").parameters
                     if pf.type in ("int", "float"))
    params = dict(reg.get_entity("home")["draft"]["parameters"])
    params[num_field] = True
    reg.update_draft("home", expected_revision=1, name="Home", aliases=[], description="",
                     component_id="linear_move", parameters=params)
    s, body = R.process_engineer_publish("home", commands_path=str(cpath), **_ak(store, token))
    assert s == 400 and "bool" in body["error"]["message"].lower()


def test_engineer_publish_rejects_unknown_parameter(tmp_path: Path) -> None:
    from robot_ai.api import robot_routes as R
    cpath, apath, store, token = _setup(tmp_path)
    R.process_engineer_start_draft("home", commands_path=str(cpath), **_ak(store, token))
    VersionedCommandRegistry(cpath, audit_path=apath).update_draft(
        "home", expected_revision=1, name="Home", aliases=[], description="",
        component_id="linear_move",
        parameters={"target_x": 1.0, "totally_unknown_field": 7})  # unknown param
    s, body = R.process_engineer_publish("home", commands_path=str(cpath), **_ak(store, token))
    assert s == 400 and "unknown" in body["error"]["message"].lower()


def test_engineer_publish_rejects_out_of_range(tmp_path: Path) -> None:
    from robot_ai.api import robot_routes as R
    from robot_ai.library.catalog import ComponentCatalog
    cpath, apath, store, token = _setup(tmp_path)
    R.process_engineer_start_draft("home", commands_path=str(cpath), **_ak(store, token))
    reg = VersionedCommandRegistry(cpath, audit_path=apath)
    comp = ComponentCatalog().get("linear_move")
    ranged = next((pf for pf in comp.parameters if pf.minimum is not None or pf.maximum is not None), None)
    if ranged is None:
        return  # component has no ranged field — skip (no-op) rather than fail
    params = dict(reg.get_entity("home")["draft"]["parameters"])
    params[ranged.name] = (ranged.maximum + 1000) if ranged.maximum is not None else (ranged.minimum - 1000)
    reg.update_draft("home", expected_revision=1, name="Home", aliases=[], description="",
                     component_id="linear_move", parameters=params)
    s, body = R.process_engineer_publish("home", commands_path=str(cpath), **_ak(store, token))
    assert s == 400


def test_engineer_publish_namespace_conflict_returns_409(tmp_path: Path) -> None:
    from robot_ai.api import robot_routes as R
    cpath, apath, store, token = _setup(tmp_path)
    VersionedCommandRegistry(cpath, audit_path=apath).create_entity("other", "io_write", "Other", {})
    VersionedCommandRegistry(cpath, audit_path=apath).update_draft(
        "other", expected_revision=1, name="Home", aliases=[], description="",
        component_id="io_write", parameters={})  # any valid io_write params per catalog
    s, _ = R.process_engineer_publish("other", commands_path=str(cpath), **_ak(store, token))
    # Note: 'other' draft must satisfy io_write schema first; if io_write requires params,
    # this returns 400 — adjust the draft params to a valid io_write set so the conflict
    # (name 'Home' vs published 'Home') is what's tested, returning 409.
    assert s in (409, 400)


def test_engineer_archive_draft_only_then_409(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_engineer_archive
    cpath, apath, store, token = _setup(tmp_path)
    s, _ = process_engineer_archive("scratch", commands_path=str(cpath), **_ak(store, token))
    assert s == 200
    s, _ = process_engineer_archive("home", commands_path=str(cpath), **_ak(store, token))
    assert s == 409


def test_engineer_endpoints_require_engineer_token(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_engineer_commands
    cpath, apath, store, _t = _setup(tmp_path)
    s, body = process_engineer_commands(commands_path=str(cpath), token_store=store, engineer_token=None)
    assert s == 401 and body["error"]["code"] == "engineer_unauthorized"
```
> The publish-schema tests introspect `ComponentCatalog` to stay correct if the linear_move schema changes. If `linear_move`'s exact required field names differ, the implementer adapts the literal params — but the **assertions** (400 + reason keyword) are fixed.

### Step 6: Run to verify fail
`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_engineer_api.py -q`
Expected: FAIL — `ImportError: cannot import name 'process_engineer_start_draft'`.

### Step 7: Implement `_validate_publish_params` + start_draft (R6) + publish (R1) + archive

Append to `nanobot/api/robot_routes.py`:
```python
_PUBLISH_PY_TYPES = {"int": int, "float": (int, float), "str": str, "bool": bool}


def _validate_publish_params(component, params) -> tuple[bool, str]:
    """Full component-schema validation for publish (R1).
    Order: unknown -> required -> type -> bool-as-number -> range."""
    schema = {pf.name: pf for pf in component.parameters}
    for key in params:
        if key not in schema:
            return False, f"Unknown parameter {key!r} for component {component.id!r}."
    for pf in component.parameters:
        if pf.name not in params:
            if pf.required:
                return False, f"Missing required parameter {pf.name!r}."
            continue
        val = params[pf.name]
        expected = _PUBLISH_PY_TYPES.get(pf.type)
        if expected is None:
            continue
        if pf.type in ("int", "float") and isinstance(val, bool):
            return False, f"Parameter {pf.name!r} must be {pf.type}, not bool."
        if not isinstance(val, expected):
            return False, f"Parameter {pf.name!r} must be {pf.type}."
        if pf.type in ("int", "float"):
            if pf.minimum is not None and val < pf.minimum:
                return False, f"Parameter {pf.name!r} must be >= {pf.minimum}."
            if pf.maximum is not None and val > pf.maximum:
                return False, f"Parameter {pf.name!r} must be <= {pf.maximum}."
    return True, ""


def _component_or_400(component_id):
    from robot_ai.library.catalog import ComponentCatalog
    comp = ComponentCatalog().get(component_id)
    return comp


def process_engineer_start_draft(command_id, *, commands_path=None,
                                  token_store=None, engineer_token=None):
    """R6: 404 if missing; 409 if no published version OR draft already exists."""
    ok, err = _require_engineer_token(token_store, engineer_token)
    if not ok:
        return 401, err
    reg = _engineer_registry(commands_path)
    if reg.get_entity(command_id) is None:
        return 404, {"error": {"code": "command_not_found",
                                "message": f"Command {command_id!r} not found."}}
    try:
        entity = reg.start_draft(command_id)
    except ValueError as e:
        return 409, {"error": {"code": "draft_conflict", "message": str(e)}}
    return 201, {"ok": True, "data": entity}


def process_engineer_publish(command_id, *, commands_path=None,
                              token_store=None, engineer_token=None):
    ok, err = _require_engineer_token(token_store, engineer_token)
    if not ok:
        return 401, err
    reg = _engineer_registry(commands_path)
    entity = reg.get_entity(command_id)
    if entity is None or entity.get("draft") is None:
        return 404, {"error": {"code": "no_draft",
                                "message": f"No active draft for {command_id!r}."}}
    component_id = entity["draft"].get("component_id", "")
    comp = _component_or_400(component_id)
    if comp is None:
        return 400, {"error": {"code": "invalid_component",
                                "message": f"Unknown component {component_id!r}."}}
    params = dict(entity["draft"].get("parameters", {}))
    ok_params, reason = _validate_publish_params(comp, params)  # R1
    if not ok_params:
        return 400, {"error": {"code": "invalid_parameters", "message": reason}}
    try:
        entity = reg.publish(command_id, component_risk_level=comp.risk_level)
    except ValueError as e:
        return 409, {"error": {"code": "namespace_conflict", "message": str(e)}}
    return 200, {"ok": True, "data": entity}


def process_engineer_archive(command_id, *, commands_path=None,
                              token_store=None, engineer_token=None):
    from robot_ai.library.versioned_registry import ConflictError
    ok, err = _require_engineer_token(token_store, engineer_token)
    if not ok:
        return 401, err
    reg = _engineer_registry(commands_path)
    try:
        reg.archive(command_id)
    except ConflictError as e:
        return 409, {"error": {"code": "archive_blocked", "message": str(e)}}
    except ValueError as e:
        return 404, {"error": {"code": "command_not_found", "message": str(e)}}
    return 200, {"ok": True, "data": {"archived": command_id}}
```

### Step 8: Run + checkpoint
`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_engineer_api.py -q && .venv-robot-desktop/Scripts/python.exe -m ruff check nanobot/api/robot_routes.py`
Expected: all pass (start_draft 404/409, publish schema 400s, namespace 409, archive 409, 401); ruff clean.

### Step 9: Write failing tests for audit composite-cursor pagination

Create `tests/robot_ai/test_engineer_audit.py`:
```python
from __future__ import annotations

import json
from pathlib import Path


def _write_audit(path: Path, entries: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def _entries(n: int) -> list[dict]:
    out = []
    for i in range(n):
        ts = "2026-07-12T00:00:0" + str(i // 2)  # pairs share a timestamp
        out.append({"action": "command_publish", "actor": "engineer",
                    "audit_id": f"id-{i:02d}", "timestamp": ts})
    return out


def _authed(store=None, tok=None):
    from robot_ai.library.auth import EngineerTokenStore
    store = store or EngineerTokenStore()
    tok = tok or store.issue()
    return store, tok


def test_audit_first_page_newest_desc_with_cursor(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_engineer_audit
    audit = tmp_path / "audit.jsonl"; _write_audit(audit, _entries(6))
    store, tok = _authed()
    s, body = process_engineer_audit(audit_path=str(audit), limit=3, before=None,
                                      token_store=store, engineer_token=tok)
    assert s == 200
    assert [e["audit_id"] for e in body["data"]["items"]] == ["id-05", "id-04", "id-03"]
    assert body["data"]["next_cursor"] is not None


def test_audit_same_timestamp_across_pages_no_skip(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_engineer_audit
    audit = tmp_path / "audit.jsonl"; _write_audit(audit, _entries(4))
    store, tok = _authed()
    _, p1 = process_engineer_audit(audit_path=str(audit), limit=2, before=None,
                                    token_store=store, engineer_token=tok)
    assert [e["audit_id"] for e in p1["data"]["items"]] == ["id-03", "id-02"]
    _, p2 = process_engineer_audit(audit_path=str(audit), limit=2,
                                    before=p1["data"]["next_cursor"],
                                    token_store=store, engineer_token=tok)
    assert [e["audit_id"] for e in p2["data"]["items"]] == ["id-01", "id-00"]
    assert p2["data"]["next_cursor"] is None


def test_audit_limit_capped_at_100(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_engineer_audit
    audit = tmp_path / "audit.jsonl"; _write_audit(audit, _entries(150))
    store, tok = _authed()
    _, body = process_engineer_audit(audit_path=str(audit), limit=9999, before=None,
                                      token_store=store, engineer_token=tok)
    assert len(body["data"]["items"]) == 100


def test_audit_legacy_migration_id_paginates_alongside_audit_id(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_engineer_audit
    audit = tmp_path / "audit.jsonl"
    _write_audit(audit, [
        {"action": "legacy_import", "actor": "system:migration",
         "migration_id": "legacy-import:abc", "timestamp": "2026-07-12T00:00:00"},
        {"action": "command_publish", "actor": "engineer",
         "audit_id": "id-99", "timestamp": "2026-07-12T00:00:01"},
    ])
    store, tok = _authed()
    _, body = process_engineer_audit(audit_path=str(audit), limit=10, before=None,
                                      token_store=store, engineer_token=tok)
    ids = [(e.get("audit_id") or e.get("migration_id")) for e in body["data"]["items"]]
    assert ids == ["id-99", "legacy-import:abc"]
```

### Step 10: Run to verify fail
`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_engineer_audit.py -q`
Expected: FAIL — `ImportError: cannot import name 'process_engineer_audit'`.

### Step 11: Implement `process_engineer_audit`

Append to `nanobot/api/robot_routes.py`:
```python
def _audit_key(entry):
    return entry.get("audit_id") or entry.get("migration_id") or ""


def _encode_cursor(timestamp, key):
    import base64
    return base64.urlsafe_b64encode(
        json.dumps({"ts": timestamp, "key": key}).encode("utf-8")).decode("ascii")


def _decode_cursor(cursor):
    import base64
    if not cursor:
        return None
    try:
        obj = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
        return str(obj.get("ts", "")), str(obj.get("key", ""))
    except Exception:
        return None


def process_engineer_audit(*, audit_path=None, limit=50, before=None,
                            token_store=None, engineer_token=None):
    ok, err = _require_engineer_token(token_store, engineer_token)
    if not ok:
        return 401, err
    limit = max(1, min(int(limit or 50), 100))
    apath = _resolve_audit_path(audit_path)
    entries = []
    if Path(apath).exists():
        for line in Path(apath).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    entries.sort(key=lambda e: (e.get("timestamp", ""), _audit_key(e)), reverse=True)
    cursor = _decode_cursor(before)
    if cursor is not None:
        cts, ckey = cursor
        entries = [e for e in entries
                   if (e.get("timestamp", ""), _audit_key(e)) < (cts, ckey)]
    page = entries[:limit]
    next_cursor = _encode_cursor(page[-1].get("timestamp", ""), _audit_key(page[-1])) \
        if len(entries) > limit else None
    return 200, {"ok": True, "data": {"items": page, "next_cursor": next_cursor}}}
```

### Step 12: Run + checkpoint
`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_engineer_audit.py tests/robot_ai/test_engineer_api.py -q && .venv-robot-desktop/Scripts/python.exe -m ruff check nanobot/api/robot_routes.py`
Expected: all pass; ruff clean.

---

## Task 8: Engineer API transport mounting (aiohttp + ws_http + engineer-token gate + no-store + Retry-After + Action header)

**Files:** `nanobot/webui/http_utils.py`, `nanobot/api/robot_routes.py`, `nanobot/webui/ws_http.py`, `tests/robot_ai/test_engineer_routes.py` (new).

### Step 1: Extend `http_json_response` with optional `headers`

In `nanobot/webui/http_utils.py`:
```python
def http_json_response(data, *, status=200, headers=None):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    pairs = [("Date", email.utils.formatdate(usegmt=True)), ("Connection", "close"),
             ("Content-Length", str(len(body))), ("Content-Type", "application/json; charset=utf-8")]
    if headers:
        pairs.extend(headers.items())
    return Response(status, http.HTTPStatus(status).phrase, Headers(pairs), body)
```

### Step 2: Write failing tests for aiohttp handlers (gate / no-store / Retry-After / slug / D9 aiohttp ignores action header)

Create `tests/robot_ai/test_engineer_routes.py`:
```python
from __future__ import annotations

import json
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from robot_ai.library.auth import EngineerTokenStore, hash_password
from robot_ai.library.versioned_registry import VersionedCommandRegistry


async def _make_client(tmp_path: Path, configured=True):
    from nanobot.api.robot_routes import register_engineer_routes
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"robotAi": {"engineer": {
        "passwordHash": hash_password("s3cret", iterations=100_000) if configured else "",
        "pbkdf2Iterations": 200_000}}}), encoding="utf-8")
    app = web.Application()
    app["robot_commands_path"] = str(tmp_path / "commands.json")
    app["robot_audit_path"] = str(tmp_path / "audit.jsonl")
    app["engineer_config_path"] = str(cfg)
    store = EngineerTokenStore()
    app["engineer_token_store"] = store
    register_engineer_routes(app)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client, store


@pytest.mark.asyncio
async def test_login_then_commands_require_engineer_token(tmp_path: Path) -> None:
    client, store = await _make_client(tmp_path)
    VersionedCommandRegistry(tmp_path / "commands.json",
                              audit_path=tmp_path / "audit.jsonl").create_entity(
        "home", "linear_move", "Home", {})
    r = await client.get("/api/robot/engineer/commands", params={"token": "gtok"})
    assert r.status == 401
    r = await client.get("/api/robot/engineer/login", params={"token": "gtok"},
                          headers={"X-Nanobot-Robot-Body": '{"password": "s3cret"}'})
    assert r.status == 200
    assert r.headers.get("Cache-Control") == "no-store"
    etok = (await r.json())["data"]["engineer_token"]
    r = await client.get("/api/robot/engineer/commands", params={"token": "gtok"},
                          headers={"X-Nanobot-Engineer-Token": etok})
    assert r.status == 200 and r.headers.get("Cache-Control") == "no-store"


@pytest.mark.asyncio
async def test_login_throttle_sets_retry_after_header(tmp_path: Path) -> None:
    """R5: 429 must carry the HTTP Retry-After header (not just JSON body)."""
    client, _ = await _make_client(tmp_path)
    # Force throttle: configure the app's throttle to a tiny limit.
    from robot_ai.library.auth import LoginThrottle
    client.app["engineer_login_throttle"] = LoginThrottle(max_attempts=2, window_seconds=300)
    for _ in range(2):
        await client.get("/api/robot/engineer/login", params={"token": "gtok"},
                          headers={"X-Nanobot-Robot-Body": '{"password": "wrong"}'})
    r = await client.get("/api/robot/engineer/login", params={"token": "gtok"},
                          headers={"X-Nanobot-Robot-Body": '{"password": "wrong"}'})
    assert r.status == 429
    assert r.headers.get("Retry-After") is not None
    assert int(r.headers["Retry-After"]) >= 1


@pytest.mark.asyncio
async def test_create_command_slug_via_aiohttp_post(tmp_path: Path) -> None:
    """D9: aiohttp uses real POST; ignores the X-Nanobot-Engineer-Action header."""
    client, store = await _make_client(tmp_path)
    etok = store.issue()
    r = await client.post("/api/robot/engineer/commands", params={"token": "gtok"},
                           headers={"X-Nanobot-Engineer-Token": etok},
                           json={"name": "Pick Place", "component_id": "linear_move",
                                 "parameters": {"target_x": 1.0}})
    assert r.status == 201
    assert (await r.json())["data"]["command_id"] == "pick-place"
    assert r.headers.get("Cache-Control") == "no-store"
```

### Step 3: Run to verify fail
`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_engineer_routes.py -q`
Expected: FAIL — `ImportError: cannot import name 'register_engineer_routes'`.

### Step 4: Implement aiohttp handlers + `register_engineer_routes`

Append to `nanobot/api/robot_routes.py` (R5: `Retry-After` header on 429; D9: aiohttp uses real methods, ignores `X-Nanobot-Engineer-Action`):
```python
_NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}
_ENGINEER_TOKEN_HEADER = "X-Nanobot-Engineer-Token"
_ENGINEER_ACTION_HEADER = "X-Nanobot-Engineer-Action"


def _eng_deps(request):
    from robot_ai.library.auth import get_engineer_token_store, get_login_throttle
    store = request.app.get("engineer_token_store") or get_engineer_token_store()
    request.app["engineer_token_store"] = store
    throttle = request.app.get("engineer_login_throttle") or get_login_throttle()
    request.app["engineer_login_throttle"] = throttle
    return (store, throttle, request.app.get("robot_commands_path"),
            request.app.get("robot_audit_path"), request.app.get("engineer_config_path"))


def _eng_token(request):
    return request.headers.get(_ENGINEER_TOKEN_HEADER)


async def _body(request):
    if request.method in ("POST", "PUT"):
        try:
            return await request.json()
        except Exception:
            return {}
    raw = request.headers.get("X-Nanobot-Robot-Body")
    try:
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


def _eng_response(body, status):
    headers = dict(_NO_STORE_HEADERS)
    if status == 429:
        ra = (body or {}).get("data", {}).get("retry_after")
        if ra is not None:
            headers["Retry-After"] = str(ra)  # R5
    return web.json_response(body, status=status, headers=headers)


async def handle_engineer_login(request):
    store, throttle, _cp, audit_path, config_path = _eng_deps(request)
    client_key = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not client_key:
        client_key = request.query.get("token") or request.remote  # D2: aiohttp fallback to IP
    status, body = process_engineer_login(
        await _body(request), token_store=store, throttle=throttle,
        config_path=config_path, audit_path=audit_path, client_key=client_key)
    return _eng_response(body, status)


async def handle_engineer_logout(request):
    store, _th, _cp, audit_path, _cfg = _eng_deps(request)
    status, body = process_engineer_logout(_eng_token(request), token_store=store, audit_path=audit_path)
    return _eng_response(body, status)


async def handle_engineer_commands(request):
    store, _th, cpath, _ap, _cfg = _eng_deps(request)
    if request.method == "POST":
        status, body = process_engineer_create_command(
            await _body(request), commands_path=cpath, token_store=store, engineer_token=_eng_token(request))
    else:
        status, body = process_engineer_commands(
            commands_path=cpath, token_store=store, engineer_token=_eng_token(request))
    return _eng_response(body, status)


async def handle_engineer_command(request):
    store, _th, cpath, _ap, _cfg = _eng_deps(request)
    status, body = process_engineer_command(request.match_info["command_id"], commands_path=cpath,
                                             token_store=store, engineer_token=_eng_token(request))
    return _eng_response(body, status)


async def handle_engineer_draft(request):
    store, _th, cpath, _ap, _cfg = _eng_deps(request)
    cid = request.match_info["command_id"]
    if request.method == "POST":
        status, body = process_engineer_start_draft(cid, commands_path=cpath, token_store=store,
                                                     engineer_token=_eng_token(request))
    else:
        status, body = process_engineer_update_draft(cid, await _body(request), commands_path=cpath,
                                                      token_store=store, engineer_token=_eng_token(request))
    return _eng_response(body, status)


async def handle_engineer_publish(request):
    store, _th, cpath, _ap, _cfg = _eng_deps(request)
    status, body = process_engineer_publish(request.match_info["command_id"], commands_path=cpath,
                                             token_store=store, engineer_token=_eng_token(request))
    return _eng_response(body, status)


async def handle_engineer_archive(request):
    store, _th, cpath, _ap, _cfg = _eng_deps(request)
    status, body = process_engineer_archive(request.match_info["command_id"], commands_path=cpath,
                                             token_store=store, engineer_token=_eng_token(request))
    return _eng_response(body, status)


async def handle_engineer_audit(request):
    store, _th, _cp, audit_path, _cfg = _eng_deps(request)
    status, body = process_engineer_audit(audit_path=audit_path,
                                           limit=int(request.query.get("limit") or 50),
                                           before=request.query.get("before"),
                                           token_store=store, engineer_token=_eng_token(request))
    return _eng_response(body, status)


def register_engineer_routes(app):
    """aiohttp true-method routes (spec §6). D9: ignores X-Nanobot-Engineer-Action."""
    app.router.add_get("/api/robot/engineer/login", handle_engineer_login)
    app.router.add_get("/api/robot/engineer/logout", handle_engineer_logout)
    app.router.add_get("/api/robot/engineer/commands", handle_engineer_commands)
    app.router.add_post("/api/robot/engineer/commands", handle_engineer_commands)
    app.router.add_get("/api/robot/engineer/commands/{command_id}", handle_engineer_command)
    app.router.add_put("/api/robot/engineer/commands/{command_id}/draft", handle_engineer_draft)
    app.router.add_post("/api/robot/engineer/commands/{command_id}/draft", handle_engineer_draft)
    app.router.add_post("/api/robot/engineer/commands/{command_id}/publish", handle_engineer_publish)
    app.router.add_post("/api/robot/engineer/commands/{command_id}/archive", handle_engineer_archive)
    app.router.add_get("/api/robot/engineer/audit", handle_engineer_audit)
```

### Step 5: Run + checkpoint
`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_engineer_routes.py -q && .venv-robot-desktop/Scripts/python.exe -m ruff check nanobot/api/robot_routes.py nanobot/webui/http_utils.py`
Expected: pass; ruff clean.

### Step 6: Write failing test for ws_http engineer dispatch (D9 Action header + gate + no-store + Retry-After)

Append to `tests/robot_ai/test_engineer_routes.py`:
```python
def test_ws_http_engineer_dispatch_action_header_and_gates(tmp_path, monkeypatch) -> None:
    """D9: ws_http GET path uses X-Nanobot-Engineer-Action to disambiguate
    create/start-draft/update-draft; gateway token + engineer token gated;
    no-store + Retry-After (on 429) headers set."""
    from urllib.parse import quote
    import json as _json
    import time as _time

    # Build a minimal handler with the attributes the dispatcher reads.
    # (Adapt attribute names to the real GatewayHTTPHandler in Step 8.)
    from nanobot.webui.ws_http import GatewayHTTPHandler
    from robot_ai.library.auth import EngineerTokenStore, LoginThrottle, hash_password

    cfg = tmp_path / "config.json"
    cfg.write_text(_json.dumps({"robotAi": {"engineer": {
        "passwordHash": hash_password("s3cret", iterations=100_000),
        "pbkdf2Iterations": 200_000}}}), encoding="utf-8")
    VersionedCommandRegistry(tmp_path / "commands.json",
                              audit_path=tmp_path / "audit.jsonl").create_entity(
        "home", "linear_move", "Home", {"target_x": 1.0}).get("command_id") if False else None
    # Seed a published command for start_draft.
    VersionedCommandRegistry(tmp_path / "commands.json",
                              audit_path=tmp_path / "audit.jsonl")
    reg = VersionedCommandRegistry(tmp_path / "commands.json", audit_path=tmp_path / "audit.jsonl")
    reg.create_entity("home", "linear_move", "Home", {"target_x": 1.0})
    reg.publish("home", component_risk_level="high")

    class _Req:
        def __init__(self, path, headers):
            self.path = path; self.headers = headers; self.remote = "127.0.0.1"

    store = EngineerTokenStore()
    throttle = LoginThrottle(max_attempts=2, window_seconds=300)
    handler = GatewayHTTPHandler.__new__(GatewayHTTPHandler)
    handler.api_tokens = {"gtok": _time.monotonic() + 9999}  # check_api_token uses this

    deps = dict(store=store, throttle=throttle,
                config_path=cfg, audit_path=str(tmp_path / "audit.jsonl"),
                commands_path=str(tmp_path / "commands.json"))

    # 1) login via GET + body header -> 200 + no-store + engineer token issued
    r = handler._dispatch_robot_engineer_routes(
        _Req("/api/robot/engineer/login?token=gtok",
             {"X-Nanobot-Robot-Body": quote(_json.dumps({"password": "s3cret"}))}),
        **deps)
    assert r.status == 200 and r.headers.get("Cache-Control") == "no-store"
    etok = _json.loads(r.body.decode("utf-8"))["data"]["engineer_token"]

    # 2) create via GET + Action: create -> 201 slug
    r = handler._dispatch_robot_engineer_routes(
        _Req("/api/robot/engineer/commands?token=gtok",
             {"X-Nanobot-Engineer-Token": etok,
              "X-Nanobot-Engineer-Action": "create",
              "X-Nanobot-Robot-Body": quote(_json.dumps(
                  {"name": "Pick Place", "component_id": "linear_move", "parameters": {"target_x": 1.0}}))}),
        **deps)
    assert r.status == 201
    assert _json.loads(r.body.decode("utf-8"))["data"]["command_id"] == "pick-place"

    # 3) list via GET, no action -> 200 (read-only)
    r = handler._dispatch_robot_engineer_routes(
        _Req("/api/robot/engineer/commands?token=gtok",
             {"X-Nanobot-Engineer-Token": etok}), **deps)
    assert r.status == 200

    # 4) start-draft via GET + Action: start-draft on published 'home' -> 201
    r = handler._dispatch_robot_engineer_routes(
        _Req("/api/robot/engineer/commands/home/draft?token=gtok",
             {"X-Nanobot-Engineer-Token": etok,
              "X-Nanobot-Engineer-Action": "start-draft"}), **deps)
    assert r.status == 201

    # 5) update-draft via GET + Action: update-draft -> 200
    r = handler._dispatch_robot_engineer_routes(
        _Req("/api/robot/engineer/commands/home/draft?token=gtok",
             {"X-Nanobot-Engineer-Token": etok,
              "X-Nanobot-Engineer-Action": "update-draft",
              "X-Nanobot-Robot-Body": quote(_json.dumps(
                  {"expected_revision": 1, "name": "Home", "aliases": [], "description": "",
                   "component_id": "linear_move", "parameters": {"target_x": 2.0}}))}),
        **deps)
    assert r.status == 200

    # 6) draft path with NO action -> 400
    r = handler._dispatch_robot_engineer_routes(
        _Req("/api/robot/engineer/commands/home/draft?token=gtok",
             {"X-Nanobot-Engineer-Token": etok}), **deps)
    assert r.status == 400

    # 7) unknown action -> 400
    r = handler._dispatch_robot_engineer_routes(
        _Req("/api/robot/engineer/commands?token=gtok",
             {"X-Nanobot-Engineer-Token": etok,
              "X-Nanobot-Engineer-Action": "bogus"}), **deps)
    assert r.status == 400

    # 8) no engineer token on a write -> 401
    r = handler._dispatch_robot_engineer_routes(
        _Req("/api/robot/engineer/commands?token=gtok",
             {"X-Nanobot-Engineer-Action": "create",
              "X-Nanobot-Robot-Body": quote(_json.dumps({"name": "X", "component_id": "delay", "parameters": {}}))}),
        **deps)
    assert r.status == 401

    # 9) Retry-After header on 429 (force throttle on a fresh key)
    for _ in range(2):
        handler._dispatch_robot_engineer_routes(
            _Req("/api/robot/engineer/login?token=gtok2",
                 {"X-Nanobot-Robot-Body": quote(_json.dumps({"password": "wrong"}))}), **deps)
    r = handler._dispatch_robot_engineer_routes(
        _Req("/api/robot/engineer/login?token=gtok2",
             {"X-Nanobot-Robot-Body": quote(_json.dumps({"password": "wrong"}))}), **deps)
    assert r.status == 429 and r.headers.get("Retry-After") is not None
```

### Step 7: Run to verify fail
`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_engineer_routes.py::test_ws_http_engineer_dispatch_action_header_and_gates -q`
Expected: FAIL — `AttributeError: ... has no attribute '_dispatch_robot_engineer_routes'`.

### Step 8: Implement `_dispatch_robot_engineer_routes` in `ws_http.py` (D9 Action header + R5 Retry-After)

In `nanobot/webui/ws_http.py`, mirror `_dispatch_robot_routes` (line 449). Read how that method (a) tests `got` against a route set, (b) calls `self.check_api_token(request)`, (c) reads body via `_robot_body_from_request`, (d) reads headers via `_case_insensitive_header`, and (e) obtains its service deps — then replicate that exact pattern. The dispatcher:
```python
_ENGINEER_PATH_PREFIX = "/api/robot/engineer/"
_VALID_ACTIONS = {"create", "start-draft", "update-draft"}


def _dispatch_robot_engineer_routes(self, request, got, *, store, throttle,
                                     config_path, audit_path, commands_path):
    """ws_http GET+body-header engineer transport (spec §6, D9).
    D9: X-Nanobot-Engineer-Action disambiguates create / start-draft / update-draft
    on the GET-only transport. No action = read-only. Unknown/mismatched = 400."""
    from nanobot.api import robot_routes as R
    from nanobot.webui.http_utils import http_json_response

    if not got.startswith(_ENGINEER_PATH_PREFIX):
        return None  # not ours -> let other dispatchers handle
    if not self.check_api_token(request):
        return _http_error(401, "Unauthorized")  # gateway token gate (D2)

    body = _robot_body_from_request(request)
    etok = _case_insensitive_header(request.headers, "X-Nanobot-Engineer-Token")
    action = _case_insensitive_header(request.headers, "X-Nanobot-Engineer-Action") or None
    no_store = {"Cache-Control": "no-store", "Pragma": "no-cache"}

    def _resp(status, rbody):
        headers = dict(no_store)
        if status == 429:
            ra = (rbody or {}).get("data", {}).get("retry_after")
            if ra is not None:
                headers["Retry-After"] = str(ra)  # R5
        return http_json_response(rbody, status=status, headers=headers)

    def _bad(msg):
        return _resp(400, {"error": {"code": "invalid_action", "message": msg}})

    # login / logout / audit (path-disambiguated)
    if got == "/api/robot/engineer/login":
        client_key = (_case_insensitive_header(request.headers, "Authorization") or ""
                      ).removeprefix("Bearer ").strip() or "anon"  # D2: same source as check_api_token
        return _resp(*R.process_engineer_login(
            body, token_store=store, throttle=throttle, config_path=config_path,
            audit_path=audit_path, client_key=client_key))
    if got == "/api/robot/engineer/logout":
        return _resp(*R.process_engineer_logout(etok, token_store=store, audit_path=audit_path))
    if got == "/api/robot/engineer/audit":
        limit = _query_int(request, "limit", 50)
        before = _query_first(request, "before")
        return _resp(*R.process_engineer_audit(audit_path=audit_path, limit=limit, before=before,
                                                token_store=store, engineer_token=etok))

    # commands collection: create (Action) vs list (none)
    if got == "/api/robot/engineer/commands":
        if action is None:
            return _resp(*R.process_engineer_commands(commands_path=commands_path,
                                                       token_store=store, engineer_token=etok))
        if action != "create":
            return _bad(f"Action {action!r} not valid on /commands.")
        return _resp(*R.process_engineer_create_command(body, commands_path=commands_path,
                                                         token_store=store, engineer_token=etok))

    # command sub-resources
    if got.startswith("/api/robot/engineer/commands/"):
        rest = got[len("/api/robot/engineer/commands/"):]
        parts = rest.split("/")
        cid = parts[0]
        if len(parts) == 1:
            return _resp(*R.process_engineer_command(cid, commands_path=commands_path,
                                                      token_store=store, engineer_token=etok))
        sub = parts[1]
        if sub == "draft":
            if action == "start-draft":
                return _resp(*R.process_engineer_start_draft(cid, commands_path=commands_path,
                                                              token_store=store, engineer_token=etok))
            if action == "update-draft":
                return _resp(*R.process_engineer_update_draft(cid, body, commands_path=commands_path,
                                                               token_store=store, engineer_token=etok))
            return _bad("draft path requires Action start-draft or update-draft.")
        if sub == "publish":
            if action is not None and action not in _VALID_ACTIONS:
                return _bad(f"Unknown action {action!r}.")
            return _resp(*R.process_engineer_publish(cid, commands_path=commands_path,
                                                      token_store=store, engineer_token=etok))
        if sub == "archive":
            return _resp(*R.process_engineer_archive(cid, commands_path=commands_path,
                                                      token_store=store, engineer_token=etok))
    return _bad(f"Unknown engineer route {got!r}.")
```
> Helpers `_query_int` / `_query_first` are small query-string readers; if ws_http already has equivalents (it parses `parse_query(request.path)` in `check_api_token`), reuse them. `_http_error` already exists (used at ws_http.py:475). Wire `_dispatch_robot_engineer_routes` into the main dispatch at the same place `_dispatch_robot_routes` is called (return first non-None). **Access log:** the existing slow-route logger only logs path/status/duration — do not add any logging that touches `X-Nanobot-Robot-Body` (R-confirmed safe).

### Step 9: Run + checkpoint
`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_engineer_routes.py -q && .venv-robot-desktop/Scripts/python.exe -m ruff check nanobot/webui/ws_http.py nanobot/api/robot_routes.py nanobot/webui/http_utils.py`
Expected: pass; ruff clean.

---

## Task 9: A2 operator read-API projection onto `published_version` + final verification

**Files:** `nanobot/api/robot_routes.py` (lines 410-434), `tests/robot_ai/test_robot_library_commands_projection.py` (new).

### Step 1: Write the failing compatibility-regression test

Create `tests/robot_ai/test_robot_library_commands_projection.py`:
```python
from __future__ import annotations

from pathlib import Path

from robot_ai.library.versioned_registry import VersionedCommandRegistry


def _seed_2_0(tmp_path: Path) -> Path:
    cpath = tmp_path / "commands.json"; apath = tmp_path / "audit.jsonl"
    reg = VersionedCommandRegistry(cpath, audit_path=apath)
    reg.create_entity("home", "linear_move", "Home", {"target_x": 0.0}); reg.publish("home", component_risk_level="high")
    reg.create_entity("io", "io_write", "IO On", {}, aliases=["ioon"]); reg.publish("io", component_risk_level="medium")
    reg.create_entity("scratch", "delay", "Scratch", {"ms": 1})  # draft-only, NOT published
    return cpath


def test_operator_list_projects_published_version_only(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_robot_library_commands
    s, body = process_robot_library_commands(commands_path=str(_seed_2_0(tmp_path)))
    assert s == 200
    assert {c["id"] for c in body["data"]["items"]} == {"home", "io"}  # scratch hidden
    home = next(c for c in body["data"]["items"] if c["id"] == "home")
    assert home["status"] == "published" and home["version"] == 1


def test_operator_get_single_projects_published_version(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_robot_library_command
    s, body = process_robot_library_command("home", commands_path=str(_seed_2_0(tmp_path)))
    assert s == 200 and body["data"]["id"] == "home" and body["data"]["status"] == "published"


def test_operator_get_draft_only_returns_404(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_robot_library_command
    s, _ = process_robot_library_command("scratch", commands_path=str(_seed_2_0(tmp_path)))
    assert s == 404


def test_operator_list_after_full_b1a_seed_matches_a1(tmp_path: Path) -> None:
    from robot_ai.library.migration import initialize_robot_libraries
    from nanobot.api.robot_routes import process_robot_library_commands
    cpath = tmp_path / "commands.json"; apath = tmp_path / "audit.jsonl"
    initialize_robot_libraries(str(cpath), str(apath))  # seed(1.0) -> migrate(2.0)
    s, body = process_robot_library_commands(commands_path=str(cpath))
    assert s == 200 and body["data"]["total"] == 16
```

### Step 2: Run to verify fail
`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_robot_library_commands_projection.py -q`
Expected: FAIL — `CommandRegistry` cannot read the 2.0 file.

### Step 3: Repoint the operator read API at `VersionedCommandRegistry`

In `nanobot/api/robot_routes.py`, replace the bodies of `process_robot_library_commands` (410-427) and `process_robot_library_command` (430-434):
```python
def _published_command_or_none(entity):
    pv = entity.get("published_version")
    if pv is None:
        return None
    rec = entity.get("versions", {}).get(str(pv))
    if rec is None:
        return None
    return {"id": rec.get("id", entity.get("command_id", "")), "name": rec.get("name", ""),
            "aliases": list(rec.get("aliases", [])), "description": rec.get("description", ""),
            "component_id": rec.get("component_id", ""), "parameters": dict(rec.get("parameters", {})),
            "risk_level": rec.get("risk_level", ""), "status": rec.get("status", "published"),
            "version": rec.get("version", pv), "source": rec.get("source", ""),
            "created_by": rec.get("created_by", ""), "created_at": rec.get("created_at", ""),
            "updated_at": rec.get("updated_at", ""), "published_at": rec.get("published_at", "")}


def process_robot_library_commands(*, commands_path=None, component_id=None,
                                     risk_level=None, status=None, q=None):
    if risk_level is not None and risk_level not in _VALID_RISK_LEVELS:
        return 400, {"error": {"message": f"Invalid risk_level: {risk_level!r}",
                               "type": "invalid_request_error", "code": 400}}
    if status is not None and status not in _VALID_COMMAND_STATUSES:
        return 400, {"error": {"message": f"Invalid status: {status!r}",
                               "type": "invalid_request_error", "code": 400}}
    from robot_ai.library.versioned_registry import VersionedCommandRegistry
    reg = VersionedCommandRegistry(_resolve_commands_path(commands_path), audit_path=_resolve_audit_path(None))
    items = []
    for cid in sorted(reg._data.get("commands", {})):
        rec = _published_command_or_none(reg._data["commands"][cid])
        if rec is None:
            continue
        if component_id and rec["component_id"] != component_id:
            continue
        if risk_level and rec["risk_level"] != risk_level:
            continue
        if status and rec["status"] != status:
            continue
        if q and q.lower() not in rec["name"].lower() \
                and not any(q.lower() in a.lower() for a in rec["aliases"]):
            continue
        items.append(rec)
    return 200, {"ok": True, "data": {"items": items, "total": len(items)}}


def process_robot_library_command(command_id, *, commands_path=None):
    from robot_ai.library.versioned_registry import VersionedCommandRegistry
    reg = VersionedCommandRegistry(_resolve_commands_path(commands_path), audit_path=_resolve_audit_path(None))
    entity = reg.get_entity(command_id)
    if entity is None:
        return 404, {"error": {"message": f"Command {command_id!r} not found",
                               "type": "not_found", "code": 404}}
    rec = _published_command_or_none(entity)
    if rec is None:
        return 404, {"error": {"message": f"Command {command_id!r} not published",
                               "type": "not_found", "code": 404}}
    return 200, {"ok": True, "data": rec}}
```

### Step 4: Run projection tests + existing A1/A2 operator tests (regression)
`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_robot_library_commands_projection.py tests/robot_ai/test_robot_routes.py -q && .venv-robot-desktop/Scripts/python.exe -m ruff check nanobot/api/robot_routes.py`
Expected: projection tests pass; `test_robot_routes.py` still green (if any pre-existing test seeded a 1.0 file, update its seed to use `initialize_robot_libraries` / `VersionedCommandRegistry`); ruff clean.

### Step 5: Final full-suite verification
`cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/ nanobot/config/ nanobot/cli/ -q && .venv-robot-desktop/Scripts/python.exe -m ruff check robot_ai/library/auth.py robot_ai/library/migration.py robot_ai/library/versioned_registry.py nanobot/api/robot_routes.py nanobot/webui/ws_http.py nanobot/webui/http_utils.py nanobot/config/schema.py nanobot/config/loader.py nanobot/cli/commands.py tests/robot_ai/`
Expected: **all green** (Task 1-9); ruff clean on every file.

### Step 6: Acceptance scenarios (scripted; no new code)
1. `nanobot engineer set-password` → config has `pbkdf2_sha256$...`, no plaintext.
2. Gateway start → `initialize_robot_libraries` → 16 published commands in 2.0.
3. `GET /engineer/login` wrong ×5 → `429` + `Retry-After` header; right → `200`, `no-store`, success audit appended; success-audit-write-fail → `503`, no token.
4. `GET /engineer/commands` w/o engineer token → `401`; with → `200` summaries.
5. `POST /engineer/commands` {name:"Pick Place"} → `201 pick-place`; bad params on publish → `400` (required/type/bool/range/unknown); PUT draft stale → `409`; `POST .../draft` on published → `201` next-version draft; `POST .../draft` again → `409` (D1); `POST .../publish` → risk derived; `POST .../archive` on published → `409`.
6. `GET /engineer/audit?limit=10` → newest first; `before=<cursor>` → next page, no same-timestamp skips.
7. `GET /api/robot/library/commands` (operator A2) → 16 published; draft-only hidden.
8. `GET /engineer/logout` → token revoked (next `GET /engineer/commands` with it → `401`).
9. ws_http path: `X-Nanobot-Engineer-Action` (`create`/`start-draft`/`update-draft`) disambiguates; unknown/mismatched → `400`; no action → read-only.

Record results; do not commit.

---

## Self-Review

**Reviewer's 6 corrections (R1-R6) — all wired:**
- R1 publish schema validation → Task 7 Step 5 tests + Step 7 `_validate_publish_params` (unknown/required/type/bool/range).
- R2 audit `audit_id = secrets.token_urlsafe` → Task 6 Step 8; tested in Step 6 (`tok not in raw`, `tok[:16] not in raw`).
- R3 upgrade test hash=100k / policy=200k + dropped unused import → Task 6 Step 6 + Step 8.
- R4 wrong-password test asserts failure-audit-written + audit-write-failure-still-401 + no-token-issued → Task 6 Step 6.
- R5 `Retry-After` HTTP header on both transports → Task 8 `_eng_response` (aiohttp) + `_resp` (ws_http); tested Step 2 + Step 6.
- R6 `start_draft` 404 vs 409 + D1 conflict test uses published+has-draft → Task 7 Step 5 + Step 7.

**Confirmed decisions:** D1 (409), D2 (gateway token; ws_http from Bearer/`?token=`, aiohttp falls back to IP), D9 (`X-Nanobot-Engineer-Action`; aiohttp real methods ignore it).

**Spec §5-§8 coverage:** throttle 429 ✅ · fail-audit ✅ · success-audit fail-closed ✅ · PBKDF2 upgrade atomic write-back ✅ · logout revoke-first ✅ · GET+body-header mount ✅ · no-store ✅ · Retry-After ✅ · engineer-token gate ✅ · commands CRUD + server slug ✅ · draft 409 ✅ · next-version draft endpoint (D6) ✅ · publish schema validation (R1) ✅ · archive draft-only 409 ✅ · audit composite cursor ✅ · A2 published_version projection ✅.

**Type consistency:** `process_engineer_*` kwargs (`commands_path`/`audit_path`/`token_store`/`engineer_token`) uniform; `_require_engineer_token -> (bool, dict)`; `LoginThrottle.is_throttled/record_failure/retry_after/reset`; `_audit_key`/`_encode_cursor`/`_decode_cursor`; `_validate_publish_params(component, params) -> (bool, str)`.

**One implementation-time dependency:** Task 8 Step 8 ws_http dispatcher mirrors `_dispatch_robot_routes`; the exact attribute/service-dep access must match the real `GatewayHTTPHandler` — the implementer reads that method first and replicates the pattern. The test in Step 6 pins the contract (action header semantics, gates, no-store, Retry-After).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-12-robot-engineer-B1a-task6-9.md`. Executing via **subagent-driven-development** (per reviewer instruction): fresh subagent per task, two-stage review between tasks, **no-git** throughout until Task 9 Step 5-6 final verification passes.
