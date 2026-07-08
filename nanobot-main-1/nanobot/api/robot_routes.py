"""HTTP routes for the robot AI WebUI dry-run -> confirm -> execute flow.

These three endpoints back the WebUI pending-plan confirmation path:

* ``POST /api/robot/pending-plan`` — dry-run a command and stage a pending plan
  (returns ``plan_id`` + the dry-run plan + ``param_hash`` + ``expires_at``).
* ``POST /api/robot/confirm`` — operator confirms the work area + estop; issues a
  backend ``RC-`` confirm code bound to the plan.
* ``POST /api/robot/execute`` — execute the staged plan for real; the
  ``_run_safety_gate`` in ``robot_ai.zmotion_operator_control`` verifies the
  pending plan + session gate + confirm code before any write is issued.

The handlers read their stores and operator runner from ``request.app`` so tests
can inject fakes:

* ``app["robot_pending_plan_store"]``  — :class:`PendingPlanStore`
* ``app["robot_session_gate_store"]``  — :class:`SessionGateStore`
* ``app["robot_operator_runner"]``     — callable matching
  :func:`run_zmotion_operator_command` (``(*, request, ...) -> dict``); when
  absent, the module default is used.
"""

from __future__ import annotations

from typing import Any, Callable

from aiohttp import web

from nanobot.agent.tools.context import RequestContext, bind_request_context, reset_request_context
from robot_ai.execution import PendingPlanStore, SessionGateStore, issue_confirm_code
from robot_ai.zmotion_operator_control import (
    _PENDING_PLAN_STORE as _DEFAULT_PENDING_PLAN_STORE,
)
from robot_ai.zmotion_operator_control import (
    _SESSION_GATE_STORE as _DEFAULT_SESSION_GATE_STORE,
)
from robot_ai.zmotion_operator_control import (
    ZMotionOperatorRequest,
    run_zmotion_operator_command,
)

__all__ = (
    "handle_robot_pending_plan",
    "handle_robot_confirm",
    "handle_robot_execute",
    "register_robot_routes",
    "create_robot_app",
    "process_robot_pending_plan",
    "process_robot_confirm",
    "process_robot_execute",
    "ROBOT_BODY_HEADER",
)

# Header used to carry the JSON request payload when the robot routes are
# served through the WebSocket gateway dispatcher (``nanobot/webui/ws_http.py``).
# The gateway is built on the ``websockets`` library, whose ``process_request``
# hook only receives HTTP *GET* requests (it rejects POST at the protocol
# level) and never exposes a request body. Payloads therefore travel in a
# custom header, mirroring the existing ``X-Nanobot-Automation-Values`` /
# ``X-Nanobot-MCP-Values`` convention.
ROBOT_BODY_HEADER = "X-Nanobot-Robot-Body"


def _default_runner_factory() -> Callable[..., dict[str, Any]]:
    """Return the default operator runner (lazy so the module stays importable
    even if ZMotion backend deps are not installed at import time)."""
    return run_zmotion_operator_command


def _get_stores(request: web.Request) -> tuple[PendingPlanStore, SessionGateStore]:
    """Return the pending-plan + session-gate stores for this app.

    Defaults to the process-wide module singletons in
    ``robot_ai.zmotion_operator_control`` so that the routes' pending-plan /
    confirm flow and ``_is_confirmed`` (read inside ``_run_safety_gate``) share
    the same store instances. Tests may override by setting
    ``app["robot_pending_plan_store"]`` / ``app["robot_session_gate_store"]``.
    """
    pending: PendingPlanStore | None = request.app.get("robot_pending_plan_store")
    session: SessionGateStore | None = request.app.get("robot_session_gate_store")
    if pending is None:
        pending = _DEFAULT_PENDING_PLAN_STORE
        request.app["robot_pending_plan_store"] = pending
    if session is None:
        session = _DEFAULT_SESSION_GATE_STORE
        request.app["robot_session_gate_store"] = session
    return pending, session


