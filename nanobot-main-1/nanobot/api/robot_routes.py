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

from types import SimpleNamespace
from typing import Any, Callable

from aiohttp import web

from nanobot.agent.tools.context import RequestContext, bind_request_context, reset_request_context
from robot_ai.execution import PendingPlanStore, SessionGateStore, issue_confirm_code
from robot_ai.library.catalog import ComponentCatalog
from robot_ai.library.migration import DEFAULT_COMMANDS_PATH
from robot_ai.library.models import CommandStatus, RiskLevel
from robot_ai.zmotion_operator_control import (
    _PENDING_PLAN_STORE as _DEFAULT_PENDING_PLAN_STORE,
)
from robot_ai.zmotion_operator_control import (
    _SESSION_GATE_STORE as _DEFAULT_SESSION_GATE_STORE,
)
from robot_ai.zmotion_operator_control import (
    REAL_EXECUTION_CONFIRMATION_CODE,
    ZMotionOperatorRequest,
    run_zmotion_operator_command,
)

# Default path for the flow registry. Mirrors the convention used by the rest of
# ``robot_ai`` (``~/.nanobot/robot_ai/*.json``). The WebUI flow routes read
# flows from here unless a path is explicitly supplied.
DEFAULT_FLOW_REGISTRY_PATH = "~/.nanobot/robot_ai/flows.json"

_VALID_RISK_LEVELS = frozenset(r.value for r in RiskLevel)
_VALID_COMMAND_STATUSES = frozenset(s.value for s in CommandStatus)

