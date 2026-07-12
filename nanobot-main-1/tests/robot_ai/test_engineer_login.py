from __future__ import annotations

import json
import time
from pathlib import Path

from robot_ai.library.auth import (
    EngineerTokenStore,
    LoginThrottle,
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
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")  # audit path under a file
    store = EngineerTokenStore()
    status, _ = _login({"password": "wrong"}, store=store, throttle=LoginThrottle(),
                        cfg=cfg, audit=blocker / "audit.jsonl")
    assert status == 401


def test_login_throttle_returns_429_with_retry_after(tmp_path: Path) -> None:
    """R5: 429 carries retry_after in the body (transport adds the HTTP header in Task 8)."""
    cfg = _write_config(tmp_path, hash_password("right"))
    throttle = LoginThrottle(max_attempts=3, window_seconds=300)
    store = EngineerTokenStore()
    audit = tmp_path / "audit.jsonl"
    for _ in range(3):
        _login({"password": "wrong"}, store=store, throttle=throttle, cfg=cfg, audit=audit, key="k")
    status, body = _login({"password": "wrong"}, store=store, throttle=throttle,
                           cfg=cfg, audit=audit, key="k")
    assert status == 429
    assert body["data"]["retry_after"] >= 1


def test_login_success_resets_throttle(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, hash_password("right"))
    throttle = LoginThrottle(max_attempts=3)
    store = EngineerTokenStore()
    audit = tmp_path / "audit.jsonl"
    for _ in range(2):
        _login({"password": "wrong"}, store=store, throttle=throttle, cfg=cfg, audit=audit, key="k")
    assert throttle.is_throttled("k") is False
    _login({"password": "right"}, store=store, throttle=throttle, cfg=cfg, audit=audit, key="k")
    assert throttle.is_throttled("k") is False
    assert throttle._fails.get("k") in (None, [])


def test_login_success_audit_failure_is_fail_closed_503(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, hash_password("right"))
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    store = EngineerTokenStore()
    status, body = _login({"password": "right"}, store=store, throttle=LoginThrottle(),
                           cfg=cfg, audit=blocker / "audit.jsonl")
    assert status == 503
    assert "engineer_token" not in body.get("data", {})
    # The success path issued a token internally before the audit write failed;
    # fail-closed must have revoked it -> the (fresh) store holds no live tokens.
    assert len(store._tokens) == 0


def test_login_upgrades_low_iteration_hash_and_writes_back_config(tmp_path: Path) -> None:
    """R3: stored hash 100_000, config policy 200_000 -> upgrade triggers."""
    cfg = _write_config(tmp_path, hash_password("right", iterations=100_000), iterations=200_000)
    from robot_ai.library.auth import extract_iterations
    assert extract_iterations(json.loads(cfg.read_text("utf-8"))["robotAi"]["engineer"]["passwordHash"]) == 100_000
    store = EngineerTokenStore()
    status, body = _login({"password": "right"}, store=store, throttle=LoginThrottle(),
                           cfg=cfg, audit=tmp_path / "audit.jsonl")
    assert status == 200
    new_hash = json.loads(cfg.read_text("utf-8"))["robot_ai"]["engineer"]["passwordHash"]
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
    blocker = tmp_path / "b"
    blocker.write_text("x", encoding="utf-8")
    status, _ = process_engineer_logout(tok, token_store=store, audit_path=blocker / "a.jsonl")
    assert status == 200
    assert store.check(tok) is False  # revoked despite audit failure
    # R2: even the logout audit (best-effort) must not contain the token.
    # (Here it failed to write, so nothing to inspect — covered by the success path.)


def test_login_resolves_config_path_none_via_nanobot_home(tmp_path: Path, monkeypatch) -> None:
    """Option A: when ws_http production wiring passes config_path=None (because
    `_engineer_config_path` isn't set), process_engineer_login must NOT crash on
    Path(None) -> TypeError -> 500. It resolves to get_config_path(), which honors
    NANOBOT_HOME. Hermetic: redirect NANOBOT_HOME to tmp_path and write the config
    there so the default-path resolution finds a real config with a known hash."""
    import nanobot.config.loader as loader
    from nanobot.api.robot_routes import process_engineer_login

    # Isolate from any set_config_path() a prior test may have called.
    saved = loader._current_config_path
    loader._current_config_path = None
    monkeypatch.setenv("NANOBOT_HOME", str(tmp_path))
    try:
        # get_config_path() resolves to Path(NANOBOT_HOME) / "config.json".
        # _write_config joins "config.json" itself, so pass the home dir.
        _write_config(tmp_path, hash_password("right", iterations=100_000), iterations=200_000)
        store = EngineerTokenStore()
        status, body = process_engineer_login(
            {"password": "right"}, token_store=store, throttle=LoginThrottle(),
            config_path=None, audit_path=str(tmp_path / "audit.jsonl"), client_key="k")
        assert status == 200
        assert store.check(body["data"]["engineer_token"]) is True
    finally:
        loader._current_config_path = saved

