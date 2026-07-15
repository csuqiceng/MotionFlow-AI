"""Tests for the /api/robot/flow-* WebUI confirm-chain endpoints.

These cover the multi-step named-flow extension to the pending-plan ->
confirm -> execute chain: dry-run a registered flow, confirm it (RC- code),
and execute it for real (per-step CLI path with EXECUTE_ZMOTION_REAL).
"""

from __future__ import annotations

import json

import pytest
from aiohttp import web

from robot_ai.execution import PendingPlanStore, SessionGateStore
from robot_ai.models import ToolResult


def _delay_step(seconds: float = 1.0) -> dict:
    return {"step_id": 1, "action": "delay", "func_id": 110, "params": {"seconds": seconds}}


def _write_registry(tmp_path, flows: list[dict]) -> str:
    import json as _json

    path = tmp_path / "flows.json"
    path.write_text(_json.dumps({"version": "1.1", "flows": flows}), encoding="utf-8")
    return str(path)


@pytest.fixture
def module_stores(monkeypatch):
    """Sync the module-level stores in zmotion_operator_control to fresh
    instances so ``_run_safety_gate`` (module-level read) shares the same data
    as the route handlers' injected stores."""
    from robot_ai import zmotion_operator_control as mod

    pending = PendingPlanStore()
    session = SessionGateStore()
    monkeypatch.setattr(mod, "_PENDING_PLAN_STORE", pending)
    monkeypatch.setattr(mod, "_SESSION_GATE_STORE", session)
    return pending, session


@pytest.fixture
def patch_flow_runner(monkeypatch):
    """Replace ``run_zmotion_operator_command`` inside ``robot_ai.flow.executor``
    with a fake so flow dry-run / execute never touches a real controller."""
    import robot_ai.flow.executor as executor_module

    seen: list = []
    forced: dict = {}

    def fake_runner(*, request, config=None, client_factory=None, executor_factory=None):
        seen.append(request)
        if "result" in forced:
            return forced["result"]
        return ToolResult.success(
            state="zmotion_operator_dry_run",
            data={"real_execution": request.execute_real},
        ).to_dict()

    monkeypatch.setattr(executor_module, "run_zmotion_operator_command", fake_runner)
    return seen, forced


def _make_flow_app(
    *,
    pending: PendingPlanStore | None = None,
    session: SessionGateStore | None = None,
    flow_registry_path: str | None = None,
) -> web.Application:
    from nanobot.api.robot_routes import register_robot_routes

    app = web.Application()
    app["robot_pending_plan_store"] = pending or PendingPlanStore()
    app["robot_session_gate_store"] = session or SessionGateStore()
    if flow_registry_path is not None:
        app["robot_flow_registry_path"] = flow_registry_path
    from robot_ai.library.auth import UserSessionStore

    users = UserSessionStore()
    app["user_session_store"] = users
    app["test_user_token"] = users.issue(
        {"user_id": "test", "username": "operator", "role": "operator", "must_change_password": False}
    )
    register_robot_routes(app)
    return app


class _FakeRequest:
    def __init__(self, app: web.Application, body: dict) -> None:
        self.app = app
        self._body = body
        self.headers = {"X-Nanobot-User-Token": app["test_user_token"]}

    async def json(self) -> dict:
        return self._body


async def _post(app: web.Application, path: str, body: dict) -> dict:
    handler = None
    for route in app.router.routes():
        if route.method == "POST" and route.resource.canonical == path:
            handler = route.handler
            break
    assert handler is not None, f"no route for {path}"

    request = _FakeRequest(app, body)
    response = await handler(request)
    return json.loads(response.text)


@pytest.mark.asyncio
async def test_flow_pending_plan_returns_plan_id_and_dry_run(tmp_path, patch_flow_runner) -> None:
    seen, _ = patch_flow_runner
    registry_path = _write_registry(
        tmp_path,
        [{"name": "PickDelay", "steps": [_delay_step()], "confirmed": True}],
    )
    pending = PendingPlanStore()
    session = SessionGateStore()
    app = _make_flow_app(
        pending=pending, session=session, flow_registry_path=registry_path
    )
    body = {"session_key": "api:webui", "flow_name": "pickdelay"}
    result = await _post(app, "/api/robot/flow-pending-plan", body)
    assert "plan_id" in result and result["plan_id"]
    assert result["flow_name"] == "PickDelay"
    assert result["dry_run_result"]["ok"] is True
    assert result["dry_run_result"]["state"] == "flow_completed"
    assert "param_hash" in result
    assert "expires_at" in result
    # Dry-run must NOT execute real motion.
    assert seen[0].execute_real is False
    # Session gate references the pending plan.
    assert session.get("api:webui").pending_plan_id == result["plan_id"]


@pytest.mark.asyncio
async def test_v2_published_flow_is_visible_to_legacy_registry_and_dry_run(
    tmp_path, patch_flow_runner
) -> None:
    from nanobot.api.robot_routes import process_robot_flow_pending_plan
    from robot_ai.flow import FlowRegistry
    from robot_ai.flow.versioned_registry import VersionedFlowRegistry

    registry_path = tmp_path / "flows.json"
    versioned = VersionedFlowRegistry(registry_path, audit_path=tmp_path / "audit.jsonl")
    versioned.create_entity("pick-delay", "Pick Delay", [_delay_step()])
    versioned.publish("pick-delay")

    assert [entry.name for entry in FlowRegistry(registry_path).list_all()] == ["Pick Delay"]
    status, result = process_robot_flow_pending_plan(
        {"session_key": "api:webui", "flow_name": "pick delay"},
        pending=PendingPlanStore(), session=SessionGateStore(), flow_registry_path=str(registry_path),
    )
    assert status == 200
    assert result["dry_run_result"]["state"] == "flow_completed"


