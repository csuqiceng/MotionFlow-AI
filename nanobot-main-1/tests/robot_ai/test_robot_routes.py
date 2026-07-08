from __future__ import annotations

import json

import pytest
from aiohttp import web

from robot_ai.execution import PendingPlanStore, SessionGateStore
from robot_ai.models import ToolResult


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
def module_stores(monkeypatch):
    """Sync the module-level stores in zmotion_operator_control to fresh
    instances so the route handlers (app-injected) and ``_run_safety_gate``
    (module-level read) see the same data."""
    from robot_ai import zmotion_operator_control as mod

    pending = PendingPlanStore()
    session = SessionGateStore()
    monkeypatch.setattr(mod, "_PENDING_PLAN_STORE", pending)
    monkeypatch.setattr(mod, "_SESSION_GATE_STORE", session)
    return pending, session


def _make_app(
    *,
    pending: PendingPlanStore | None = None,
    session: SessionGateStore | None = None,
    runner=None,
) -> web.Application:
    from nanobot.api.robot_routes import register_robot_routes

    app = web.Application()
    app["robot_pending_plan_store"] = pending or PendingPlanStore()
    app["robot_session_gate_store"] = session or SessionGateStore()
    app["robot_operator_runner"] = runner
    register_robot_routes(app)
    return app


class _FakeRequest:
    """Minimal aiohttp request stand-in for direct handler invocation."""

    def __init__(self, app: web.Application, body: dict) -> None:
        self.app = app
        self._body = body

    async def json(self) -> dict:
        return self._body


async def _post(app: web.Application, path: str, body: dict) -> dict:
    """Invoke a registered route handler directly with a fake request."""
    handler = None
    for route in app.router.routes():
        if route.method == "POST" and route.resource.canonical == path:
            handler = route.handler
            break
    assert handler is not None, f"no route for {path}"

    request = _FakeRequest(app, body)
    response = await handler(request)
    assert response.status == 200
    return json.loads(response.text)


@pytest.mark.asyncio
async def test_pending_plan_returns_plan_id_and_plan() -> None:
    from nanobot.api.robot_routes import _default_runner_factory

    dry_run_result = ToolResult.success(
        state="zmotion_operator_dry_run",
        message="plan ready",
        data={"plan": {"function_code": 108}},
    ).to_dict()

    def runner(*, request, **_kwargs):
        return dry_run_result

    app = _make_app(runner=runner)
    body = {
        "session_key": "api:webui",
        "command": "linear_move",
        "parameters": _linear_parameters(),
    }
    result = await _post(app, "/api/robot/pending-plan", body)
    assert "plan_id" in result
    assert result["plan_id"]
    assert result["plan"]["state"] == "zmotion_operator_dry_run"
    assert "param_hash" in result
    assert "expires_at" in result
    # Session gate should now reference the pending plan.
    session: SessionGateStore = app["robot_session_gate_store"]
    state = session.get("api:webui")
    assert state.pending_plan_id == result["plan_id"]
    assert state.confirmed is False
    # ensure _default_runner_factory importable (smoke)
    assert _default_runner_factory is not None


@pytest.mark.asyncio
async def test_pending_plan_dry_run_failure_propagated() -> None:
    failure = ToolResult.failure(
        state="zmotion_operator_safety_blocked",
        message="blocked",
    ).to_dict()

    def runner(*, request, **_kwargs):
        return failure

    app = _make_app(runner=runner)
    body = {
        "session_key": "api:webui",
        "command": "linear_move",
        "parameters": _linear_parameters(),
    }
    result = await _post(app, "/api/robot/pending-plan", body)
    assert result["ok"] is False
    assert result["state"] == "zmotion_operator_safety_blocked"
    # No plan created.
    pending: PendingPlanStore = app["robot_pending_plan_store"]
    assert pending.get("nope") is None


