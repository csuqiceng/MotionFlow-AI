from __future__ import annotations

from robot_ai.library.auth import UserSessionStore


def _user(uid="u1", username="admin", role="engineer"):
    return {"user_id": uid, "username": username, "role": role}


def test_issue_check_revoke() -> None:
    store = UserSessionStore(ttl_seconds=3600)
    tok = store.issue(_user())
    session = store.check(tok)
    assert session is not None and session["user_id"] == "u1" and session["role"] == "engineer"
    assert session["session_id"]
    store.revoke(tok)
    assert store.check(tok) is None


def test_check_rejects_unknown() -> None:
    assert UserSessionStore().check("bogus") is None


def test_revoke_by_user_id() -> None:
    store = UserSessionStore()
    t1 = store.issue(_user("u1"))
    t2 = store.issue(_user("u1"))
    assert store.check(t1)["session_id"] != store.check(t2)["session_id"]  # type: ignore[index]
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
