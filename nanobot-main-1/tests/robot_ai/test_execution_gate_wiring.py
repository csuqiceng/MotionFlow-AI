from __future__ import annotations

import pytest

from robot_ai.execution import (
    PendingPlanStore,
    SessionGateStore,
    issue_confirm_code,
)
from robot_ai.models import RobotState


def _request(**kwargs):
    from robot_ai.zmotion_operator_control import ZMotionOperatorRequest

    return ZMotionOperatorRequest(**kwargs)


def _state() -> RobotState:
    return RobotState(
        mode="idle",
        axes_mm={"x": 900.0, "y": 0.0, "z": 1000.0, "rx": 0.0, "ry": 0.0, "rz": 0.0},
        alarms=[],
        connected_real_device=True,
    )


def _linear_parameters(**overrides) -> dict:
    values = {
        "target_pose": {
            "x": 900.0,
            "y": 0.0,
            "z": 999.0,
            "rx": 0.0,
            "ry": 0.0,
            "rz": 0.0,
        },
        "speed_pct": 5.0,
        "acceleration_pct": 5.0,
        "deceleration_pct": 5.0,
        "r_min": 800.0,
        "r_max": 1000.0,
        "z_min": 900.0,
        "z_max": 1100.0,
    }
    values.update(overrides)
    return values


@pytest.fixture
def stores(monkeypatch):
    """Inject fresh stores via the factory override."""
    from robot_ai import zmotion_operator_control as mod

    pending = PendingPlanStore()
    session = SessionGateStore()
    monkeypatch.setattr(mod, "_PENDING_PLAN_STORE", pending)
    monkeypatch.setattr(mod, "_SESSION_GATE_STORE", session)
    return pending, session


def _seed_confirmed_plan(
    pending: PendingPlanStore,
    session: SessionGateStore,
    *,
    session_key: str | None,
    command: str = "linear_move",
    parameters: dict | None = None,
) -> tuple[str, str]:
    parameters = parameters or _linear_parameters()
    plan = pending.create(
        command=command,
        parameters=parameters,
        dry_run_result={"ok": True, "state": "zmotion_operator_dry_run"},
    )
    session.set_pending_plan(session_key, plan.plan_id)
    assert session.confirm(session_key, plan.plan_id) is True
    assert pending.confirm(plan.plan_id) is True
    code = issue_confirm_code(plan.plan_id)
    return plan.plan_id, code


# ---------------------------------------------------------------------------
# _is_confirmed
# ---------------------------------------------------------------------------


def test_is_confirmed_webui_path_returns_true_for_valid_confirm_code(stores) -> None:
    from robot_ai.zmotion_operator_control import _is_confirmed

    pending, session = stores
    plan_id, code = _seed_confirmed_plan(
        pending, session, session_key="api:webui"
    )
    request = _request(
        command="linear_move",
        parameters=_linear_parameters(),
        execute_real=True,
        confirm_work_area_clear=True,
        confirm_estop_ready=True,
        pending_plan_id=plan_id,
        confirm_code=code,
    )
    assert _is_confirmed(request, _state(), session_key="api:webui") is True


def test_is_confirmed_webui_path_wrong_confirm_code_returns_false(stores) -> None:
    from robot_ai.zmotion_operator_control import _is_confirmed

    pending, session = stores
    plan_id, _ = _seed_confirmed_plan(pending, session, session_key="api:webui")
    request = _request(
        command="linear_move",
        parameters=_linear_parameters(),
        execute_real=True,
        confirm_work_area_clear=True,
        confirm_estop_ready=True,
        pending_plan_id=plan_id,
        confirm_code="RC-deadbeefdeadbeef",
    )
    assert _is_confirmed(request, _state(), session_key="api:webui") is False


def test_is_confirmed_webui_path_tampered_params_returns_false(stores) -> None:
    from robot_ai.zmotion_operator_control import _is_confirmed

    pending, session = stores
    plan_id, code = _seed_confirmed_plan(pending, session, session_key="api:webui")
    tampered = _linear_parameters()
    tampered["target_pose"]["z"] = 950.0  # differs from seeded plan
    request = _request(
        command="linear_move",
        parameters=tampered,
        execute_real=True,
        confirm_work_area_clear=True,
        confirm_estop_ready=True,
        pending_plan_id=plan_id,
        confirm_code=code,
    )
    assert _is_confirmed(request, _state(), session_key="api:webui") is False


def test_is_confirmed_webui_path_not_confirmed_in_session_returns_false(stores) -> None:
    from robot_ai.zmotion_operator_control import _is_confirmed

    pending, session = stores
    # Seed plan but DO NOT confirm in session.
    plan = pending.create(
        command="linear_move",
        parameters=_linear_parameters(),
        dry_run_result={"ok": True},
    )
    session.set_pending_plan("api:webui", plan.plan_id)
    pending.confirm(plan.plan_id)
    code = issue_confirm_code(plan.plan_id)
    request = _request(
        command="linear_move",
        parameters=_linear_parameters(),
        execute_real=True,
        confirm_work_area_clear=True,
        confirm_estop_ready=True,
        pending_plan_id=plan.plan_id,
        confirm_code=code,
    )
    assert _is_confirmed(request, _state(), session_key="api:webui") is False


def test_is_confirmed_cli_path_returns_true(stores) -> None:
    from robot_ai.zmotion_operator_control import (
        REAL_EXECUTION_CONFIRMATION_CODE,
        _is_confirmed,
    )

    request = _request(
        command="linear_move",
        parameters=_linear_parameters(),
        execute_real=True,
        confirm_work_area_clear=True,
        confirm_estop_ready=True,
        confirmation_code=REAL_EXECUTION_CONFIRMATION_CODE,
    )
    assert _is_confirmed(request, _state(), session_key=None) is True


def test_is_confirmed_neither_path_returns_false(stores) -> None:
    from robot_ai.zmotion_operator_control import _is_confirmed

    request = _request(
        command="linear_move",
        parameters=_linear_parameters(),
        execute_real=True,
        confirm_work_area_clear=True,
        confirm_estop_ready=True,
    )
    assert _is_confirmed(request, _state(), session_key=None) is False