def _get_runner(request: web.Request) -> Callable[..., dict[str, Any]]:
    runner = request.app.get("robot_operator_runner")
    return runner if runner is not None else _default_runner_factory()


def _error_json(status: int, message: str, err_type: str = "invalid_request_error") -> web.Response:
    return web.json_response(
        {"error": {"message": message, "type": err_type, "code": status}},
        status=status,
    )


# ---------------------------------------------------------------------------
# Shared core logic (HTTP-transport-agnostic).
#
# These ``process_*`` functions take already-parsed inputs plus the stores /
# runner and return a ``(status_code, result_dict)`` tuple. Both the aiohttp
# handlers below and the WebSocket gateway dispatcher
# (``nanobot/webui/ws_http.py``) call them, so the route behavior stays
# identical across ``nanobot api`` and ``nanobot gateway``.
# ---------------------------------------------------------------------------


def process_robot_pending_plan(
    body: Any,
    *,
    pending: PendingPlanStore,
    session: SessionGateStore,
    runner: Callable[..., dict[str, Any]],
) -> tuple[int, dict[str, Any]]:
    """Core logic for the pending-plan endpoint.

    Returns ``(status_code, result_dict)``. On a dry-run failure the result
    dict is the dry-run failure payload (status 200, ``ok=False``).
    """
    if not isinstance(body, dict):
        return 400, {"error": {"message": "Request body must be a JSON object",
                               "type": "invalid_request_error", "code": 400}}

    session_key = body.get("session_key")
    command = body.get("command")
    parameters = body.get("parameters")
    if not isinstance(command, str) or not command:
        return 400, {"error": {"message": "'command' is required",
                               "type": "invalid_request_error", "code": 400}}
    if not isinstance(parameters, dict):
        return 400, {"error": {"message": "'parameters' must be an object",
                               "type": "invalid_request_error", "code": 400}}

    dry_run_request = ZMotionOperatorRequest(
        command=command,
        parameters=parameters,
        execute_real=False,
    )
    dry_run_result = runner(request=dry_run_request)

    if not dry_run_result.get("ok"):
        # Dry-run failed (safety blocked, invalid params, etc.). Propagate as-is.
        return 200, dry_run_result

    plan = pending.create(
        command=command,
        parameters=parameters,
        dry_run_result=dry_run_result,
    )
    session.set_pending_plan(session_key, plan.plan_id)
    return 200, {
        "plan_id": plan.plan_id,
        "plan": dry_run_result,
        "param_hash": plan.param_hash,
        "expires_at": plan.expires_at,
    }


def process_robot_confirm(
    body: Any,
    *,
    pending: PendingPlanStore,
    session: SessionGateStore,
) -> tuple[int, dict[str, Any]]:
    """Core logic for the confirm endpoint."""
    if not isinstance(body, dict):
        return 400, {"error": {"message": "Request body must be a JSON object",
                               "type": "invalid_request_error", "code": 400}}

    session_key = body.get("session_key")
    plan_id = body.get("plan_id")
    confirm_work_area_clear = bool(body.get("confirm_work_area_clear"))
    confirm_estop_ready = bool(body.get("confirm_estop_ready"))

    if not isinstance(plan_id, str) or not plan_id:
        return 400, {"error": {"message": "'plan_id' is required",
                               "type": "invalid_request_error", "code": 400}}
    if not (confirm_work_area_clear and confirm_estop_ready):
        return 400, {"error": {
            "message": "Both confirm_work_area_clear and confirm_estop_ready must be true.",
            "type": "invalid_request_error", "code": 400}}

    plan = pending.get(plan_id)
    if plan is None:
        return 404, {"error": {"message": "Pending plan not found or expired.",
                               "type": "invalid_request_error", "code": 404}}

    if not session.confirm(session_key, plan_id):
        return 409, {"error": {
            "message": "Session has no matching pending plan to confirm.",
            "type": "invalid_request_error", "code": 409}}
    pending.confirm(plan_id)
    confirm_code = issue_confirm_code(plan_id)
    return 200, {"confirm_code": confirm_code}


