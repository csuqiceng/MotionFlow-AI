from __future__ import annotations

from robot_ai.execution.confirm_code import issue_confirm_code, verify_confirm_code


def test_issue_returns_code_starting_with_rc_prefix() -> None:
    code = issue_confirm_code("plan-123")
    assert code.startswith("RC-")
    # Signature portion present (16 hex chars after prefix)
    assert len(code) == len("RC-") + 16


def test_verify_with_issued_code_is_true() -> None:
    plan_id = "plan-abc"
    code = issue_confirm_code(plan_id)
    assert verify_confirm_code(plan_id, code) is True


def test_verify_rejects_llm_execute_zmotion_real() -> None:
    # The LLM's literal code must NOT be accepted as a valid confirm code.
    # (The plan_id is intentionally unused here; we only assert the literal is rejected.)
    issue_confirm_code("plan-1")
    assert verify_confirm_code("plan-1", "EXECUTE_ZMOTION_REAL") is False


def test_verify_rejects_wrong_rc_code() -> None:
    assert verify_confirm_code("plan-1", "RC-deadbeefdeadbeef") is False


def test_verify_rejects_code_for_different_plan_id() -> None:
    code = issue_confirm_code("plan-A")
    assert verify_confirm_code("plan-B", code) is False


def test_verify_rejects_empty_code() -> None:
    assert verify_confirm_code("plan-1", "") is False


def test_verify_rejects_none_code() -> None:
    assert verify_confirm_code("plan-1", None) is False  # type: ignore[arg-type]


def test_verify_rejects_code_without_rc_prefix() -> None:
    assert verify_confirm_code("plan-1", "deadbeefdeadbeef") is False


def test_issue_same_plan_id_within_same_window_yields_same_code() -> None:
    # Deterministic within a time window (same plan_id + window -> same sig)
    c1 = issue_confirm_code("plan-1")
    c2 = issue_confirm_code("plan-1")
    assert c1 == c2


def test_verify_accepts_previous_window_code(monkeypatch) -> None:
    # The verify function accepts the current window and +/-1 neighboring windows
    # to avoid edge-expiry flakiness. Issue a code, then advance time by one full
    # window so the code is from the "previous" window relative to verify time.
    import robot_ai.execution.confirm_code as cc

    ttl = 100.0
    real_time = cc.time.time
    t0 = real_time()
    monkeypatch.setattr(cc.time, "time", lambda: t0)
    code = issue_confirm_code("plan-1", ttl_sec=ttl)
    # Move to the next absolute window. Adding a fixed duration is flaky when
    # t0 is near the end of a window because it can jump two window indexes.
    next_window_start = (int(t0 / ttl) + 1) * ttl
    monkeypatch.setattr(cc.time, "time", lambda: next_window_start + 0.1)
    assert verify_confirm_code("plan-1", code, ttl_sec=ttl) is True


def test_verify_rejects_code_two_windows_old(monkeypatch) -> None:
    # A code from two windows ago must NOT verify (tolerance is only +/-1).
    import robot_ai.execution.confirm_code as cc

    ttl = 100.0
    real_time = cc.time.time
    t0 = real_time()
    monkeypatch.setattr(cc.time, "time", lambda: t0)
    code = issue_confirm_code("plan-1", ttl_sec=ttl)
    monkeypatch.setattr(cc.time, "time", lambda: t0 + ttl * 2.1)
    assert verify_confirm_code("plan-1", code, ttl_sec=ttl) is False