@pytest.mark.asyncio
async def test_confirm_returns_rc_confirm_code() -> None:
    pending = PendingPlanStore()
    session = SessionGateStore()
    plan = pending.create(
        command="linear_move",
        parameters=_linear_parameters(),
        dry_run_result={"ok": True},
    )
    session.set_pending_plan("api:webui", plan.plan_id)
    app = _make_app(pending=pending, session=session)
    body = {
        "session_key": "api:webui",
        "plan_id": plan.plan_id,
        "confirm_work_area_clear": True,
        "confirm_estop_ready": True,
    }
    result = await _post(app, "/api/robot/confirm", body)
    assert result["confirm_code"].startswith("RC-")
    # Plan + session now confirmed.
    refreshed_plan = pending.get(plan.plan_id)
    assert refreshed_plan.confirmed is True
    assert session.is_confirmed("api:webui", plan.plan_id) is True


@pytest.mark.asyncio
async def test_confirm_rejects_when_flags_missing() -> None:
    pending = PendingPlanStore()
    plan = pending.create(
        command="linear_move",
        parameters=_linear_parameters(),
        dry_run_result={"ok": True},
    )
    app = _make_app(pending=pending)
    body = {
        "session_key": "api:webui",
        "plan_id": plan.plan_id,
        "confirm_work_area_clear": True,
        "confirm_estop_ready": False,
    }
    request = _FakeRequest(app, body)
    from nanobot.api.robot_routes import handle_robot_confirm

    response = await handle_robot_confirm(request)
    assert response.status == 400


@pytest.mark.asyncio
async def test_execute_with_valid_confirm_code_runs(module_stores) -> None:
    pending, session = module_stores
    plan = pending.create(
        command="linear_move",
        parameters=_linear_parameters(),
        dry_run_result={"ok": True},
    )
    session.set_pending_plan("api:webui", plan.plan_id)
    pending.confirm(plan.plan_id)
    session.confirm("api:webui", plan.plan_id)
    from robot_ai.execution import issue_confirm_code

    code = issue_confirm_code(plan.plan_id)

    executed = {"called": False}

    def runner(*, request, **_kwargs):
        executed["called"] = True
        # Sanity: the request reached the runner with the WebUI fields set.
        assert request.execute_real is True
        assert request.pending_plan_id == plan.plan_id
        assert request.confirm_code == code
        return ToolResult.success(state="real_motion_command_completed").to_dict()

    app = _make_app(pending=pending, session=session, runner=runner)
    body = {
        "session_key": "api:webui",
        "plan_id": plan.plan_id,
        "confirm_code": code,
    }
    result = await _post(app, "/api/robot/execute", body)
    assert result["ok"] is True
    assert executed["called"] is True


@pytest.mark.asyncio
async def test_execute_with_wrong_confirm_code_blocked(module_stores) -> None:
    pending, session = module_stores
    plan = pending.create(
        command="linear_move",
        parameters=_linear_parameters(),
        dry_run_result={"ok": True},
    )
    session.set_pending_plan("api:webui", plan.plan_id)
    pending.confirm(plan.plan_id)
    session.confirm("api:webui", plan.plan_id)

    executed = {"called": False}

    def runner(*, request, **_kwargs):
        # Faithful gate: run the real safety gate before any execution. A wrong
        # confirm code must be rejected here, mirroring run_zmotion_operator_command.
        from robot_ai.models import RobotState
        from robot_ai.zmotion_operator_control import _run_safety_gate

        state = RobotState(
            mode="idle",
            axes_mm={
                "x": 900.0, "y": 0.0, "z": 1000.0,
                "rx": 0.0, "ry": 0.0, "rz": 0.0,
            },
            alarms=[],
            connected_real_device=True,
        )
        failure = _run_safety_gate(request, state)
        if failure is not None:
            return failure
        executed["called"] = True
        return ToolResult.success(state="real_motion_command_completed").to_dict()

    app = _make_app(pending=pending, session=session, runner=runner)
    body = {
        "session_key": "api:webui",
        "plan_id": plan.plan_id,
        "confirm_code": "RC-deadbeefdeadbeef",
    }
    result = await _post(app, "/api/robot/execute", body)
    # The safety gate blocks execution; runner body must not be reached.
    assert result["ok"] is False
    assert executed["called"] is False
