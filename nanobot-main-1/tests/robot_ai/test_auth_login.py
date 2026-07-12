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


def test_login_success_audit_failure_is_fail_closed_503(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_auth_login
    from robot_ai.library.auth import LoginThrottle, UserSessionStore, hash_password
    from robot_ai.library.users import UserRegistry
    reg = UserRegistry(tmp_path / "users.json", audit_path=tmp_path / "a.jsonl")
    reg.create("admin", "engineer", hash_password("s3cret", iterations=100_000))
    blocker = tmp_path / "blocker"  # audit path under a file
    blocker.write_text("x", encoding="utf-8")
    store = UserSessionStore()
    status, body = process_auth_login(
        {"username": "admin", "password": "s3cret", "role": "engineer"},
        users_path=str(tmp_path / "users.json"), audit_path=str(blocker / "a.jsonl"),
        token_store=store, throttle=LoginThrottle(), client_key="k")
    assert status == 503
    assert "user_token" not in body.get("data", {})
    assert len(store._sessions) == 0  # the internally-issued token WAS revoked


def test_logout_revokes_first_then_best_effort_audit(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_auth_login, process_auth_logout
    _seed(tmp_path)
    store = UserSessionStore()
    _, body = process_auth_login({"username": "admin", "password": "s3cret", "role": "engineer"},
                                  users_path=str(tmp_path / "users.json"), audit_path=str(tmp_path / "audit.jsonl"),
                                  token_store=store, throttle=LoginThrottle(), client_key="k")
    tok = body["data"]["user_token"]
    blocker = tmp_path / "b"
    blocker.write_text("x", encoding="utf-8")
    status, _ = process_auth_logout(tok, token_store=store, audit_path=str(blocker / "audit.jsonl"))
    assert status == 200 and store.check(tok) is None
