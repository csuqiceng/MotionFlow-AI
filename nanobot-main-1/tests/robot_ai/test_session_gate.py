from __future__ import annotations

from threading import Event, Thread

from robot_ai.execution.session_gate import SessionGateStore, SessionState


def test_get_none_returns_default_allow_cli_state() -> None:
    store = SessionGateStore()
    s = store.get(None)
    assert isinstance(s, SessionState)
    assert s.session_key == "_cli_"
    assert s.logged_in is True
    assert s.operator_permission is True
    assert s.wake_word_valid is True
    assert s.pending_plan_id is None
    assert s.confirmed is False


def test_get_empty_string_returns_default_allow_cli_state() -> None:
    store = SessionGateStore()
    s = store.get("")
    assert s.session_key == "_cli_"
    assert s.logged_in is True


def test_get_same_session_key_returns_same_state() -> None:
    store = SessionGateStore()
    s1 = store.get("sess-1")
    s2 = store.get("sess-1")
    assert s1 is s2


def test_get_different_session_keys_return_distinct_states() -> None:
    store = SessionGateStore()
    s1 = store.get("sess-1")
    s2 = store.get("sess-2")
    assert s1 is not s2
    assert s1.session_key == "sess-1"
    assert s2.session_key == "sess-2"


def test_set_pending_plan_then_confirm_is_confirmed_true() -> None:
    store = SessionGateStore()
    store.set_pending_plan("sess-1", "plan-A")
    assert store.confirm("sess-1", "plan-A") is True
    assert store.is_confirmed("sess-1", "plan-A") is True


def test_is_confirmed_before_confirm_is_false() -> None:
    store = SessionGateStore()
    store.set_pending_plan("sess-1", "plan-A")
    assert store.is_confirmed("sess-1", "plan-A") is False


def test_confirm_with_wrong_plan_id_is_false() -> None:
    store = SessionGateStore()
    store.set_pending_plan("sess-1", "plan-A")
    assert store.confirm("sess-1", "plan-B") is False
    assert store.is_confirmed("sess-1", "plan-A") is False


def test_is_confirmed_with_wrong_plan_id_is_false() -> None:
    store = SessionGateStore()
    store.set_pending_plan("sess-1", "plan-A")
    assert store.confirm("sess-1", "plan-A") is True
    # Wrong plan id passed to is_confirmed
    assert store.is_confirmed("sess-1", "plan-B") is False


def test_set_pending_plan_resets_confirmed_state() -> None:
    store = SessionGateStore()
    store.set_pending_plan("sess-1", "plan-A")
    assert store.confirm("sess-1", "plan-A") is True
    assert store.is_confirmed("sess-1", "plan-A") is True
    # New plan resets confirmation
    store.set_pending_plan("sess-1", "plan-B")
    assert store.is_confirmed("sess-1", "plan-A") is False
    assert store.is_confirmed("sess-1", "plan-B") is False


def test_confirm_without_set_pending_plan_is_false() -> None:
    store = SessionGateStore()
    # Never set a pending plan for this session
    assert store.confirm("sess-1", "plan-A") is False


def test_cli_path_supports_confirm_flow() -> None:
    store = SessionGateStore()
    store.set_pending_plan(None, "plan-cli")
    assert store.confirm(None, "plan-cli") is True
    assert store.is_confirmed(None, "plan-cli") is True


def test_restore_failed_stage_only_restores_plan_fields_in_place() -> None:
    store = SessionGateStore()
    held = store.get("sess-1")
    store.set_pending_plan("sess-1", "previous-plan")
    assert store.confirm("sess-1", "previous-plan") is True
    previous = store.snapshot("sess-1")

    store.set_pending_plan("sess-1", "failed-plan")
    held.logged_in = False
    held.operator_permission = False
    held.wake_word_valid = False

    assert store.restore_if_current("sess-1", "failed-plan", previous) is True
    restored = store.get("sess-1")
    assert restored is held
    assert restored.pending_plan_id == "previous-plan"
    assert restored.confirmed is True
    assert restored.logged_in is False
    assert restored.operator_permission is False
    assert restored.wake_word_valid is False


def test_restore_failed_stage_does_not_overwrite_newer_plan() -> None:
    store = SessionGateStore()
    store.set_pending_plan("sess-1", "previous-plan")
    previous = store.snapshot("sess-1")
    store.set_pending_plan("sess-1", "failed-plan")
    store.set_pending_plan("sess-1", "newer-plan")

    assert store.restore_if_current("sess-1", "failed-plan", previous) is False
    assert store.get("sess-1").pending_plan_id == "newer-plan"


def test_hold_confirmed_plan_blocks_concurrent_replacement_until_dispatch_finishes() -> None:
    store = SessionGateStore()
    store.set_pending_plan("sess-1", "plan-A")
    assert store.confirm("sess-1", "plan-A") is True
    holding = Event()
    release = Event()
    replaced = Event()

    def execute() -> None:
        with store.hold_confirmed_plan("sess-1", "plan-A") as claimed:
            assert claimed is True
            holding.set()
            assert release.wait(2)

    def replace() -> None:
        assert holding.wait(2)
        store.set_pending_plan("sess-1", "plan-B")
        replaced.set()

    execution = Thread(target=execute)
    replacement = Thread(target=replace)
    execution.start()
    replacement.start()
    assert holding.wait(2)
    assert replaced.wait(0.05) is False
    release.set()
    execution.join(2)
    replacement.join(2)

    assert replaced.is_set()
    assert store.get("sess-1").pending_plan_id == "plan-B"
    assert store.is_confirmed("sess-1", "plan-A") is False