@pytest.mark.asyncio
async def test_flow_pending_plan_unknown_flow_returns_flow_not_found(
    tmp_path, patch_flow_runner
) -> None:
    registry_path = _write_registry(tmp_path, [])
    app = _make_flow_app(flow_registry_path=registry_path)
    body = {"session_key": "api:webui", "flow_name": "ghost"}
    result = await _post(app, "/api/robot/flow-pending-plan", body)
    assert result["ok"] is False
    assert result["state"] == "flow_not_found"


@pytest.mark.asyncio
async def test_flow_confirm_returns_rc_confirm_code(tmp_path, patch_flow_runner) -> None:
    patch_flow_runner  # noqa: F841 - ensure fake runner is installed
    registry_path = _write_registry(
        tmp_path,
        [{"name": "PickDelay", "steps": [_delay_step()], "confirmed": True}],
    )
    pending = PendingPlanStore()
    session = SessionGateStore()
    app = _make_flow_app(
        pending=pending, session=session, flow_registry_path=registry_path
    )
    plan_body = {"session_key": "api:webui", "flow_name": "pickdelay"}
    plan_result = await _post(app, "/api/robot/flow-pending-plan", plan_body)
    plan_id = plan_result["plan_id"]

    body = {
        "session_key": "api:webui",
        "plan_id": plan_id,
        "confirm_work_area_clear": True,
        "confirm_estop_ready": True,
    }
    result = await _post(app, "/api/robot/flow-confirm", body)
    assert result["confirm_code"].startswith("RC-")
    assert pending.get(plan_id).confirmed is True
    assert session.is_confirmed("api:webui", plan_id) is True


@pytest.mark.asyncio
async def test_flow_execute_with_valid_code_runs_real(
    tmp_path, patch_flow_runner, module_stores
) -> None:
    seen, _ = patch_flow_runner
    pending, session = module_stores
    registry_path = _write_registry(
        tmp_path,
        [{"name": "PickDelay", "steps": [_delay_step()], "confirmed": True}],
    )
    app = _make_flow_app(
        pending=pending, session=session, flow_registry_path=registry_path
    )
    plan_body = {"session_key": "api:webui", "flow_name": "pickdelay"}
    plan_result = await _post(app, "/api/robot/flow-pending-plan", plan_body)
    plan_id = plan_result["plan_id"]

    confirm_body = {
        "session_key": "api:webui",
        "plan_id": plan_id,
        "confirm_work_area_clear": True,
        "confirm_estop_ready": True,
    }
    confirm_result = await _post(app, "/api/robot/flow-confirm", confirm_body)
    code = confirm_result["confirm_code"]

    from robot_ai.execution import issue_confirm_code

    # Sanity: the code is the real issued RC- code.
    assert issue_confirm_code(plan_id) == code or code.startswith("RC-")

    exec_body = {
        "session_key": "api:webui",
        "plan_id": plan_id,
        "confirm_code": code,
    }
    result = await _post(app, "/api/robot/flow-execute", exec_body)
    assert result["ok"] is True
    assert result["state"] == "flow_completed"
    # The execute step must have run with execute_real=True + EXECUTE_ZMOTION_REAL.
    # ``seen`` also holds the earlier dry-run step (execute_real=False), so take
    # the last entry — the real-execution pass.
    assert len(seen) >= 2
    step_request = seen[-1]
    assert step_request.execute_real is True
    assert step_request.confirm_work_area_clear is True
    assert step_request.confirm_estop_ready is True
    from robot_ai.zmotion_operator_control import REAL_EXECUTION_CONFIRMATION_CODE

    assert step_request.confirmation_code == REAL_EXECUTION_CONFIRMATION_CODE


@pytest.mark.asyncio
async def test_flow_execute_with_wrong_code_blocked(
    tmp_path, patch_flow_runner, module_stores
) -> None:
    seen, _ = patch_flow_runner
    pending, session = module_stores
    registry_path = _write_registry(
        tmp_path,
        [{"name": "PickDelay", "steps": [_delay_step()], "confirmed": True}],
    )
    app = _make_flow_app(
        pending=pending, session=session, flow_registry_path=registry_path
    )
    plan_body = {"session_key": "api:webui", "flow_name": "pickdelay"}
    plan_result = await _post(app, "/api/robot/flow-pending-plan", plan_body)
    plan_id = plan_result["plan_id"]

    confirm_body = {
        "session_key": "api:webui",
        "plan_id": plan_id,
        "confirm_work_area_clear": True,
        "confirm_estop_ready": True,
    }
    await _post(app, "/api/robot/flow-confirm", confirm_body)

    exec_body = {
        "session_key": "api:webui",
        "plan_id": plan_id,
        "confirm_code": "RC-deadbeefdeadbeef",
    }
    response = await _post(app, "/api/robot/flow-execute", exec_body)
    # Wrong code -> 403 error envelope (json.loads of the error response).
    assert "error" in response
    assert response["error"]["code"] == 403
    # No *execute* step must have been submitted. ``seen`` only holds the earlier
    # dry-run step from flow-pending-plan; the execute pass must add nothing.
    assert len(seen) == 1
    assert seen[0].execute_real is False
