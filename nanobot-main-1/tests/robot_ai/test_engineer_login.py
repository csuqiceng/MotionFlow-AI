from __future__ import annotations

import json
import time
from pathlib import Path

from robot_ai.library.auth import (
    LoginThrottle,
    UserSessionStore,
    hash_password,
    verify_password,
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


def _seed_admin(tmp_path: Path, password: str = "s3cret", *, iterations: int = 100_000,
                enabled: bool = True) -> Path:
    """Create a users.json with an enabled `admin` engineer user (Task 6 alias routes
    /api/robot/engineer/login -> process_auth_login(admin/engineer)). Returns users.json path."""
    from robot_ai.library.users import UserRegistry
    users_json = tmp_path / "users.json"
    audit = tmp_path / "audit.jsonl"
    reg = UserRegistry(users_json, audit_path=audit)
    reg.create("admin", "engineer", hash_password(password, iterations=iterations), enabled=enabled)
    return users_json


def _login(body, *, store, throttle, users_json, audit, key="k"):
    """Task 6 alias: process_engineer_login now routes through process_auth_login."""
    from nanobot.api.robot_routes import process_engineer_login
    return process_engineer_login(body, token_store=store, throttle=throttle,
                                  users_path=str(users_json), audit_path=str(audit), client_key=key)


def test_login_success_issues_token_and_audits(tmp_path: Path) -> None:
    users_json = _seed_admin(tmp_path, "s3cret")
    audit = tmp_path / "audit.jsonl"
    store = UserSessionStore()
    status, body = _login({"password": "s3cret"}, store=store,
                          throttle=LoginThrottle(), users_json=users_json, audit=audit)
    assert status == 200
    # Task 6 alias returns user_token AND a mirrored engineer_token (old-client compat).
    tok = body["data"]["user_token"]
    assert body["data"]["engineer_token"] == tok
    session = store.check(tok)
    assert session is not None and session["role"] == "engineer"
    assert body["data"]["expires_in"] == 8 * 3600
    entries = [json.loads(ln) for ln in audit.read_text("utf-8").splitlines() if ln.strip()]
    assert any(e["action"] == "user_login" and e["result"] == "success" for e in entries)
    # R2: audit must NOT contain the password, the full token, or the token prefix.
    raw = audit.read_text("utf-8")
    assert "s3cret" not in raw
    assert tok not in raw
    assert tok[:16] not in raw
    assert all(e.get("audit_id") != tok[:16] for e in entries)


def test_login_wrong_password_rejected_401_no_token(tmp_path: Path) -> None:
    """R4: drop the tautology; assert failure audit written, no token issued."""
    users_json = _seed_admin(tmp_path, "right")
    audit = tmp_path / "audit.jsonl"
    store = UserSessionStore()
    before = len(store._sessions)
    status, body = _login({"password": "wrong"}, store=store,
                          throttle=LoginThrottle(), users_json=users_json, audit=audit)
    assert status == 401
    assert len(store._sessions) == before  # no token issued
    entries = [json.loads(ln) for ln in audit.read_text("utf-8").splitlines() if ln.strip()]
    assert any(e["action"] == "user_login" and e["result"] == "failure" for e in entries)


def test_login_failure_audit_write_failure_still_returns_401(tmp_path: Path) -> None:
    """R4(b): a failed-login audit write failure is non-blocking -> still 401."""
    users_json = _seed_admin(tmp_path, "right")
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")  # audit path under a file
    store = UserSessionStore()
    status, _ = _login({"password": "wrong"}, store=store, throttle=LoginThrottle(),
                       users_json=users_json, audit=blocker / "audit.jsonl")
    assert status == 401


def test_login_throttle_returns_429_with_retry_after(tmp_path: Path) -> None:
    """R5: 429 carries retry_after in the body (transport adds the HTTP header in Task 8)."""
    users_json = _seed_admin(tmp_path, "right")
    throttle = LoginThrottle(max_attempts=3, window_seconds=300)
    store = UserSessionStore()
    audit = tmp_path / "audit.jsonl"
    for _ in range(3):
        _login({"password": "wrong"}, store=store, throttle=throttle,
               users_json=users_json, audit=audit, key="k")
    status, body = _login({"password": "wrong"}, store=store, throttle=throttle,
                          users_json=users_json, audit=audit, key="k")
    assert status == 429
    assert body["data"]["retry_after"] >= 1


def test_login_success_resets_throttle(tmp_path: Path) -> None:
    users_json = _seed_admin(tmp_path, "right")
    throttle = LoginThrottle(max_attempts=3)
    store = UserSessionStore()
    audit = tmp_path / "audit.jsonl"
    for _ in range(2):
        _login({"password": "wrong"}, store=store, throttle=throttle,
               users_json=users_json, audit=audit, key="k")
    assert throttle.is_throttled("k") is False
    _login({"password": "right"}, store=store, throttle=throttle,
           users_json=users_json, audit=audit, key="k")
    assert throttle.is_throttled("k") is False
    assert throttle._fails.get("k") in (None, [])


def test_login_success_audit_failure_is_fail_closed_503(tmp_path: Path) -> None:
    users_json = _seed_admin(tmp_path, "right")
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    store = UserSessionStore()
    status, body = _login({"password": "right"}, store=store, throttle=LoginThrottle(),
                          users_json=users_json, audit=blocker / "audit.jsonl")
    assert status == 503
    assert "user_token" not in body.get("data", {}) and "engineer_token" not in body.get("data", {})
    # The success path issued a token internally before the audit write failed;
    # fail-closed must have revoked it -> the (fresh) store holds no live sessions.
    assert len(store._sessions) == 0


def test_login_succeeds_and_does_not_mutate_stored_hash(tmp_path: Path) -> None:
    """Task 6 alias routes through process_auth_login, which performs NO PBKDF2
    iteration-upgrade-on-login (the B1a upgrade path was removed). The stored hash
    must be unchanged after a successful login."""
    users_json = _seed_admin(tmp_path, "right", iterations=100_000)
    before = json.loads(users_json.read_text("utf-8"))
    admin_before = next(u for u in before["users"].values() if u["username"] == "admin")["password_hash"]
    store = UserSessionStore()
    status, _ = _login({"password": "right"}, store=store, throttle=LoginThrottle(),
                       users_json=users_json, audit=tmp_path / "audit.jsonl")
    assert status == 200
    after = json.loads(users_json.read_text("utf-8"))
    admin_after = next(u for u in after["users"].values() if u["username"] == "admin")["password_hash"]
    assert admin_after == admin_before  # no upgrade / no rewrite
    assert verify_password("right", admin_after) is True


def test_login_admin_disabled_returns_403(tmp_path: Path) -> None:
    """Unified login returns 403 `user_disabled` when the admin account is disabled
    (e.g. fresh install where no B1a hash was migrated). Replaces the B1a
    `engineer_password_not_configured` 403 assertion."""
    users_json = _seed_admin(tmp_path, "x", enabled=False)
    status, body = _login({"password": "x"}, store=UserSessionStore(),
                          throttle=LoginThrottle(), users_json=users_json, audit=tmp_path / "a.jsonl")
    assert status == 403
    assert body["error"]["code"] == "user_disabled"


def test_login_admin_missing_returns_401_no_existence_leak(tmp_path: Path) -> None:
    """No admin user in users.json -> unified login returns 401 invalid_credentials
    (never reveals whether the user exists)."""
    from robot_ai.library.users import UserRegistry
    users_json = tmp_path / "users.json"
    # Create the file but with no admin user (only an operator).
    UserRegistry(users_json, audit_path=tmp_path / "a.jsonl").create("op", "operator", hash_password("x"))
    status, body = _login({"password": "x"}, store=UserSessionStore(),
                          throttle=LoginThrottle(), users_json=users_json, audit=tmp_path / "a.jsonl")
    assert status == 401
    assert body["error"]["code"] == "invalid_credentials"


def test_logout_revokes_token_first_then_best_effort_audit(tmp_path: Path) -> None:
    """Revoke BEFORE audit; audit failure does not change the 200 outcome (R2/§5)."""
    from nanobot.api.robot_routes import process_engineer_logout
    users_json = _seed_admin(tmp_path, "right")
    store = UserSessionStore()
    _, body = _login({"password": "right"}, store=store, throttle=LoginThrottle(),
                     users_json=users_json, audit=tmp_path / "a.jsonl")
    tok = body["data"]["user_token"]
    assert store.check(tok) is not None
    blocker = tmp_path / "b"
    blocker.write_text("x", encoding="utf-8")
    status, _ = process_engineer_logout(tok, token_store=store, audit_path=blocker / "a.jsonl")
    assert status == 200
    assert store.check(tok) is None  # revoked despite audit failure
    # R2: even the logout audit (best-effort) must not contain the token.
    # (Here it failed to write, so nothing to inspect — covered by the success path.)


def test_login_resolves_users_path_none_to_default(tmp_path: Path, monkeypatch) -> None:
    """Task 6 alias: process_engineer_login no longer reads config (config_path is
    ignored). The equivalent default-resolution path is users_path=None, which must
    NOT crash (the B1a Path(None)->TypeError->500 bug) and must resolve to the
    default users.json. Hermetic: monkeypatch DEFAULT_USERS_PATH so the default
    points under tmp_path, then seed the admin there."""
    import os

    import nanobot.api.robot_routes as routes
    import robot_ai.library.users as users_mod
    from nanobot.api.robot_routes import process_engineer_login
    from robot_ai.library.auth import LoginThrottle, UserSessionStore

    users_json = tmp_path / "users.json"
    monkeypatch.setattr(users_mod, "DEFAULT_USERS_PATH", str(users_json))
    monkeypatch.setattr(routes, "_resolve_users_path",
                        lambda up: str(users_json) if not up else os.path.expanduser(up))
    _seed_admin(tmp_path, "right", iterations=100_000)
    store = UserSessionStore()
    status, body = process_engineer_login(
        {"password": "right"}, token_store=store, throttle=LoginThrottle(),
        users_path=None, audit_path=str(tmp_path / "audit.jsonl"), client_key="k")
    assert status == 200
    assert store.check(body["data"]["user_token"]) is not None