__all__ = (
    "handle_robot_pending_plan",
    "handle_robot_confirm",
    "handle_robot_execute",
    "handle_robot_flow_pending_plan",
    "handle_robot_flow_confirm",
    "handle_robot_flow_execute",
    "handle_robot_status",
    "register_robot_routes",
    "create_robot_app",
    "process_robot_pending_plan",
    "process_robot_confirm",
    "process_robot_execute",
    "process_robot_flow_pending_plan",
    "process_robot_flow_confirm",
    "process_robot_flow_execute",
    "process_robot_status",
    "ROBOT_BODY_HEADER",
    "DEFAULT_FLOW_REGISTRY_PATH",
    "DEFAULT_COMMANDS_PATH",
    "handle_robot_library_commands",
    "handle_robot_library_command",
    "handle_robot_library_components",
    "handle_robot_library_component",
    "process_robot_library_commands",
    "process_robot_library_command",
    "process_robot_library_components",
    "process_robot_library_component",
    "process_robot_library_flows",
    "process_robot_library_flow",
    "process_robot_library_command_run",
    "process_robot_library_flow_run",
    "process_robot_library_command_execution",
    "process_robot_library_flow_execution",
    "process_robot_library_execution_status",
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


# Allowed operator system actions — direct safety/control buttons (not LLM).
_ROBOT_SYSTEM_ACTIONS = frozenset({
    "emergency_stop",
    "release_emergency_stop",
    "pause",
    "resume",
    "stop_current",
    "release_cancel",
    "alarm_reset",
})


def process_robot_system_action(
    body: Any,
    *,
    runner: Callable[..., dict[str, Any]],
) -> tuple[int, dict[str, Any]]:
    """Direct operator system action (急停/暂停/继续/停止当前/解除取消/报警复位).

    Runs immediately via the operator path with the real-execution confirmation
    code — no pending-plan/confirm chain (these are safety buttons that must
    fire instantly). ``alarm_reset`` is operator-only (not LLM-exposed).
    """
    if not isinstance(body, dict):
        return 400, {"error": {"message": "Request body must be a JSON object",
                               "type": "invalid_request_error", "code": 400}}
    action = body.get("action")
    if not isinstance(action, str) or action not in _ROBOT_SYSTEM_ACTIONS:
        return 400, {"error": {"message": f"Unknown or missing system action: {action!r}",
                               "type": "invalid_request_error", "code": 400}}
    req = ZMotionOperatorRequest(
        command="system",
        parameters={"action": action},
        execute_real=True,
        confirm_work_area_clear=True,
        confirm_estop_ready=True,
        confirmation_code=REAL_EXECUTION_CONFIRMATION_CODE,
    )
    ctx = RequestContext(channel="api", chat_id="robot", session_key="api")
    token = bind_request_context(ctx)
    try:
        result = runner(request=req)
    finally:
        reset_request_context(token)
    return 200, result


# Persistent status backend — connect once, reuse across polls. Creating a
# backend per /api/robot/status request leaked a ZAux_OpenEth connection every
# ~3s (Python GC doesn't call ZAux_Close), clogging the controller's session
# table and breaking coexistence with ZRobotView/HMIUI/Qt (code 3402). One
# long-lived client is sufficient; get_state() reconnects on failure.
_status_backend: Any = None


def _get_status_backend() -> Any:
    global _status_backend
    if _status_backend is None:
        from robot_ai.backends.factory import (
            RobotBackendConfig,
            create_robot_backend,
        )

        _status_backend = create_robot_backend(RobotBackendConfig.from_env())
    return _status_backend


def _current_execution_mode() -> str:
    """Return the configured execution mode (``robot_ai.execution.mode``).

    Falls back to ``"unknown"`` if the mode module cannot be imported — the
    frontend treats unknown as "render nothing mode-specific" rather than
    erroring, and a read-only status endpoint must never 500.
    """
    try:
        from robot_ai.execution.mode import EXECUTION_MODE

        return EXECUTION_MODE
    except Exception:  # noqa: BLE001
        return "unknown"


def process_robot_status() -> tuple[int, dict[str, Any]]:
    """Core logic for the read-only status endpoint.

    Reads the current robot state via :class:`RobotBackendConfig.from_env` →
    :func:`create_robot_backend` → ``get_state()`` and returns it normalized as
    ``{"ok": True, "data": {"robot_state": {...}}}``. If the controller is
    unreachable or the backend cannot be constructed, returns a
    ``mode="disconnected"`` snapshot instead of raising.
    """
    try:
        backend = _get_status_backend()
        state = backend.get_state()
        robot_state = state.to_dict() if hasattr(state, "to_dict") else dict(state)
        if not isinstance(robot_state, dict):
            robot_state = {"mode": "disconnected"}
        if "mode" not in robot_state:
            robot_state["mode"] = "unknown"
        return 200, {
            "ok": True,
            "data": {"robot_state": robot_state, "execution_mode": _current_execution_mode()},
        }
    except Exception as e:  # noqa: BLE001 — read-only status must never 500.
        return 200, {
            "ok": True,
            "data": {
                "robot_state": {
                    "mode": "disconnected",
                    "axes_mm": {},
                    "alarms": [f"status_error: {type(e).__name__}: {e}"],
                    "connected_real_device": False,
                    "cancel_latch": False,
                },
                "execution_mode": _current_execution_mode(),
            },
        }


def _resolve_commands_path(path: str | None) -> str:
    import os

    return os.path.expanduser(path or DEFAULT_COMMANDS_PATH)


def _resolve_audit_path(audit_path: str | None) -> str:
    import os

    from robot_ai.library.users import _default_audit_path

    return os.path.expanduser(audit_path or _default_audit_path())


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now().isoformat()


def _best_effort_audit(audit_path: str, entry: dict) -> None:
    """Append an audit entry; swallow OSError (failed-login audit is non-blocking)."""
    from robot_ai.library.migration import _audit_append

    try:
        _audit_append(audit_path, entry)
    except OSError:
        pass


def _resolve_users_path(users_path: str | None) -> str:
    import os

    from robot_ai.library.users import _default_users_path

    return os.path.expanduser(users_path or _default_users_path())


def _actor_dict(user: dict[str, Any]) -> dict[str, Any]:
    return {"actor": f"user:{user['user_id']}", "actor_user_id": user["user_id"],
            "actor_username": user["username"], "actor_role": user["role"]}


def process_auth_login(body: Any, *, users_path: str | None = None, audit_path: str | None = None,
                       token_store, throttle, client_key: str | None = None) -> tuple[int, dict[str, Any]]:
    """Unified login: throttle -> verify -> fail-closed success audit -> issue user token."""
    import secrets

    from robot_ai.library.auth import verify_password
    from robot_ai.library.migration import _audit_append
    from robot_ai.library.users import UserRegistry

    key = client_key or "anon"
    if throttle.is_throttled(key):
        return 429, {"ok": False, "data": {"retry_after": throttle.retry_after(key)},
                     "error": {"code": "too_many_attempts", "message": "Too many login attempts."}}

    body = body or {}
    username = str(body.get("username", ""))
    password = str(body.get("password", ""))
    role = str(body.get("role", ""))
    if role not in ("operator", "engineer"):
        throttle.record_failure(key)
        _best_effort_audit(_resolve_audit_path(audit_path),
                           {"action": "user_login", "actor": "anon", "result": "failure",
                            "reason": "bad_role", "audit_id": secrets.token_urlsafe(16),
                            "timestamp": _now_iso()})
        return 401, {"error": {"code": "invalid_credentials", "message": "Invalid credentials."}}

    reg = UserRegistry(_resolve_users_path(users_path), audit_path=_resolve_audit_path(audit_path))
    user = reg.get_by_username(username)
    if user is None or user["role"] != role:
        throttle.record_failure(key)
        _best_effort_audit(_resolve_audit_path(audit_path),
                           {"action": "user_login", "actor": "anon", "result": "failure",
                            "reason": "bad_user_or_role", "audit_id": secrets.token_urlsafe(16),
                            "timestamp": _now_iso()})
        return 401, {"error": {"code": "invalid_credentials", "message": "Invalid credentials."}}
    if not user["enabled"]:
        return 403, {"error": {"code": "user_disabled", "message": "Account is disabled."}}
    if not verify_password(password, user["password_hash"]):
        throttle.record_failure(key)
        _best_effort_audit(_resolve_audit_path(audit_path),
                           {"action": "user_login", "actor": f"user:{user['user_id']}",
                            "actor_user_id": user["user_id"], "actor_username": user["username"],
                            "actor_role": user["role"], "result": "failure", "reason": "bad_password",
                            "audit_id": secrets.token_urlsafe(16), "timestamp": _now_iso()})
        return 401, {"error": {"code": "invalid_credentials", "message": "Invalid credentials."}}

    throttle.reset(key)
    token = token_store.issue({"user_id": user["user_id"], "username": user["username"], "role": user["role"]})
    success = {"action": "user_login", **_actor_dict(user), "result": "success",
               "audit_id": secrets.token_urlsafe(16), "timestamp": _now_iso()}
    try:
        _audit_append(_resolve_audit_path(audit_path), success)
    except OSError:
        token_store.revoke(token)
        return 503, {"error": {"code": "audit_write_failed", "message": "Login audit could not be recorded."}}
    return 200, {"ok": True,
                 "data": {"user_token": token, "expires_in": token_store.ttl_seconds,
                          "user": {"user_id": user["user_id"], "username": user["username"], "role": user["role"]}}}


def process_auth_logout(user_token, *, token_store, audit_path: str | None = None,
                        session: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    """Revoke FIRST (safety > audit), then best-effort audit."""
    import secrets

    from robot_ai.library.migration import _audit_append
    token_store.revoke(user_token or "")
    actor = (_actor_dict(session) if session
             else {"actor": "user:?", "actor_role": None})
    try:
        _audit_append(_resolve_audit_path(audit_path),
                      {"action": "user_logout", **actor, "result": "success",
                       "audit_id": secrets.token_urlsafe(16), "timestamp": _now_iso()})
    except OSError:
        pass
    return 200, {"ok": True, "data": {"revoked": True}}


def _require_user_role(token_store, user_token, role: str | None) -> tuple[bool, dict, dict | None]:
    """Returns (ok, error_body, session). session=None on failure. role=None = any authenticated user."""
    session = token_store.check(user_token) if user_token else None
    if session is None:
        return False, {"error": {"code": "unauthorized", "message": "Valid user token required."}}, None
    if role is not None and session["role"] != role:
        return False, {"error": {"code": "forbidden", "message": f"role={role!r} required."}}, None
    return True, {}, session


def process_users_list(*, users_path: str | None = None, token_store=None, user_token=None):
    ok, err, _ = _require_user_role(token_store, user_token, "engineer")
    if not ok:
        return 403 if err["error"]["code"] == "forbidden" else 401, err
    from robot_ai.library.users import UserRegistry
    users = [{"user_id": u["user_id"], "username": u["username"], "role": u["role"],
              "enabled": u["enabled"], "created_at": u["created_at"], "updated_at": u["updated_at"]}
             for u in UserRegistry(_resolve_users_path(users_path)).list_all()]
    return 200, {"ok": True, "data": {"users": users}}


def process_users_create(body, *, users_path=None, audit_path=None, token_store=None,
                          user_token=None, actor=None):
    ok, err, _ = _require_user_role(token_store, user_token, "engineer")
    if not ok:
        return 403 if err["error"]["code"] == "forbidden" else 401, err
    from robot_ai.library.auth import hash_password
    from robot_ai.library.users import UserRegistry
    body = body or {}
    try:
        user = UserRegistry(_resolve_users_path(users_path), audit_path=_resolve_audit_path(audit_path)).create(
            str(body.get("username", "")), str(body.get("role", "")),
            hash_password(str(body.get("password", ""))), actor=actor)
    except ValueError as e:
        return 409, {"error": {"code": "user_exists", "message": str(e)}}
    return 201, {"ok": True, "data": {k: v for k, v in user.items() if k != "password_hash"}}


def process_users_patch(user_id, body, *, users_path=None, audit_path=None, token_store=None,
                         user_token=None, actor=None):
    ok, err, _ = _require_user_role(token_store, user_token, "engineer")
    if not ok:
        return 403 if err["error"]["code"] == "forbidden" else 401, err
    from robot_ai.library.users import LastEngineerError, UserRegistry
    body = body or {}
    reg = UserRegistry(_resolve_users_path(users_path), audit_path=_resolve_audit_path(audit_path))
    try:
        user = reg.update(user_id, enabled=body.get("enabled"), role=body.get("role"), actor=actor)
    except LastEngineerError as e:
        return 409, {"error": {"code": "last_engineer_protected", "message": str(e)}}
    except ValueError as e:
        return 404, {"error": {"code": "user_not_found", "message": str(e)}}
    if body.get("enabled") is False or body.get("role") is not None:
        token_store.revoke_by_user_id(user_id)  # disable or role-change -> kick
    return 200, {"ok": True, "data": {k: v for k, v in user.items() if k != "password_hash"}}


def process_users_reset_password(user_id, body, *, users_path=None, audit_path=None, token_store=None,
                                  user_token=None, actor=None):
    ok, err, session = _require_user_role(token_store, user_token, "engineer")
    if not ok:
        return 403 if err["error"]["code"] == "forbidden" else 401, err
    if session["user_id"] == user_id:
        return 409, {"error": {"code": "use_me_password",
                                "message": "Use /api/users/me/password to change your own password."}}
    from robot_ai.library.auth import hash_password
    from robot_ai.library.users import UserRegistry
    try:
        UserRegistry(_resolve_users_path(users_path), audit_path=_resolve_audit_path(audit_path)).set_password(
            user_id, hash_password(str((body or {}).get("new_password", ""))), actor=actor,
            action="user_password_reset")
    except ValueError as e:
        return 404, {"error": {"code": "user_not_found", "message": str(e)}}
    token_store.revoke_by_user_id(user_id)
    return 200, {"ok": True, "data": {"reset": user_id}}


def process_users_me_password(body, *, users_path=None, audit_path=None, token_store=None,
                               user_token=None, actor=None):
    ok, err, session = _require_user_role(token_store, user_token, None)  # any authenticated
    if not ok:
        return 401, err
    from robot_ai.library.auth import hash_password, verify_password
    from robot_ai.library.users import UserRegistry
    body = body or {}
    reg = UserRegistry(_resolve_users_path(users_path), audit_path=_resolve_audit_path(audit_path))
    user = reg.get(session["user_id"])
    if user is None or not verify_password(str(body.get("old_password", "")), user["password_hash"]):
        return 401, {"error": {"code": "invalid_credentials", "message": "Old password incorrect."}}
    reg.set_password(session["user_id"], hash_password(str(body.get("new_password", ""))), actor=actor)
    token_store.revoke_by_user_id(session["user_id"])  # self revoked -> re-login
    return 200, {"ok": True, "data": {"changed": True}}


def _load_published_commands(path: str) -> list[dict[str, Any]]:
    """Read commands.json (schema 1.0 or 2.0), return list of published Command dicts.

    Schema 2.0: version tree — project ``published_version`` per entity (skip null).
    Schema 1.0: list — return as-is (backward compat).
    """
    import json as _json
    import os as _os

    cpath = _os.path.expanduser(path)
    if not _os.path.exists(cpath):
        return []
    data = _json.loads(open(cpath, encoding="utf-8").read())
    commands = data.get("commands", [])
    if isinstance(commands, dict):  # schema 2.0 — version tree
        result = []
        for cid in sorted(commands):
            entity = commands[cid]
            pv = entity.get("published_version")
            if pv is None:
                continue  # no published version → invisible to operator
            pub = entity.get("versions", {}).get(str(pv))
            if pub:
                result.append(pub)
        return result
    return list(commands)  # schema 1.0 fallback


def _get_published_command(command_id: str, path: str) -> dict[str, Any] | None:
    """Get a single command's published version from commands.json."""
    for cmd in _load_published_commands(path):
        if cmd.get("id") == command_id:
            return cmd
    return None


def process_robot_library_commands(
    *,
    commands_path: str | None = None,
    component_id: str | None = None,
    risk_level: str | None = None,
    status: str | None = None,
    q: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Core logic for ``GET /api/robot/library/commands`` (read-only list)."""
    if risk_level is not None and risk_level not in _VALID_RISK_LEVELS:
        return 400, {"error": {"message": f"Invalid risk_level: {risk_level!r}",
                               "type": "invalid_request_error", "code": 400}}
    if status is not None and status not in _VALID_COMMAND_STATUSES:
        return 400, {"error": {"message": f"Invalid status: {status!r}",
                               "type": "invalid_request_error", "code": 400}}
    cpath = _resolve_commands_path(commands_path)
    items = _load_published_commands(cpath)
    if component_id:
        items = [c for c in items if c.get("component_id") == component_id]
    if risk_level:
        items = [c for c in items if c.get("risk_level") == risk_level]
    if status:
        items = [c for c in items if c.get("status") == status]
    if q:
        ql = q.lower()
        items = [c for c in items if ql in c.get("name", "").lower()
                 or any(ql in a.lower() for a in c.get("aliases", []))]
    return 200, {"ok": True, "data": {"items": items, "total": len(items)}}


def process_robot_library_command(
    command_id: str,
    *,
    commands_path: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Core logic for ``GET /api/robot/library/commands/{id}`` (current record only)."""
    cpath = _resolve_commands_path(commands_path)
    cmd = _get_published_command(command_id, cpath)
    if cmd is None:
        return 404, {"error": {"message": f"Command '{command_id}' not found.",
                               "type": "invalid_request_error", "code": 404}}
    return 200, {"ok": True, "data": cmd}


def process_robot_library_components() -> tuple[int, dict[str, Any]]:
    """Core logic for ``GET /api/robot/library/components`` (read-only list)."""
    catalog = ComponentCatalog()
    items = catalog.list_all()
    return 200, {"ok": True, "data": {"items": [c.to_dict() for c in items], "total": len(items)}}


def process_robot_library_component(component_id: str) -> tuple[int, dict[str, Any]]:
    """Core logic for ``GET /api/robot/library/components/{id}`` (schema included)."""
    catalog = ComponentCatalog()
    comp = catalog.get(component_id)
    if comp is None:
        return 404, {"error": {"message": f"Component '{component_id}' not found.",
                               "type": "invalid_request_error", "code": 404}}
    return 200, {"ok": True, "data": comp.to_dict()}


def process_robot_library_flows(
    *,
    flow_registry_path: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Core logic for ``GET /api/robot/library/flows`` (read-only list).

    Reads the existing ``FlowRegistry`` without writing. Step shape stays as-is
    (``func_id``/``params``); the ``{command_id, version}`` upgrade is phase C.
    """
    from robot_ai.flow import FlowRegistry

    registry = FlowRegistry(_resolve_flow_registry_path(flow_registry_path))
    items = registry.list_all()
    return 200, {"ok": True, "data": {"items": [f.to_dict() for f in items], "total": len(items)}}


def process_robot_library_flow(
    flow_name: str,
    *,
    flow_registry_path: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Core logic for ``GET /api/robot/library/flows/{name}`` (read-only)."""
    from robot_ai.flow import FlowRegistry

    registry = FlowRegistry(_resolve_flow_registry_path(flow_registry_path))
    flow = registry.get(flow_name)
    if flow is None:
        return 404, {"error": {"message": f"Flow '{flow_name}' not found.",
                               "type": "invalid_request_error", "code": 404}}
    return 200, {"ok": True, "data": flow.to_dict()}


def _run_library_flow(entry, *, on_step=None, before_step=None) -> dict[str, Any]:
    """Preflight an entry, then execute it without a separate UI confirmation.

    The real pass is reached only when the runtime's per-step dry run succeeds;
    the existing controller safety gate still evaluates each real request.
    """
    from robot_ai.flow import run_flow

    dry_run = run_flow(entry, execute_real=False)
    if not dry_run.get("ok"):
        return dry_run
    return run_flow(
        entry,
        execute_real=True,
        confirm_work_area_clear=True,
        confirm_estop_ready=True,
        confirmation_code=REAL_EXECUTION_CONFIRMATION_CODE,
        on_step=on_step,
        before_step=before_step,
    )


def process_robot_library_command_run(
    command_id: str, *, commands_path: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Execute one published command through the same restricted flow runtime."""
    from robot_ai.flow.models import FlowEntry, FlowStep

    command = _get_published_command(command_id, _resolve_commands_path(commands_path))
    if command is None:
        return 404, {"error": {"code": "command_not_found", "message": "Published command not found."}}
    component = ComponentCatalog().get(str(command.get("component_id", "")))
    if component is None:
        return 400, {"error": {"code": "unknown_component", "message": "Command component is not executable."}}
    entry = FlowEntry(
        name=str(command.get("name", command_id)),
        steps=[FlowStep(
            step_id=1,
            action=component.id,
            func_id=component.func_num,
            params=dict(command.get("parameters", {})),
            description=str(command.get("description", "")),
        )],
    )
    return 200, _run_library_flow(entry)


def process_robot_library_flow_run(
    flow_name: str, *, flow_registry_path: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Execute a registered published flow after its runtime dry run succeeds."""
    from robot_ai.flow import FlowRegistry

    entry = FlowRegistry(_resolve_flow_registry_path(flow_registry_path)).get(flow_name)
    if entry is None:
        return 404, {"error": {"code": "flow_not_found", "message": "Published flow not found."}}
    return 200, _run_library_flow(entry)


def _start_library_execution(entry, *, kind: str, source_id: str) -> tuple[int, dict[str, Any]]:
    """Start an execution and return immediately; status is read by execution id."""
    from robot_ai.flow.execution_registry import get_library_execution_registry

    registry = get_library_execution_registry()
    execution_id = registry.start(
        len(entry.steps),
        lambda on_step, wait_for_step: _run_library_flow(
            entry, on_step=on_step, before_step=wait_for_step,
        ),
        kind=kind,
        source_id=source_id,
    )
    return 202, {"ok": True, "data": {"execution_id": execution_id, "state": "queued"}}


def process_robot_library_command_execution(
    command_id: str, *, commands_path: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Start one published command and expose its real controller progress."""
    from robot_ai.flow.models import FlowEntry, FlowStep

    command = _get_published_command(command_id, _resolve_commands_path(commands_path))
    if command is None:
        return 404, {"error": {"code": "command_not_found", "message": "Published command not found."}}
    component = ComponentCatalog().get(str(command.get("component_id", "")))
    if component is None:
        return 400, {"error": {"code": "unknown_component", "message": "Command component is not executable."}}
    return _start_library_execution(FlowEntry(name=str(command.get("name", command_id)), steps=[FlowStep(
        step_id=1, action=component.id, func_id=component.func_num,
        params=dict(command.get("parameters", {})), description=str(command.get("description", "")),
    )]), kind="command", source_id=command_id)


def process_robot_library_flow_execution(
    flow_name: str, *, flow_registry_path: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Start a published flow and expose real per-step controller progress."""
    from robot_ai.flow import FlowRegistry

    entry = FlowRegistry(_resolve_flow_registry_path(flow_registry_path)).get(flow_name)
    if entry is None:
        return 404, {"error": {"code": "flow_not_found", "message": "Published flow not found."}}
    return _start_library_execution(entry, kind="flow", source_id=flow_name)


def process_robot_library_execution_status(execution_id: str) -> tuple[int, dict[str, Any]]:
    from robot_ai.flow.execution_registry import get_library_execution_registry

    data = get_library_execution_registry().get(execution_id)
    if data is None:
        return 404, {"error": {"code": "execution_not_found", "message": "Execution not found."}}
    return 200, {"ok": True, "data": data}


# ---------------------------------------------------------------------------
# Flow process functions (multi-step named-flow dry-run -> confirm -> execute).
#
# These mirror the single-command ``process_robot_*`` functions but operate on
# a registered named flow (``FlowRegistry``). The flow-level confirm (RC- code
# + pending plan) gates ``flow-execute``; each step then runs through the CLI
# path inside ``run_flow`` (``confirmation_code=EXECUTE_ZMOTION_REAL``) so
# ``_is_confirmed`` returns True per step. The LLM never touches
# EXECUTE_ZMOTION_REAL (``RobotFlowTool`` is dry-run only).
# ---------------------------------------------------------------------------


def _resolve_flow_registry_path(path: str | None) -> str:
    import os

    resolved = path or DEFAULT_FLOW_REGISTRY_PATH
    return os.path.expanduser(resolved)


def process_robot_flow_pending_plan(
    body: Any,
    *,
    pending: PendingPlanStore,
    session: SessionGateStore,
    flow_registry_path: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Core logic for ``flow-pending-plan``: dry-run a named flow.

    Looks the flow up in :class:`FlowRegistry`, runs it with
    ``execute_real=False`` (dry-run), and stages a flow-level pending plan
    keyed by ``flow_name``. Returns ``(status_code, result_dict)``.
    """
    from robot_ai.flow import FlowRegistry, run_flow

    if not isinstance(body, dict):
        return 400, {"error": {"message": "Request body must be a JSON object",
                               "type": "invalid_request_error", "code": 400}}

    session_key = body.get("session_key")
    flow_name = body.get("flow_name")
    if not isinstance(flow_name, str) or not flow_name.strip():
        return 400, {"error": {"message": "'flow_name' is required",
                               "type": "invalid_request_error", "code": 400}}

    registry = FlowRegistry(_resolve_flow_registry_path(flow_registry_path))
    entry = registry.get(flow_name)
    if entry is None:
        return 200, {
            "ok": False,
            "state": "flow_not_found",
            "message": f"Flow '{flow_name}' is not registered.",
            "data": {"flow_name": flow_name},
            "errors": [{"code": "flow_not_found"}],
        }

    dry_run_result = run_flow(entry, execute_real=False)
    if not dry_run_result.get("ok"):
        # Dry-run failed (safety blocked, empty flow, failed step, ...).
        return 200, dry_run_result

    plan = pending.create(
        command="flow_run",
        parameters={"flow_name": entry.name},
        dry_run_result=dry_run_result,
    )
    session.set_pending_plan(session_key, plan.plan_id)
    return 200, {
        "plan_id": plan.plan_id,
        "flow_name": entry.name,
        "dry_run_result": dry_run_result,
        "param_hash": plan.param_hash,
        "expires_at": plan.expires_at,
    }


def process_robot_flow_confirm(
    body: Any,
    *,
    pending: PendingPlanStore,
    session: SessionGateStore,
) -> tuple[int, dict[str, Any]]:
    """Core logic for ``flow-confirm``: confirm a staged flow pending plan.

    Identical to :func:`process_robot_confirm` — the flow-level pending plan is
    stored with ``command="flow_run"`` + ``parameters={"flow_name": ...}``, and
    the same RC- code path applies.
    """
    return process_robot_confirm(body, pending=pending, session=session)


def process_robot_flow_execute(
    body: Any,
    *,
    pending: PendingPlanStore,
    session: SessionGateStore,
    flow_registry_path: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Core logic for ``flow-execute``: run a confirmed flow for real.

    Verifies the flow-level pending plan + RC- confirm code, then runs the flow
    with ``execute_real=True`` and ``confirmation_code=EXECUTE_ZMOTION_REAL``
    so each step passes the per-step ``_is_confirmed`` gate via the CLI path.
    """
    from robot_ai.execution import verify_confirm_code
    from robot_ai.flow import FlowRegistry, run_flow

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

    # Flow-level verification: RC- code + session gate (the same checks
    # ``_is_confirmed`` would run per-step, but enforced once at the flow gate
    # before any real motion is issued).
    if not verify_confirm_code(plan_id, confirm_code):
        return 403, {"error": {"message": "Invalid or expired confirm code.",
                               "type": "invalid_request_error", "code": 403}}
    if not session.is_confirmed(session_key, plan_id):
        return 403, {"error": {"message": "Session has no matching confirmed plan.",
                               "type": "invalid_request_error", "code": 403}}

    flow_name = plan.parameters.get("flow_name") if isinstance(plan.parameters, dict) else None
    if not isinstance(flow_name, str) or not flow_name:
        return 400, {"error": {"message": "Pending plan is not a flow plan.",
                               "type": "invalid_request_error", "code": 400}}

    registry = FlowRegistry(_resolve_flow_registry_path(flow_registry_path))
    entry = registry.get(flow_name)
    if entry is None:
        return 200, {
            "ok": False,
            "state": "flow_not_found",
            "message": f"Flow '{flow_name}' is not registered.",
            "data": {"flow_name": flow_name},
            "errors": [{"code": "flow_not_found"}],
        }

    result = run_flow(
        entry,
        execute_real=True,
        confirm_work_area_clear=True,
        confirm_estop_ready=True,
        confirmation_code=REAL_EXECUTION_CONFIRMATION_CODE,
    )
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


async def handle_robot_flow_pending_plan(request: web.Request) -> web.Response:
    """POST /api/robot/flow-pending-plan — dry-run a named flow + stage a plan."""
    try:
        body = await request.json()
    except Exception:
        return _error_json(400, "Invalid JSON body")

    pending, session = _get_stores(request)
    flow_registry_path = request.app.get("robot_flow_registry_path")
    status, result = process_robot_flow_pending_plan(
        body,
        pending=pending,
        session=session,
        flow_registry_path=flow_registry_path,
    )
    return web.json_response(result, status=status)


async def handle_robot_flow_confirm(request: web.Request) -> web.Response:
    """POST /api/robot/flow-confirm — confirm a staged flow plan + issue RC- code."""
    try:
        body = await request.json()
    except Exception:
        return _error_json(400, "Invalid JSON body")

    pending, session = _get_stores(request)
    status, result = process_robot_flow_confirm(body, pending=pending, session=session)
    return web.json_response(result, status=status)


async def handle_robot_flow_execute(request: web.Request) -> web.Response:
    """POST /api/robot/flow-execute — run a confirmed flow for real."""
    try:
        body = await request.json()
    except Exception:
        return _error_json(400, "Invalid JSON body")

    pending, session = _get_stores(request)
    flow_registry_path = request.app.get("robot_flow_registry_path")
    status, result = process_robot_flow_execute(
        body,
        pending=pending,
        session=session,
        flow_registry_path=flow_registry_path,
    )
    return web.json_response(result, status=status)


async def handle_robot_status(request: web.Request) -> web.Response:
    """GET /api/robot/status — read-only snapshot of the current robot state.

    No body required. Same ``check_api_token`` gate as the other robot routes
    (the gateway dispatcher enforces it); served directly as JSON by aiohttp.
    """
    status, result = process_robot_status()
    return web.json_response(result, status=status)


async def handle_robot_system_action(request: web.Request) -> web.Response:
    """POST /api/robot/system-action — direct operator system action."""
    try:
        body = await request.json()
    except Exception:
        return _error_json(400, "Invalid JSON body")
    runner = _get_runner(request)
    status, result = process_robot_system_action(body, runner=runner)
    return web.json_response(result, status=status)


async def handle_robot_library_commands(request: web.Request) -> web.Response:
    """GET /api/robot/library/commands — read-only command list."""
    if request.query.get("version") is not None:
        return _error_json(400, "unsupported parameter: version")
    status, result = process_robot_library_commands(
        commands_path=request.app.get("robot_commands_path"),
        component_id=request.query.get("component_id") or None,
        risk_level=request.query.get("risk_level") or None,
        status=request.query.get("status") or None,
        q=request.query.get("q") or None,
    )
    return web.json_response(result, status=status)


async def handle_robot_library_command(request: web.Request) -> web.Response:
    """GET /api/robot/library/commands/{command_id} — single command."""
    if request.query.get("version") is not None:
        return _error_json(400, "unsupported parameter: version")
    command_id = request.match_info["command_id"]
    status, result = process_robot_library_command(
        command_id, commands_path=request.app.get("robot_commands_path")
    )
    return web.json_response(result, status=status)


async def handle_robot_library_components(request: web.Request) -> web.Response:
    """GET /api/robot/library/components — read-only component list."""
    status, result = process_robot_library_components()
    return web.json_response(result, status=status)


async def handle_robot_library_component(request: web.Request) -> web.Response:
    """GET /api/robot/library/components/{component_id} — component schema."""
    status, result = process_robot_library_component(request.match_info["component_id"])
    return web.json_response(result, status=status)


async def handle_robot_library_flows(request: web.Request) -> web.Response:
    """GET /api/robot/library/flows — read-only flow list."""
    status, result = process_robot_library_flows(
        flow_registry_path=request.app.get("robot_flow_registry_path"),
    )
    return web.json_response(result, status=status)


async def handle_robot_library_flow(request: web.Request) -> web.Response:
    """GET /api/robot/library/flows/{flow_name} — single flow (read-only)."""
    flow_name = request.match_info["flow_name"]
    status, result = process_robot_library_flow(
        flow_name, flow_registry_path=request.app.get("robot_flow_registry_path")
    )
    return web.json_response(result, status=status)


async def handle_robot_library_command_execution(request: web.Request) -> web.Response:
    status, result = process_robot_library_command_execution(
        request.match_info["command_id"], commands_path=request.app.get("robot_commands_path"),
    )
    return web.json_response(result, status=status)


async def handle_robot_library_flow_execution(request: web.Request) -> web.Response:
    status, result = process_robot_library_flow_execution(
        request.match_info["flow_name"], flow_registry_path=request.app.get("robot_flow_registry_path"),
    )
    return web.json_response(result, status=status)


async def handle_robot_library_execution_status(request: web.Request) -> web.Response:
    status, result = process_robot_library_execution_status(request.match_info["execution_id"])
    return web.json_response(result, status=status)


def register_robot_routes(app: web.Application) -> None:
    """Register the /api/robot/* routes on an existing aiohttp app."""
    app.router.add_post("/api/robot/pending-plan", handle_robot_pending_plan)
    app.router.add_post("/api/robot/confirm", handle_robot_confirm)
    app.router.add_post("/api/robot/execute", handle_robot_execute)
    app.router.add_post("/api/robot/flow-pending-plan", handle_robot_flow_pending_plan)
    app.router.add_post("/api/robot/flow-confirm", handle_robot_flow_confirm)
    app.router.add_post("/api/robot/flow-execute", handle_robot_flow_execute)
    app.router.add_get("/api/robot/status", handle_robot_status)
    app.router.add_post("/api/robot/system-action", handle_robot_system_action)
    app.router.add_get("/api/robot/library/commands", handle_robot_library_commands)
    app.router.add_get("/api/robot/library/commands/{command_id}", handle_robot_library_command)
    app.router.add_get("/api/robot/library/components", handle_robot_library_components)
    app.router.add_get("/api/robot/library/components/{component_id}", handle_robot_library_component)
    app.router.add_get("/api/robot/library/flows", handle_robot_library_flows)
    app.router.add_get("/api/robot/library/commands/{command_id}/run", handle_robot_library_command_execution)
    app.router.add_get("/api/robot/library/flows/{flow_name}/run", handle_robot_library_flow_execution)
    app.router.add_get("/api/robot/library/executions/{execution_id}", handle_robot_library_execution_status)
    app.router.add_get("/api/robot/library/flows/{flow_name}", handle_robot_library_flow)


def create_robot_app() -> web.Application:
    """Build a standalone aiohttp app exposing only the /api/robot/* routes.

    Use this when the host process does not already run the nanobot gateway;
    otherwise prefer :func:`register_robot_routes` on the shared app.
    """
    app = web.Application()
    register_robot_routes(app)
    return app


def process_engineer_login(body: Any, *, token_store=None, throttle=None,
                            users_path: str | None = None, audit_path: str | None = None,
                            config_path=None, client_key: str | None = None) -> tuple[int, dict[str, Any]]:
    """DEPRECATED alias: B1a engineer login -> unified login as admin/engineer.

    Returns a user_token (keyed `user_token`; also mirrored as `engineer_token` for old clients)."""
    status, result = process_auth_login(
        {"username": "admin", "password": str((body or {}).get("password", "")), "role": "engineer"},
        users_path=users_path, audit_path=audit_path, token_store=token_store, throttle=throttle,
        client_key=client_key)
    if status == 200:
        result["data"]["engineer_token"] = result["data"]["user_token"]  # compat mirror
    return status, result


def process_engineer_logout(engineer_token, *, token_store, audit_path=None, **_kw) -> tuple[int, dict[str, Any]]:
    """DEPRECATED alias -> unified logout."""
    return process_auth_logout(engineer_token, token_store=token_store, audit_path=audit_path)


def _engineer_registry(commands_path, audit_path=None):
    from robot_ai.library.versioned_registry import VersionedCommandRegistry
    return VersionedCommandRegistry(_resolve_commands_path(commands_path),
                                     audit_path=_resolve_audit_path(audit_path))


def _engineer_flow_registry(flows_path, audit_path=None):
    from robot_ai.flow.versioned_registry import VersionedFlowRegistry

    return VersionedFlowRegistry(
        _resolve_flow_registry_path(flows_path), audit_path=_resolve_audit_path(audit_path)
    )


def process_engineer_commands(*, commands_path=None, audit_path=None,
                               token_store=None, engineer_token=None):
    ok, err, _session = _require_user_role(token_store, engineer_token, "engineer")
    if not ok:
        return (403 if err["error"]["code"] == "forbidden" else 401), err
    return 200, {"ok": True, "data": {"entities": _engineer_registry(commands_path).list_summaries()}}


def process_engineer_command(command_id, *, commands_path=None, audit_path=None,
                              token_store=None, engineer_token=None):
    ok, err, _session = _require_user_role(token_store, engineer_token, "engineer")
    if not ok:
        return (403 if err["error"]["code"] == "forbidden" else 401), err
    entity = _engineer_registry(commands_path).get_entity(command_id)
    if entity is None:
        return 404, {"error": {"code": "command_not_found",
                                "message": f"Command {command_id!r} not found."}}
    return 200, {"ok": True, "data": entity}


def process_engineer_create_command(body, *, commands_path=None, audit_path=None,
                                     token_store=None, engineer_token=None):
    from robot_ai.library.models import normalize_id
    ok, err, _session = _require_user_role(token_store, engineer_token, "engineer")
    if not ok:
        return (403 if err["error"]["code"] == "forbidden" else 401), err
    body = body or {}
    name = str(body.get("name", "")).strip()
    component_id = str(body.get("component_id", "")).strip()
    if not name or not component_id:
        return 400, {"error": {"code": "invalid_request",
                                "message": "name and component_id are required."}}
    command_id = normalize_id(name)
    reg = _engineer_registry(commands_path, audit_path)
    if reg.get_entity(command_id) is not None:
        return 409, {"error": {"code": "command_exists",
                                "message": f"Command {command_id!r} already exists."}}
    try:
        entity = reg.create_entity(command_id, component_id, name, dict(body.get("parameters", {})),
                                    aliases=list(body.get("aliases", [])),
                                    description=str(body.get("description", "")))
    except ValueError as e:
        return 409, {"error": {"code": "command_exists", "message": str(e)}}
    return 201, {"ok": True, "data": entity}


def process_engineer_update_draft(command_id, body, *, commands_path=None, audit_path=None,
                                   token_store=None, engineer_token=None):
    from robot_ai.library.versioned_registry import ConflictError
    ok, err, _session = _require_user_role(token_store, engineer_token, "engineer")
    if not ok:
        return (403 if err["error"]["code"] == "forbidden" else 401), err
    body = body or {}
    reg = _engineer_registry(commands_path, audit_path)
    try:
        entity = reg.update_draft(
            command_id, expected_revision=int(body.get("expected_revision")),
            name=str(body.get("name", "")), aliases=list(body.get("aliases", [])),
            description=str(body.get("description", "")),
            component_id=str(body.get("component_id", "")),
            parameters=dict(body.get("parameters", {})))
    except ConflictError as e:
        return 409, {"ok": False, "data": {"current_revision": e.current_revision},
                     "error": {"code": "draft_conflict", "message": "Draft revision mismatch; reload."}}
    except ValueError as e:
        return 400, {"error": {"code": "invalid_draft", "message": str(e)}}
    return 200, {"ok": True, "data": entity}


_PUBLISH_PY_TYPES = {"int": int, "float": (int, float), "str": str, "bool": bool}


def _validate_publish_params(component, params) -> tuple[bool, str]:
    """Full component-schema validation for publish (R1).
    Order: unknown -> required -> type -> bool-as-number -> range."""
    schema = {pf.name: pf for pf in component.parameters}
    for key in params:
        if key not in schema:
            return False, f"Unknown parameter {key!r} for component {component.id!r}."
    for pf in component.parameters:
        if pf.name not in params:
            if pf.required:
                return False, f"Missing required parameter {pf.name!r}."
            continue
        val = params[pf.name]
        expected = _PUBLISH_PY_TYPES.get(pf.type)
        if expected is None:
            continue
        if pf.type in ("int", "float") and isinstance(val, bool):
            return False, f"Parameter {pf.name!r} must be {pf.type}, not bool."
        if not isinstance(val, expected):
            return False, f"Parameter {pf.name!r} must be {pf.type}."
        if pf.type in ("int", "float"):
            if pf.minimum is not None and val < pf.minimum:
                return False, f"Parameter {pf.name!r} must be >= {pf.minimum}."
            if pf.maximum is not None and val > pf.maximum:
                return False, f"Parameter {pf.name!r} must be <= {pf.maximum}."
    return True, ""


def _get_component(component_id):
    from robot_ai.library.catalog import ComponentCatalog
    comp = ComponentCatalog().get(component_id)
    return comp


def process_engineer_start_draft(command_id, *, commands_path=None, audit_path=None,
                                  token_store=None, engineer_token=None):
    """R6: 404 if missing; 409 if no published version OR draft already exists."""
    ok, err, _session = _require_user_role(token_store, engineer_token, "engineer")
    if not ok:
        return (403 if err["error"]["code"] == "forbidden" else 401), err
    reg = _engineer_registry(commands_path, audit_path)
    if reg.get_entity(command_id) is None:
        return 404, {"error": {"code": "command_not_found",
                                "message": f"Command {command_id!r} not found."}}
    try:
        entity = reg.start_draft(command_id)
    except ValueError as e:
        return 409, {"error": {"code": "draft_conflict", "message": str(e)}}
    return 201, {"ok": True, "data": entity}


def process_engineer_publish(command_id, *, commands_path=None, audit_path=None,
                              token_store=None, engineer_token=None):
    ok, err, _session = _require_user_role(token_store, engineer_token, "engineer")
    if not ok:
        return (403 if err["error"]["code"] == "forbidden" else 401), err
    reg = _engineer_registry(commands_path, audit_path)
    entity = reg.get_entity(command_id)
    if entity is None or entity.get("draft") is None:
        return 404, {"error": {"code": "no_draft",
                                "message": f"No active draft for {command_id!r}."}}
    component_id = entity["draft"].get("component_id", "")
    comp = _get_component(component_id)
    if comp is None:
        return 400, {"error": {"code": "invalid_component",
                                "message": f"Unknown component {component_id!r}."}}
    params = dict(entity["draft"].get("parameters", {}))
    ok_params, reason = _validate_publish_params(comp, params)  # R1
    if not ok_params:
        return 400, {"error": {"code": "invalid_parameters", "message": reason}}
    try:
        entity = reg.publish(command_id, component_risk_level=comp.risk_level)
    except ValueError as e:
        return 409, {"error": {"code": "namespace_conflict", "message": str(e)}}
    return 200, {"ok": True, "data": entity}


def process_engineer_archive(command_id, *, commands_path=None, audit_path=None,
                              token_store=None, engineer_token=None):
    from robot_ai.library.versioned_registry import ConflictError
    ok, err, _session = _require_user_role(token_store, engineer_token, "engineer")
    if not ok:
        return (403 if err["error"]["code"] == "forbidden" else 401), err
    reg = _engineer_registry(commands_path, audit_path)
    try:
        reg.archive(command_id)
    except ConflictError as e:
        return 409, {"error": {"code": "archive_blocked", "message": str(e)}}
    except ValueError as e:
        return 404, {"error": {"code": "command_not_found", "message": str(e)}}
    return 200, {"ok": True, "data": {"archived": command_id}}


def process_engineer_flows(*, flows_path=None, audit_path=None,
                           token_store=None, engineer_token=None):
    ok, err, _session = _require_user_role(token_store, engineer_token, "engineer")
    if not ok:
        return (403 if err["error"]["code"] == "forbidden" else 401), err
    registry = _engineer_flow_registry(flows_path, audit_path)
    return 200, {"ok": True, "data": {"entities": list(registry._data["flows"].values())}}


def process_engineer_flow(flow_id, *, flows_path=None, audit_path=None,
                          token_store=None, engineer_token=None):
    ok, err, _session = _require_user_role(token_store, engineer_token, "engineer")
    if not ok:
        return (403 if err["error"]["code"] == "forbidden" else 401), err
    entity = _engineer_flow_registry(flows_path, audit_path).get_entity(flow_id)
    if entity is None:
        return 404, {"error": {"code": "flow_not_found", "message": f"Flow {flow_id!r} not found."}}
    return 200, {"ok": True, "data": entity}


def process_engineer_create_flow(body, *, flows_path=None, audit_path=None,
                                 token_store=None, engineer_token=None):
    ok, err, _session = _require_user_role(token_store, engineer_token, "engineer")
    if not ok:
        return (403 if err["error"]["code"] == "forbidden" else 401), err
    body = body or {}
    if not isinstance(body, dict):
        return 400, {"error": {"code": "invalid_request", "message": "Flow body must be an object."}}
    name = str(body.get("name", "")).strip()
    steps = body.get("steps")
    if not name or not isinstance(steps, list):
        return 400, {"error": {"code": "invalid_request", "message": "name and steps are required."}}
    flow_id = "_".join(name.lower().split())
    registry = _engineer_flow_registry(flows_path, audit_path)
    if registry.get_entity(flow_id) is not None:
        return 409, {"error": {"code": "flow_exists", "message": f"Flow {flow_id!r} already exists."}}
    try:
        entity = registry.create_entity(
            flow_id, name, steps,
            step_delay_ms=body.get("step_delay_ms", 1000),
            rehearsal_spd=body.get("rehearsal_spd", 20),
            description=str(body.get("description", "")),
        )
    except ValueError as exc:
        return 400, {"error": {"code": "invalid_flow", "message": str(exc)}}
    return 201, {"ok": True, "data": entity}


def process_engineer_start_flow_draft(flow_id, *, flows_path=None, audit_path=None,
                                      token_store=None, engineer_token=None):
    ok, err, _session = _require_user_role(token_store, engineer_token, "engineer")
    if not ok:
        return (403 if err["error"]["code"] == "forbidden" else 401), err
    registry = _engineer_flow_registry(flows_path, audit_path)
    if registry.get_entity(flow_id) is None:
        return 404, {"error": {"code": "flow_not_found", "message": f"Flow {flow_id!r} not found."}}
    try:
        entity = registry.start_draft(flow_id)
    except ValueError as exc:
        return 409, {"error": {"code": "draft_conflict", "message": str(exc)}}
    return 201, {"ok": True, "data": entity}


def process_engineer_update_flow_draft(flow_id, body, *, flows_path=None, audit_path=None,
                                       token_store=None, engineer_token=None):
    from robot_ai.library.versioned_registry import ConflictError

    ok, err, _session = _require_user_role(token_store, engineer_token, "engineer")
    if not ok:
        return (403 if err["error"]["code"] == "forbidden" else 401), err
    body = body or {}
    if not isinstance(body, dict):
        return 400, {"error": {"code": "invalid_draft", "message": "Flow body must be an object."}}
    try:
        entity = _engineer_flow_registry(flows_path, audit_path).update_draft(
            flow_id,
            expected_revision=int(body.get("expected_revision")),
            name=str(body.get("name", "")),
            steps=list(body.get("steps", [])),
            step_delay_ms=body.get("step_delay_ms", 1000),
            rehearsal_spd=body.get("rehearsal_spd", 20),
            description=str(body.get("description", "")),
        )
    except ConflictError as exc:
        return 409, {"ok": False, "data": {"current_revision": exc.current_revision},
                     "error": {"code": "draft_conflict", "message": "Draft revision mismatch; reload."}}
    except (TypeError, ValueError) as exc:
        return 400, {"error": {"code": "invalid_draft", "message": str(exc)}}
    return 200, {"ok": True, "data": entity}


def process_engineer_validate_flow_draft(flow_id, *, flows_path=None, audit_path=None,
                                         token_store=None, engineer_token=None):
    ok, err, _session = _require_user_role(token_store, engineer_token, "engineer")
    if not ok:
        return (403 if err["error"]["code"] == "forbidden" else 401), err
    try:
        errors = _engineer_flow_registry(flows_path, audit_path).validate_draft(flow_id)
    except ValueError as exc:
        return 404, {"error": {"code": "no_draft", "message": str(exc)}}
    return 200, {"ok": not errors, "data": {"errors": errors}}


def process_engineer_publish_flow(flow_id, *, flows_path=None, audit_path=None,
                                  token_store=None, engineer_token=None):
    ok, err, _session = _require_user_role(token_store, engineer_token, "engineer")
    if not ok:
        return (403 if err["error"]["code"] == "forbidden" else 401), err
    registry = _engineer_flow_registry(flows_path, audit_path)
    entity = registry.get_entity(flow_id)
    if entity is None or entity.get("draft") is None:
        return 404, {"error": {"code": "no_draft", "message": f"No active draft for {flow_id!r}."}}
    try:
        entity = registry.publish(flow_id)
    except ValueError as exc:
        return 400, {"error": {"code": "invalid_flow", "message": str(exc)}}
    return 200, {"ok": True, "data": entity}


def process_engineer_archive_flow(flow_id, *, flows_path=None, audit_path=None,
                                  token_store=None, engineer_token=None):
    from robot_ai.library.versioned_registry import ConflictError

    ok, err, _session = _require_user_role(token_store, engineer_token, "engineer")
    if not ok:
        return (403 if err["error"]["code"] == "forbidden" else 401), err
    try:
        _engineer_flow_registry(flows_path, audit_path).archive(flow_id)
    except ConflictError as exc:
        return 409, {"error": {"code": "archive_blocked", "message": str(exc)}}
    except ValueError as exc:
        return 404, {"error": {"code": "flow_not_found", "message": str(exc)}}
    return 200, {"ok": True, "data": {"archived": flow_id}}


def _audit_key(entry):
    return entry.get("audit_id") or entry.get("migration_id") or ""


def _encode_cursor(timestamp, key):
    import base64
    import json as _json
    return base64.urlsafe_b64encode(
        _json.dumps({"ts": timestamp, "key": key}).encode("utf-8")).decode("ascii")


def _decode_cursor(cursor):
    import base64
    import json as _json
    if not cursor:
        return None
    try:
        obj = _json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
        return str(obj.get("ts", "")), str(obj.get("key", ""))
    except Exception:
        return None


def process_engineer_audit(*, audit_path=None, limit=50, before=None,
                            token_store=None, engineer_token=None):
    import json as _json
    from pathlib import Path

    ok, err, _session = _require_user_role(token_store, engineer_token, "engineer")
    if not ok:
        return (403 if err["error"]["code"] == "forbidden" else 401), err
    limit = max(1, min(int(limit or 50), 100))
    apath = _resolve_audit_path(audit_path)
    entries = []
    if Path(apath).exists():
        for line in Path(apath).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(_json.loads(line))
            except _json.JSONDecodeError:
                continue
    entries.sort(key=lambda e: (e.get("timestamp", ""), _audit_key(e)), reverse=True)
    cursor = _decode_cursor(before)
    if before and cursor is None:
        return 400, {"error": {"code": "invalid_cursor",
                                "message": "Malformed audit cursor."}}
    if cursor is not None:
        cts, ckey = cursor
        entries = [e for e in entries
                   if (e.get("timestamp", ""), _audit_key(e)) < (cts, ckey)]
    page = entries[:limit]
    next_cursor = _encode_cursor(page[-1].get("timestamp", ""), _audit_key(page[-1])) \
        if len(entries) > limit else None
    return 200, {"ok": True, "data": {"items": page, "next_cursor": next_cursor}}


# ---------------------------------------------------------------------------
# Task 8: aiohttp transport — handle_engineer_* + register_engineer_routes.
# D9: aiohttp uses real POST/PUT and IGNORES X-Nanobot-Engineer-Action.
# R5: 429 carries the HTTP Retry-After header (value from body["data"]["retry_after"]).
# Every engineer response carries Cache-Control: no-store + Pragma: no-cache.
# ---------------------------------------------------------------------------

_NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}
_ENGINEER_TOKEN_HEADER = "X-Nanobot-Engineer-Token"
_USER_TOKEN_HEADER = "X-Nanobot-User-Token"
_ENGINEER_ACTION_HEADER = "X-Nanobot-Engineer-Action"


def _eng_deps(request):
    """Resolve (token_store, throttle, commands_path, audit_path, config_path).

    App-provided overrides win (request.app[...]); otherwise fall back to the
    module singletons in robot_ai.library.auth. Read-only — does not mutate the
    app (the app may already be started).

    Task 7: the session store is now the unified ``UserSessionStore`` (resolved
    via the ``user_session_store`` app key or ``get_user_session_store``); the
    B1a ``EngineerTokenStore`` + its app key were removed.
    """
    from robot_ai.library.auth import get_login_throttle, get_user_session_store

    store = request.app.get("user_session_store") or get_user_session_store()
    throttle = request.app.get("user_login_throttle") or get_login_throttle()
    return (
        store,
        throttle,
        request.app.get("robot_commands_path"),
        request.app.get("robot_audit_path"),
        request.app.get("engineer_config_path"),
    )


def _eng_token(request):
    return request.headers.get(_USER_TOKEN_HEADER) or request.headers.get(_ENGINEER_TOKEN_HEADER)


async def _eng_body(request):
    """Read the request body. POST/PUT use the real body; GET (and any method
    without a body) falls back to the X-Nanobot-Robot-Body header so the same
    handler serves the ws_http GET transport."""
    if request.method in ("POST", "PUT"):
        try:
            return await request.json()
        except Exception:
            return {}
    raw = request.headers.get("X-Nanobot-Robot-Body")
    try:
        import json as _json

        return _json.loads(raw) if raw else {}
    except Exception:
        return {}


def _eng_response(body, status):
    headers = dict(_NO_STORE_HEADERS)
    if status == 429:
        ra = (body or {}).get("data", {}).get("retry_after")
        if ra is not None:
            headers["Retry-After"] = str(ra)  # R5
    return web.json_response(body, status=status, headers=headers)


async def handle_engineer_login(request):
    store, throttle, _cpath, audit_path, config_path = _eng_deps(request)
    client_key = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not client_key:
        client_key = request.query.get("token") or request.remote  # D2: aiohttp fallback to IP
    status, body = process_engineer_login(
        await _eng_body(request),
        token_store=store,
        throttle=throttle,
        users_path=request.app.get("robot_users_path"),
        config_path=config_path,
        audit_path=audit_path,
        client_key=client_key,
    )
    return _eng_response(body, status)


async def handle_engineer_logout(request):
    store, _th, _cpath, audit_path, _cfg = _eng_deps(request)
    status, body = process_engineer_logout(
        _eng_token(request), token_store=store, audit_path=audit_path
    )
    return _eng_response(body, status)


async def handle_engineer_commands(request):
    store, _th, cpath, audit_path, _cfg = _eng_deps(request)
    etok = _eng_token(request)
    if request.method == "POST":
        status, body = process_engineer_create_command(
            await _eng_body(request),
            commands_path=cpath,
            audit_path=audit_path,
            token_store=store,
            engineer_token=etok,
        )
    else:
        status, body = process_engineer_commands(
            commands_path=cpath,
            audit_path=audit_path,
            token_store=store,
            engineer_token=etok,
        )
    return _eng_response(body, status)


async def handle_engineer_command(request):
    store, _th, cpath, audit_path, _cfg = _eng_deps(request)
    status, body = process_engineer_command(
        request.match_info["command_id"],
        commands_path=cpath,
        audit_path=audit_path,
        token_store=store,
        engineer_token=_eng_token(request),
    )
    return _eng_response(body, status)


async def handle_engineer_draft(request):
    store, _th, cpath, audit_path, _cfg = _eng_deps(request)
    cid = request.match_info["command_id"]
    if request.method == "POST":
        status, body = process_engineer_start_draft(
            cid,
            commands_path=cpath,
            audit_path=audit_path,
            token_store=store,
            engineer_token=_eng_token(request),
        )
    else:  # PUT — full draft replacement
        status, body = process_engineer_update_draft(
            cid,
            await _eng_body(request),
            commands_path=cpath,
            audit_path=audit_path,
            token_store=store,
            engineer_token=_eng_token(request),
        )
    return _eng_response(body, status)


async def handle_engineer_publish(request):
    store, _th, cpath, audit_path, _cfg = _eng_deps(request)
    status, body = process_engineer_publish(
        request.match_info["command_id"],
        commands_path=cpath,
        audit_path=audit_path,
        token_store=store,
        engineer_token=_eng_token(request),
    )
    return _eng_response(body, status)


async def handle_engineer_archive(request):
    store, _th, cpath, audit_path, _cfg = _eng_deps(request)
    status, body = process_engineer_archive(
        request.match_info["command_id"],
        commands_path=cpath,
        audit_path=audit_path,
        token_store=store,
        engineer_token=_eng_token(request),
    )
    return _eng_response(body, status)


def _has_gateway_token(request) -> bool:
    """Check the app's gateway token for direct aiohttp flow authoring routes.

    The WebSocket gateway already performs this check before dispatching. Direct
    aiohttp registration must fail closed instead of allowing an engineer user
    token to bypass the gateway-token boundary.
    """
    checker = request.app.get("check_api_token")
    if callable(checker):
        return bool(checker(request))
    token_store = request.app.get("gateway_token_store")
    gateway_request = SimpleNamespace(headers=request.headers, path=request.path_qs)
    return bool(token_store and token_store.check_api_token(gateway_request))


async def handle_engineer_flows(request):
    if not _has_gateway_token(request):
        return _eng_response({"error": {"code": "unauthorized", "message": "Unauthorized"}}, 401)
    store, _th, _cpath, audit_path, _cfg = _eng_deps(request)
    flows_path = request.app.get("robot_flow_registry_path")
    etok = _eng_token(request)
    if request.method == "POST":
        status, body = process_engineer_create_flow(
            await _eng_body(request), flows_path=flows_path, audit_path=audit_path,
            token_store=store, engineer_token=etok,
        )
    else:
        status, body = process_engineer_flows(
            flows_path=flows_path, audit_path=audit_path, token_store=store, engineer_token=etok,
        )
    return _eng_response(body, status)


async def handle_engineer_flow(request):
    if not _has_gateway_token(request):
        return _eng_response({"error": {"code": "unauthorized", "message": "Unauthorized"}}, 401)
    store, _th, _cpath, audit_path, _cfg = _eng_deps(request)
    status, body = process_engineer_flow(
        request.match_info["flow_id"], flows_path=request.app.get("robot_flow_registry_path"),
        audit_path=audit_path, token_store=store, engineer_token=_eng_token(request),
    )
    return _eng_response(body, status)


async def handle_engineer_flow_draft(request):
    if not _has_gateway_token(request):
        return _eng_response({"error": {"code": "unauthorized", "message": "Unauthorized"}}, 401)
    store, _th, _cpath, audit_path, _cfg = _eng_deps(request)
    flow_id = request.match_info["flow_id"]
    kwargs = {"flows_path": request.app.get("robot_flow_registry_path"), "audit_path": audit_path,
              "token_store": store, "engineer_token": _eng_token(request)}
    if request.method == "POST":
        status, body = process_engineer_start_flow_draft(flow_id, **kwargs)
    else:
        status, body = process_engineer_update_flow_draft(flow_id, await _eng_body(request), **kwargs)
    return _eng_response(body, status)


async def handle_engineer_flow_validate(request):
    if not _has_gateway_token(request):
        return _eng_response({"error": {"code": "unauthorized", "message": "Unauthorized"}}, 401)
    store, _th, _cpath, audit_path, _cfg = _eng_deps(request)
    status, body = process_engineer_validate_flow_draft(
        request.match_info["flow_id"], flows_path=request.app.get("robot_flow_registry_path"),
        audit_path=audit_path, token_store=store, engineer_token=_eng_token(request),
    )
    return _eng_response(body, status)


async def handle_engineer_flow_publish(request):
    if not _has_gateway_token(request):
        return _eng_response({"error": {"code": "unauthorized", "message": "Unauthorized"}}, 401)
    store, _th, _cpath, audit_path, _cfg = _eng_deps(request)
    status, body = process_engineer_publish_flow(
        request.match_info["flow_id"], flows_path=request.app.get("robot_flow_registry_path"),
        audit_path=audit_path, token_store=store, engineer_token=_eng_token(request),
    )
    return _eng_response(body, status)


async def handle_engineer_flow_archive(request):
    if not _has_gateway_token(request):
        return _eng_response({"error": {"code": "unauthorized", "message": "Unauthorized"}}, 401)
    store, _th, _cpath, audit_path, _cfg = _eng_deps(request)
    status, body = process_engineer_archive_flow(
        request.match_info["flow_id"], flows_path=request.app.get("robot_flow_registry_path"),
        audit_path=audit_path, token_store=store, engineer_token=_eng_token(request),
    )
    return _eng_response(body, status)


async def handle_engineer_audit(request):
    store, _th, _cpath, audit_path, _cfg = _eng_deps(request)
    status, body = process_engineer_audit(
        audit_path=audit_path,
        limit=int(request.query.get("limit") or 50),
        before=request.query.get("before"),
        token_store=store,
        engineer_token=_eng_token(request),
    )
    return _eng_response(body, status)


def register_engineer_routes(app):
    """Register the engineer API on an aiohttp app (spec §6).

    D9: aiohttp uses real HTTP methods and IGNORES X-Nanobot-Engineer-Action
    entirely — the ws_http GET transport is the only place that header matters.
    The GET registrations exist so the same handlers serve the body-header
    transport when aiohttp is used standalone.
    """
    app.router.add_get("/api/robot/engineer/login", handle_engineer_login)
    app.router.add_get("/api/robot/engineer/logout", handle_engineer_logout)
    app.router.add_get("/api/robot/engineer/commands", handle_engineer_commands)
    app.router.add_post("/api/robot/engineer/commands", handle_engineer_commands)
    app.router.add_get(
        "/api/robot/engineer/commands/{command_id}", handle_engineer_command
    )
    app.router.add_put(
        "/api/robot/engineer/commands/{command_id}/draft", handle_engineer_draft
    )
    app.router.add_post(
        "/api/robot/engineer/commands/{command_id}/draft", handle_engineer_draft
    )
    app.router.add_post(
        "/api/robot/engineer/commands/{command_id}/publish", handle_engineer_publish
    )
    app.router.add_post(
        "/api/robot/engineer/commands/{command_id}/archive", handle_engineer_archive
    )
    app.router.add_get("/api/robot/engineer/flows", handle_engineer_flows)
    app.router.add_post("/api/robot/engineer/flows", handle_engineer_flows)
    app.router.add_get("/api/robot/engineer/flows/{flow_id}", handle_engineer_flow)
    app.router.add_put("/api/robot/engineer/flows/{flow_id}/draft", handle_engineer_flow_draft)
    app.router.add_post("/api/robot/engineer/flows/{flow_id}/draft", handle_engineer_flow_draft)
    app.router.add_post("/api/robot/engineer/flows/{flow_id}/validate", handle_engineer_flow_validate)
    app.router.add_post("/api/robot/engineer/flows/{flow_id}/publish", handle_engineer_flow_publish)
    app.router.add_post("/api/robot/engineer/flows/{flow_id}/archive", handle_engineer_flow_archive)
    app.router.add_get("/api/robot/engineer/audit", handle_engineer_audit)


# ---------------------------------------------------------------------------
# Task 7 Step 5: unified /api/auth/* + /api/users/* transport mounting.
# No-store on every response; 429 carries Retry-After (R5). The same handlers
# serve aiohttp (real POST/PATCH) and the ws_http GET+body-header transport.
# ---------------------------------------------------------------------------


def _user_deps(request):
    """Resolve (token_store, users_path, audit_path) for auth/users endpoints."""
    from robot_ai.library.auth import get_user_session_store
    store = request.app.get("user_session_store") or get_user_session_store()
    request.app["user_session_store"] = store
    return (store, request.app.get("robot_users_path"), request.app.get("robot_audit_path"))


def _user_throttle(request):
    from robot_ai.library.auth import get_login_throttle
    return request.app.get("user_login_throttle") or get_login_throttle()


def _user_tok(request):
    return request.headers.get(_USER_TOKEN_HEADER) or request.headers.get(_ENGINEER_TOKEN_HEADER)


def _actor_from(store, tok):
    s = store.check(tok) if tok else None
    if s is None:
        return {"actor": "user:?"}
    return {"actor": f"user:{s['user_id']}", "actor_user_id": s["user_id"],
            "actor_username": s["username"], "actor_role": s["role"]}


async def handle_auth_login(request):
    store, _up, audit_path = _user_deps(request)
    client_key = (request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
                  or request.query.get("token") or "anon")
    status, body = process_auth_login(await _eng_body(request), audit_path=audit_path,
                                       token_store=store, throttle=_user_throttle(request),
                                       client_key=client_key)
    return _eng_response(body, status)


async def handle_auth_logout(request):
    store, _up, audit_path = _user_deps(request)
    tok = _user_tok(request)
    session = store.check(tok) if tok else None
    status, body = process_auth_logout(tok, token_store=store, audit_path=audit_path, session=session)
    return _eng_response(body, status)


async def handle_users_collection(request):
    store, users_path, audit_path = _user_deps(request)
    tok = _user_tok(request)
    if request.method == "POST":
        status, body = process_users_create(await _eng_body(request), users_path=users_path,
                                             audit_path=audit_path, token_store=store, user_token=tok,
                                             actor=_actor_from(store, tok))
    else:
        status, body = process_users_list(users_path=users_path, token_store=store, user_token=tok)
    return _eng_response(body, status)


async def handle_users_item(request):
    store, users_path, audit_path = _user_deps(request)
    tok = _user_tok(request)
    status, body = process_users_patch(request.match_info["user_id"], await _eng_body(request),
                                        users_path=users_path, audit_path=audit_path,
                                        token_store=store, user_token=tok, actor=_actor_from(store, tok))
    return _eng_response(body, status)


async def handle_users_item_password(request):
    store, users_path, audit_path = _user_deps(request)
    tok = _user_tok(request)
    status, body = process_users_reset_password(request.match_info["user_id"], await _eng_body(request),
                                                 users_path=users_path, audit_path=audit_path,
                                                 token_store=store, user_token=tok, actor=_actor_from(store, tok))
    return _eng_response(body, status)


async def handle_users_me_password(request):
    store, users_path, audit_path = _user_deps(request)
    tok = _user_tok(request)
    status, body = process_users_me_password(await _eng_body(request), users_path=users_path,
                                              audit_path=audit_path, token_store=store, user_token=tok,
                                              actor=_actor_from(store, tok))
    return _eng_response(body, status)


def register_auth_routes(app):
    app.router.add_post("/api/auth/login", handle_auth_login)
    app.router.add_get("/api/auth/login", handle_auth_login)   # ws_http GET+body-header mirror
    app.router.add_post("/api/auth/logout", handle_auth_logout)
    app.router.add_get("/api/auth/logout", handle_auth_logout)


def register_users_routes(app):
    app.router.add_get("/api/users", handle_users_collection)
    app.router.add_post("/api/users", handle_users_collection)
    app.router.add_patch("/api/users/{user_id}", handle_users_item)
    app.router.add_post("/api/users/{user_id}/password", handle_users_item_password)
    app.router.add_post("/api/users/me/password", handle_users_me_password)
    app.router.add_get("/api/users", handle_users_collection)           # GET+body-header mirror
    app.router.add_get("/api/users/me/password", handle_users_me_password)
