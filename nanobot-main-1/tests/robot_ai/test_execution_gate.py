from __future__ import annotations

from robot_ai.safety import (
    EXECUTION_GATE_CHECK_ORDER,
    ExecutionGateInput,
    evaluate_execution_gate,
)


def _payload(**overrides) -> ExecutionGateInput:
    base = {
        "action_type": "linear_move",
        "is_execution": True,
        "has_wake_word": True,
        "permission_ok": True,
        "missing_fields": (),
        "bounds_ok": True,
        "safety_ok": True,
        "requires_confirmation": True,
        "has_pending_confirm": True,
        "confirmed": True,
    }
    base.update(overrides)
    return ExecutionGateInput(**base)


def test_check_order_is_seven_steps_in_expected_sequence() -> None:
    assert EXECUTION_GATE_CHECK_ORDER == (
        "wake_word",
        "permission",
        "params_complete",
        "bounds",
        "safety_precheck",
        "pending_confirm",
        "confirmed",
    )


def test_non_execution_skips_gate() -> None:
    result = evaluate_execution_gate(_payload(is_execution=False))
    assert result.ok is True
    assert result.state == "gate_skipped_non_execution"


def test_all_pass_returns_execution_allowed() -> None:
    result = evaluate_execution_gate(_payload())
    assert result.ok is True
    assert result.state == "execution_allowed"


def test_missing_wake_word_blocks_first() -> None:
    result = evaluate_execution_gate(_payload(has_wake_word=False, permission_ok=False))
    assert result.ok is False
    assert result.state == "wake_word_required"
    assert result.errors[0]["code"] == "WAKE_WORD_REQUIRED"


def test_permission_denied() -> None:
    result = evaluate_execution_gate(_payload(permission_ok=False))
    assert result.state == "permission_denied"
    assert result.errors[0]["code"] == "PERMISSION_DENIED"


def test_missing_params_carries_fields() -> None:
    result = evaluate_execution_gate(_payload(missing_fields=("target_pose", "speed_pct")))
    assert result.state == "missing_params"
    assert result.errors[0]["code"] == "MISSING_REQUIRED_PARAMS"
    assert result.errors[0]["fields"] == ["target_pose", "speed_pct"]
    assert result.data["missing_fields"] == ["target_pose", "speed_pct"]


def test_bounds_failed() -> None:
    result = evaluate_execution_gate(_payload(bounds_ok=False))
    assert result.state == "bounds_failed"
    assert result.errors[0]["code"] == "PARAM_BOUNDS_FAILED"


def test_safety_precheck_failed() -> None:
    result = evaluate_execution_gate(_payload(safety_ok=False))
    assert result.state == "safety_precheck_failed"
    assert result.errors[0]["code"] == "SAFETY_PRECHECK_FAILED"


def test_confirmation_required_when_no_pending() -> None:
    result = evaluate_execution_gate(_payload(has_pending_confirm=False))
    assert result.state == "confirmation_required"
    assert result.errors[0]["code"] == "CONFIRMATION_REQUIRED"


def test_waiting_confirmation_when_pending_but_not_confirmed() -> None:
    result = evaluate_execution_gate(_payload(confirmed=False))
    assert result.state == "waiting_confirmation"
    assert result.errors[0]["code"] == "WAITING_CONFIRMATION"


def test_gate_ignores_confirmation_when_not_required() -> None:
    # Non-confirming action type: even without confirm flags, execution allowed.
    result = evaluate_execution_gate(
        _payload(requires_confirmation=False, has_pending_confirm=False, confirmed=False)
    )
    assert result.ok is True
    assert result.state == "execution_allowed"