def process_robot_execute(
    body: Any,
    *,
    pending: PendingPlanStore,
    runner: Callable[..., dict[str, Any]],
) -> tuple[int, dict[str, Any]]:
    """Core logic for the execute endpoint."""
    if not isinstance(body, dict):
        return 400, {"error": {"message": "Request body must be a JSON object",
                               "type": "invalid_request_error", "code": 400}}

    session_key = body.get("session_key")
    plan_id = body.get("plan_id")
    confirm_code = body.get("confirm_code")

    if not isinstance(plan_id, str) or not plan_id:
        return 400, {"error": {"message": "'plan_id' is required",
                               "type": "invalid_request_error", "code": 400}}
    if not isinstance(confirm_code, str) or not confirm_code:
        return 400, {"error": {"message": "'confirm_code' is required",
                               "type": "invalid_request_error", "code": 400}}

    plan = pending.get(plan_id)
    if plan is None:
        return 404, {"error": {"message": "Pending plan not found or expired.",
                               "type": "invalid_request_error", "code": 404}}

    exec_request = ZMotionOperatorRequest(
        command=plan.command,
        parameters=plan.parameters,
        execute_real=True,
        confirm_work_area_clear=True,
        confirm_estop_ready=True,
        pending_plan_id=plan_id,
        confirm_code=confirm_code,
    )
    # NOTE: ``confirmation_code`` is intentionally NOT set to
    # EXECUTE_ZMOTION_REAL here; the WebUI must go through the pending-plan
    # verification path in ``_is_confirmed`` (verify_confirm_code + plan verify
    # + session gate). Bind the session_key into the request context so
    # ``current_request_session_key()`` resolves inside ``_is_confirmed``.
    ctx = RequestContext(channel="api", chat_id="robot", session_key=session_key)
    token = bind_request_context(ctx)
    try:
        result = runner(request=exec_request)
    finally:
        reset_request_context(token)
    return 200, result


async def handle_robot_pending_plan(request: web.Request) -> web.Response:
    """POST /api/robot/pending-plan — dry-run + stage a pending plan."""
    try:
        body = await request.json()
    except Exception:
        return _error_json(400, "Invalid JSON body")

    pending, session = _get_stores(request)
    runner = _get_runner(request)
    status, result = process_robot_pending_plan(
        body, pending=pending, session=session, runner=runner
    )
    return web.json_response(result, status=status)


async def handle_robot_confirm(request: web.Request) -> web.Response:
    """POST /api/robot/confirm — confirm a staged plan + issue an RC- code."""
    try:
        body = await request.json()
    except Exception:
        return _error_json(400, "Invalid JSON body")

    pending, session = _get_stores(request)
    status, result = process_robot_confirm(body, pending=pending, session=session)
    return web.json_response(result, status=status)


async def handle_robot_execute(request: web.Request) -> web.Response:
    """POST /api/robot/execute — execute a confirmed plan for real."""
    try:
        body = await request.json()
    except Exception:
        return _error_json(400, "Invalid JSON body")

    pending, _session = _get_stores(request)
    runner = _get_runner(request)
    status, result = process_robot_execute(body, pending=pending, runner=runner)
    return web.json_response(result, status=status)


def register_robot_routes(app: web.Application) -> None:
    """Register the three /api/robot/* routes on an existing aiohttp app."""
    app.router.add_post("/api/robot/pending-plan", handle_robot_pending_plan)
    app.router.add_post("/api/robot/confirm", handle_robot_confirm)
    app.router.add_post("/api/robot/execute", handle_robot_execute)


def create_robot_app() -> web.Application:
    """Build a standalone aiohttp app exposing only the /api/robot/* routes.

    Use this when the host process does not already run the nanobot gateway;
    otherwise prefer :func:`register_robot_routes` on the shared app.
    """
    app = web.Application()
    register_robot_routes(app)
    return app
