"""HTTP API handler extracted from WebSocketChannel.

Handles all non-WebSocket HTTP routes: bootstrap, sessions, settings,
media, commands, sidebar state, static file serving, and token management.

Also houses shared HTTP utility functions used by both this module and
``websocket.py`` to avoid circular imports.
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote

from loguru import logger
from websockets.http11 import Request as WsRequest
from websockets.http11 import Response

from nanobot.command.builtin import builtin_command_palette
from nanobot.cron.session_turns import is_bound_cron_job
from nanobot.cron.types import CronJob, CronSchedule
from nanobot.session.namespace import SessionNotAvailableError, derive_namespace
from nanobot.triggers.local_types import LocalTrigger
from nanobot.utils.subagent_channel_display import scrub_subagent_messages_for_channel
from nanobot.webui.file_preview import WebUIFilePreviewError, file_preview_payload
from nanobot.webui.gateway_tokens import GatewayTokenStore, token_response_payload
from nanobot.webui.http_utils import (
    case_insensitive_header as _case_insensitive_header,
)
from nanobot.webui.http_utils import (
    host_for_url as _host_for_url,
)
from nanobot.webui.http_utils import (
    http_error as _http_error,
)
from nanobot.webui.http_utils import (
    http_json_response as _http_json_response,
)
from nanobot.webui.http_utils import (
    http_response as _http_response,
)
from nanobot.webui.http_utils import (
    is_localhost as _is_localhost,
)
from nanobot.webui.http_utils import (
    issue_route_secret_matches as _issue_route_secret_matches,
)
from nanobot.webui.http_utils import (
    normalize_config_path as _normalize_config_path,
)
from nanobot.webui.http_utils import (
    parse_query as _parse_query,
)
from nanobot.webui.http_utils import (
    parse_request_path as _parse_request_path,
)
from nanobot.webui.http_utils import (
    query_first as _query_first,
)
from nanobot.webui.http_utils import (
    safe_host_header as _safe_host_header,
)
from nanobot.webui.media_gateway import WebUIMediaGateway
from nanobot.webui.session_automations import (
    all_automations_payload,
    serialize_automation_jobs,
    session_automation_jobs,
    session_automations_payload,
)
from nanobot.webui.session_list_index import list_webui_sessions
from nanobot.webui.sidebar_state import (
    read_webui_sidebar_state,
    write_webui_sidebar_state,
)
from nanobot.webui.skills_api import webui_skill_detail_payload, webui_skills_payload
from nanobot.webui.thread_disk import delete_webui_thread
from nanobot.webui.transcript import build_webui_thread_response
from nanobot.webui.workspaces import WebUIWorkspaceController

_SLOW_WEBUI_HTTP_LOG_MS = 1_000
_AUTOMATION_VALUES_HEADER = "X-Nanobot-Automation-Values"
_ROBOT_BODY_HEADER = "X-Nanobot-Robot-Body"
_ENGINEER_PATH_PREFIX = "/api/robot/engineer/"
_AUTH_PATH_PREFIX = "/api/auth/"
_USERS_PATH_PREFIX = "/api/users/"

if TYPE_CHECKING:
    from nanobot.bus.queue import MessageBus
    from nanobot.cron.service import CronService
    from nanobot.session.manager import SessionManager
    from nanobot.triggers.local_store import LocalTriggerStore


def _decode_api_key(raw_key: str) -> str | None:
    key = unquote(raw_key)
    _api_key_re = re.compile(r"^[A-Za-z0-9_:.-]{1,128}$")
    if _api_key_re.match(key) is None:
        return None
    return key


def _default_model_name_from_config() -> str | None:
    try:
        from nanobot.config.loader import load_config
        model = load_config().resolve_preset().model.strip()
        return model or None
    except Exception as e:
        logger.debug("bootstrap model_name could not load from config: {}", e)
        return None


def _resolve_bootstrap_model_name(
    runtime_name: Callable[[], str | None] | None,
) -> str:
    if runtime_name is not None:
        try:
            raw = runtime_name()
        except Exception as e:
            logger.debug("bootstrap runtime model resolver failed: {}", e)
        else:
            if isinstance(raw, str):
                stripped = raw.strip()
                if stripped:
                    return stripped
    return _default_model_name_from_config() or ""


# ---------------------------------------------------------------------------
# Slice ② multi-user namespace gate (REST session routes)
# ---------------------------------------------------------------------------

_USER_TOKEN_HEADER = "X-Nanobot-User-Token"


def derive_namespace_from_user_token(user_token: str) -> str | None:
    """Resolve the caller's namespace from an ``X-Nanobot-User-Token`` value.

    Returns ``None`` when the token is missing, blank, unknown, or expired —
    i.e. the caller is unauthenticated and must be turned away at the gate
    before any session data is touched.
    """
    if not user_token:
        return None
    from robot_ai.library.auth import get_user_session_store

    session = get_user_session_store().check(user_token)
    if session is None:
        return None
    return derive_namespace(session["role"], session["user_id"])


def enforce_session_owner(session_manager: Any, key: str, namespace: str) -> None:
    """Raise :class:`SessionNotAvailableError` unless *key* is owned by *namespace*.

    Thin pass-through so callers don't import from ``nanobot.session.namespace``
    directly and REST handlers stay uniform.
    """
    session_manager.assert_namespace_owner(key, namespace)


def validate_namespace_param(*, derived: str, supplied: str | None) -> bool:
    """True when *supplied* matches *derived* or is omitted (server-derived)."""
    return supplied is None or supplied == derived


def _user_token_from_request(request: WsRequest) -> str:
    raw = request.headers.get(_USER_TOKEN_HEADER, "") or ""
    return raw.strip()


def _decode_session_key(key: str) -> str | None:
    """Decode a URL session-key segment to the real session key.

    Mirrors :func:`_decode_api_key` (the decoding every ``_handle_session_*``
    handler already applies downstream): ``unquote`` then a strict charset
    guard. Returns ``None`` for malformed segments so the gate fails closed.
    """
    return _decode_api_key(key)


# ---------------------------------------------------------------------------
# GatewayHTTPHandler
# ---------------------------------------------------------------------------


class GatewayHTTPHandler:
    """Handles all HTTP routes served alongside the WebSocket endpoint.

    Routes HTTP requests and delegates stateful work to explicit gateway
    services owned by the composition layer.
    """

    def __init__(
        self,
        *,
        config: Any,  # WebSocketConfig
        session_manager: SessionManager | None,
        static_dist_path: Path | None,
        runtime_model_name: Callable[[], str | None] | None,
        runtime_surface: str,
        runtime_capabilities_overrides: dict[str, Any] | None,
        bus: MessageBus,
        tokens: GatewayTokenStore,
        media: WebUIMediaGateway,
        workspaces: WebUIWorkspaceController,
        skills_workspace_path: Path,
        disabled_skills: set[str] | None = None,
        cron_service: CronService | None = None,
        local_trigger_store: LocalTriggerStore | None = None,
        cron_pending_job_ids: Callable[[str], set[str]] | None = None,
        local_trigger_pending_ids: Callable[[str], set[str]] | None = None,
        log: Any = logger,
    ) -> None:
        self.config = config
        self.session_manager = session_manager
        self.static_dist_path = static_dist_path
        self.runtime_model_name = runtime_model_name
        self.bus = bus
        self.tokens = tokens
        self.media = media
        self.workspaces = workspaces
        self.skills_workspace_path = skills_workspace_path
        self.disabled_skills = disabled_skills or set()
        self.cron_service = cron_service
        self.local_trigger_store = local_trigger_store
        self.cron_pending_job_ids = cron_pending_job_ids
        self.local_trigger_pending_ids = local_trigger_pending_ids
        self._log = log
        self._runtime_surface = runtime_surface

        from nanobot.webui.settings_api import runtime_capabilities as _rc
        from nanobot.webui.settings_routes import WebUISettingsRouter

        self._capabilities = _rc(runtime_surface, runtime_capabilities_overrides or {})
        self.settings_routes = WebUISettingsRouter(
            bus=bus,
            logger=self._log,
            check_api_token=self.check_api_token,
            parse_query=_parse_query,
            json_response=_http_json_response,
            error_response=_http_error,
            runtime_surface=runtime_surface,
            runtime_capabilities=self._capabilities,
        )

    def workspace_controls_available(self, connection: Any) -> bool:
        return self._runtime_surface == "native" or _is_localhost(connection)

    # -- Token management ---------------------------------------------------

    def check_api_token(self, request: WsRequest) -> bool:
        return self.tokens.check_api_token(request)

    # -- Main dispatch ------------------------------------------------------

    async def dispatch(self, connection: Any, request: WsRequest) -> Any | None:
        """Route an HTTP request. Returns Response or None."""
        got, _ = _parse_request_path(request.path)
        started = time.perf_counter()
        response: Any | None = None

        try:
            response = await self._dispatch_resolved(connection, request, got)
            return response
        finally:
            self._log_slow_http(got, response, started)

    async def _dispatch_resolved(
        self,
        connection: Any,
        request: WsRequest,
        got: str,
    ) -> Any | None:
        # Token issue endpoint
        if self.config.token_issue_path:
            issue_expected = _normalize_config_path(self.config.token_issue_path)
            if got == issue_expected:
                return self._handle_token_issue(connection, request)

        # Bootstrap
        if got == "/webui/bootstrap":
            return self._handle_bootstrap(connection, request)

        # Settings routes (delegated)
        response = await self.settings_routes.dispatch(request, got)
        if response is not None:
            return response

        # Login preflight is bootstrap-token protected but intentionally does
        # not require a user session: it runs bounded, read-only diagnostics
        # before the role login form is submitted.
        response = await asyncio.to_thread(self._dispatch_login_preflight, request, got)
        if response is not None:
            return response

        # Session routes
        response = await self._dispatch_session_routes(request, got)
        if response is not None:
            return response

        # Robot AI routes (dry-run -> confirm -> execute). These do blocking Modbus
        # I/O (ZAux reads/writes over Ethernet), so run them in a worker thread — a
        # status poll every ~3s must not freeze the asyncio event loop (which would
        # stall WebSocket chat traffic / run-status updates). The shared
        # ZMotionSdkClient is thread-safe (per-operation RLock).
        response = await asyncio.to_thread(self._dispatch_robot_routes, request, got)
        if response is not None:
            return response

        # Engineer API routes (login / commands CRUD / draft / publish / archive /
        # audit). Mounted on the GET-only ws_http transport via the
        # X-Nanobot-Robot-Body + X-Nanobot-Engineer-Action headers (D9). Runs in a
        # worker thread like the robot routes — command writes are atomic file I/O.
        response = await asyncio.to_thread(self._dispatch_robot_engineer_routes, request, got)
        if response is not None:
            return response

        # Unified auth + users API (Task 7). Same GET+body-header transport as the
        # engineer routes; run in a worker thread for atomic-file-I/O parity.
        response = await asyncio.to_thread(self._dispatch_auth_routes, request, got)
        if response is not None:
            return response
        response = await asyncio.to_thread(self._dispatch_users_routes, request, got)
        if response is not None:
            return response

        # Media routes
        response = self._dispatch_media_routes(request, got)
        if response is not None:
            return response

        # Automation routes
        response = await self._dispatch_automation_routes(request, got)
        if response is not None:
            return response

        # Misc routes
        response = await self._dispatch_misc_routes(connection, request, got)
        if response is not None:
            return response

        # API 404 (never serve SPA for /api/ routes)
        if got.startswith("/api/"):
            return _http_error(404, "API route not found")

        # Static SPA serving
        if self.static_dist_path is not None:
            response = self._serve_static(got)
            if response is not None:
                return response

        return connection.respond(404, "Not Found")

    def _log_slow_http(self, path: str, response: Any | None, started: float) -> None:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        if elapsed_ms < _SLOW_WEBUI_HTTP_LOG_MS:
            return
        if not (path.startswith("/api/") or path == "/webui/bootstrap"):
            return
        status = getattr(response, "status_code", None)
        self._log.warning(
            "slow webui http route path={} status={} duration_ms={}",
            path,
            status if status is not None else "none",
            elapsed_ms,
        )

    # -- Token issue --------------------------------------------------------

    def _handle_token_issue(self, connection: Any, request: Any) -> Any:
        secret = self.config.token_issue_secret.strip() or self.config.token.strip()
        if secret:
            if not _issue_route_secret_matches(request.headers, secret):
                return connection.respond(401, "Unauthorized")
        else:
            self._log.warning(
                "token_issue_path is set but token_issue_secret is empty; "
                "any client can obtain connection tokens — set token_issue_secret for production."
            )
        if not self.tokens.can_issue():
            self._log.error(
                "too many outstanding issued tokens ({}), rejecting issuance",
                len(self.tokens.issued_tokens),
            )
            return _http_json_response({"error": "too many outstanding tokens"}, status=429)
        token_value = self.tokens.issue_token(self.config.token_ttl_s)
        return _http_json_response(token_response_payload(token_value, self.config.token_ttl_s))

    # -- Bootstrap ----------------------------------------------------------

    def _handle_bootstrap(self, connection: Any, request: Any) -> Response:
        secret = self.config.token_issue_secret.strip() or self.config.token.strip()
        if not _is_localhost(connection):
            if secret:
                if not _issue_route_secret_matches(request.headers, secret):
                    return _http_error(401, "Unauthorized")
            else:
                return _http_error(403, "bootstrap is localhost-only")

        if not self.tokens.can_issue(include_api_token=True):
            return _http_response(
                json.dumps({"error": "too many outstanding tokens"}).encode("utf-8"),
                status=429,
                content_type="application/json; charset=utf-8",
            )
        token = self.tokens.issue_token(self.config.token_ttl_s, api_token=True)

        ws_url = self._bootstrap_ws_url(request)
        expected_path = _normalize_config_path(self.config.path)
        return _http_json_response(
            {
                "token": token,
                "ws_path": expected_path,
                "ws_url": ws_url,
                "expires_in": self.config.token_ttl_s,
                "model_name": _resolve_bootstrap_model_name(self.runtime_model_name),
                "runtime_surface": self._runtime_surface,
                "runtime_capabilities": self._capabilities,
            }
        )

    def _bootstrap_ws_url(self, request: Any) -> str:
        headers = getattr(request, "headers", {}) or {}
        host = _safe_host_header(_case_insensitive_header(headers, "Host"))
        if not host:
            host = _host_for_url(self.config.host, self.config.port)
        proto = _case_insensitive_header(headers, "X-Forwarded-Proto")
        proto = proto.split(",", 1)[0].strip().lower()
        secure = proto in {"https", "wss"} or bool(self.config.ssl_certfile.strip())
        scheme = "wss" if secure else "ws"
        expected_path = _normalize_config_path(self.config.path)
        return f"{scheme}://{host}{expected_path}"

    # -- Session routes -----------------------------------------------------

    async def _dispatch_session_routes(self, request: WsRequest, got: str) -> Response | None:
        m = re.match(r"^/api/sessions/([^/]+)/messages$", got)
        if m:
            return self._handle_session_messages(request, m.group(1))

        m = re.match(r"^/api/sessions/([^/]+)/webui-thread$", got)
        if m:
            return self._handle_webui_thread_get(request, m.group(1))

        m = re.match(r"^/api/sessions/([^/]+)/file-preview$", got)
        if m:
            return self._handle_file_preview(request, m.group(1))

        m = re.match(r"^/api/sessions/([^/]+)/automations$", got)
        if m:
            return self._handle_session_automations(request, m.group(1))

        m = re.match(r"^/api/sessions/([^/]+)/delete$", got)
        if m:
            return self._handle_session_delete(request, m.group(1))

        return None

    # -- Robot AI routes ----------------------------------------------------

    def _dispatch_robot_library_routes(self, request: WsRequest, got: str) -> Response | None:
        """Dispatch the read-only ``/api/robot/library/*`` endpoints.

        Token-gated GET (no body), mounted through the robot dispatcher so the
        library inherits the same ``check_api_token`` gate as the other robot
        routes. Detail paths use regex (the rest of the robot dispatcher is
        exact-match only). ``?version=`` is explicitly unsupported in A1.
        """
        command_run = re.match(r"^/api/robot/library/commands/([^/]+)/run$", got)
        flow_run = re.match(r"^/api/robot/library/flows/([^/]+)/run$", got)
        execution_control = re.match(r"^/api/robot/library/executions/([^/]+)/control$", got)
        execution_status = re.match(r"^/api/robot/library/executions/([^/]+)$", got)
        command_detail = re.match(r"^/api/robot/library/commands/([^/]+)$", got)
        component_detail = re.match(r"^/api/robot/library/components/([^/]+)$", got)
        flow_detail = re.match(r"^/api/robot/library/flows/([^/]+)$", got)
        is_command_list = got == "/api/robot/library/commands"
        is_component_list = got == "/api/robot/library/components"
        is_flow_list = got == "/api/robot/library/flows"
        is_execution_list = got == "/api/robot/library/executions"
        if not (command_run or flow_run or execution_control or execution_status or command_detail or component_detail or flow_detail
                or is_command_list or is_component_list or is_flow_list or is_execution_list):
            return None

        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")

        query = _parse_query(request.path)
        if _query_first(query, "version") is not None:
            return _http_error(400, "unsupported parameter: version")

        from nanobot.api.robot_routes import (
            DEFAULT_COMMANDS_PATH,
            DEFAULT_FLOW_REGISTRY_PATH,
            process_robot_library_command,
            process_robot_library_commands,
            process_robot_library_component,
            process_robot_library_components,
            process_robot_library_flow,
            process_robot_library_flows,
            process_robot_library_command_execution,
            process_robot_library_flow_execution,
            process_robot_library_execution_control,
            process_robot_library_execution_list,
            process_robot_library_execution_status,
        )

        commands_path = getattr(self, "_robot_commands_path", None) or DEFAULT_COMMANDS_PATH
        flow_registry_path = getattr(self, "_robot_flow_registry_path", None) or DEFAULT_FLOW_REGISTRY_PATH

        if command_run or flow_run or execution_control or execution_status or is_execution_list:
            from robot_ai.library.auth import get_user_session_store
            user_session = get_user_session_store().check(_user_token_from_request(request))
            if user_session is None:
                return _http_error(401, "Authenticated user required")
            actor = str(user_session.get("user_id", ""))
            if command_run:
                status, result = process_robot_library_command_execution(
                    unquote(command_run.group(1)), commands_path=commands_path, actor=actor,
                )
            elif flow_run:
                status, result = process_robot_library_flow_execution(
                    unquote(flow_run.group(1)), flow_registry_path=flow_registry_path, actor=actor,
                )
            elif execution_control:
                status, result = process_robot_library_execution_control(
                    unquote(execution_control.group(1)),
                    action=_query_first(query, "action") or "",
                    actor=actor,
                )
            elif is_execution_list:
                status, result = process_robot_library_execution_list(actor=actor)
            else:
                status, result = process_robot_library_execution_status(
                    unquote(execution_status.group(1)), actor=actor,
                )
        elif is_command_list:
            status, result = process_robot_library_commands(
                commands_path=commands_path,
                component_id=_query_first(query, "component_id") or None,
                risk_level=_query_first(query, "risk_level") or None,
                status=_query_first(query, "status") or None,
                q=_query_first(query, "q") or None,
            )
        elif command_detail is not None:
            status, result = process_robot_library_command(
                unquote(command_detail.group(1)), commands_path=commands_path
            )
        elif is_component_list:
            status, result = process_robot_library_components()
        elif is_flow_list:
            status, result = process_robot_library_flows(flow_registry_path=flow_registry_path)
        elif flow_detail is not None:
            status, result = process_robot_library_flow(
                unquote(flow_detail.group(1)), flow_registry_path=flow_registry_path
            )
        else:  # component_detail
            status, result = process_robot_library_component(unquote(component_detail.group(1)))
        return _http_json_response(result, status=status)

    def _dispatch_login_preflight(self, request: WsRequest, got: str) -> Response | None:
        if got != "/api/login/preflight":
            return None
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        body = _robot_body_from_request(request)
        if body is None:
            return _http_error(400, "missing or invalid X-Nanobot-Robot-Body JSON payload")
        from nanobot.webui.login_preflight import PreflightInputError, run_login_preflight

        try:
            result = run_login_preflight(body.get("controller_host"))
        except PreflightInputError as exc:
            return _http_error(400, str(exc))
        return _http_json_response({"ok": True, "data": result})

    def _dispatch_robot_routes(self, request: WsRequest, got: str) -> Response | None:
        """Dispatch the robot AI dry-run / confirm / execute endpoints.

        The gateway runs on the ``websockets`` library, whose ``process_request``
        hook only sees HTTP GET requests (POST is rejected at the protocol
        level) and never exposes a request body. The JSON payload therefore
        travels in the ``X-Nanobot-Robot-Body`` header, mirroring the existing
        ``X-Nanobot-Automation-Values`` / ``X-Nanobot-MCP-Values`` convention.
        """
        lib_response = self._dispatch_robot_library_routes(request, got)
        if lib_response is not None:
            return lib_response

        if got not in (
            "/api/robot/pending-plan",
            "/api/robot/confirm",
            "/api/robot/execute",
            "/api/robot/flow-pending-plan",
            "/api/robot/flow-confirm",
            "/api/robot/flow-execute",
            "/api/robot/status",
            "/api/robot/system-action",
        ):
            return None

        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")

        # /api/robot/status is a read-only GET with no body — handle it before
        # the X-Nanobot-Robot-Body requirement below.
        if got == "/api/robot/status":
            from nanobot.api.robot_routes import process_robot_status

            status, result = process_robot_status()
            return _http_json_response(result, status=status)

        body = _robot_body_from_request(request)
        if body is None:
            return _http_error(400, "missing or invalid X-Nanobot-Robot-Body JSON payload")

        from nanobot.api.robot_routes import (
            DEFAULT_FLOW_REGISTRY_PATH,
            process_robot_confirm,
            process_robot_execute,
            process_robot_flow_confirm,
            process_robot_flow_execute,
            process_robot_flow_pending_plan,
            process_robot_pending_plan,
        )
        from robot_ai.zmotion_operator_control import (
            _PENDING_PLAN_STORE,
            _SESSION_GATE_STORE,
            run_zmotion_operator_command,
        )

        flow_registry_path = getattr(self, "_robot_flow_registry_path", None) or (
            DEFAULT_FLOW_REGISTRY_PATH
        )

        if got == "/api/robot/pending-plan":
            status, result = process_robot_pending_plan(
                body,
                pending=_PENDING_PLAN_STORE,
                session=_SESSION_GATE_STORE,
                runner=run_zmotion_operator_command,
            )
        elif got == "/api/robot/confirm":
            status, result = process_robot_confirm(
                body, pending=_PENDING_PLAN_STORE, session=_SESSION_GATE_STORE
            )
        elif got == "/api/robot/execute":
            status, result = process_robot_execute(
                body,
                pending=_PENDING_PLAN_STORE,
                runner=run_zmotion_operator_command,
            )
        elif got == "/api/robot/flow-pending-plan":
            status, result = process_robot_flow_pending_plan(
                body,
                pending=_PENDING_PLAN_STORE,
                session=_SESSION_GATE_STORE,
                flow_registry_path=flow_registry_path,
            )
        elif got == "/api/robot/flow-confirm":
            status, result = process_robot_flow_confirm(
                body, pending=_PENDING_PLAN_STORE, session=_SESSION_GATE_STORE
            )
        elif got == "/api/robot/system-action":
            from nanobot.api.robot_routes import process_robot_system_action

            status, result = process_robot_system_action(
                body,
                runner=run_zmotion_operator_command,
            )
        else:  # /api/robot/flow-execute
            status, result = process_robot_flow_execute(
                body,
                pending=_PENDING_PLAN_STORE,
                session=_SESSION_GATE_STORE,
                flow_registry_path=flow_registry_path,
            )
        return _http_json_response(result, status=status)

    def _dispatch_robot_engineer_routes(
        self, request: WsRequest, got: str
    ) -> Response | None:
        """Mount the engineer API on the GET-only ws_http transport (spec §6, D9).

        The websockets ``process_request`` hook only sees HTTP GET, so mutating
        intent is disambiguated by the ``X-Nanobot-Engineer-Action`` header
        (``create`` on ``/commands``; ``start-draft`` / ``update-draft`` on
        ``/commands/{id}/draft``). No action = read-only (list / detail).
        Unknown or path-mismatched action = ``400``. ``publish`` / ``archive`` /
        ``login`` / ``logout`` / ``audit`` are path-disambiguated and need no
        action. Every response carries ``Cache-Control: no-store``; 429 also
        carries ``Retry-After`` (R5).
        """
        if not got.startswith(_ENGINEER_PATH_PREFIX):
            return None  # not ours — let other dispatchers handle

        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")  # gateway-token gate (D2)

        from nanobot.api import robot_routes
        from robot_ai.library.auth import get_login_throttle, get_user_session_store

        store = getattr(self, "_user_session_store", None) or get_user_session_store()
        throttle = getattr(self, "_user_login_throttle", None) or get_login_throttle()
        commands_path = getattr(self, "_robot_commands_path", None) or robot_routes.DEFAULT_COMMANDS_PATH
        flows_path = getattr(self, "_robot_flow_registry_path", None) or robot_routes.DEFAULT_FLOW_REGISTRY_PATH
        audit_path = getattr(self, "_robot_audit_path", None)
        config_path = getattr(self, "_engineer_config_path", None)

        body = _robot_body_from_request(request)
        etok = (_case_insensitive_header(request.headers, robot_routes._USER_TOKEN_HEADER)
                or _case_insensitive_header(request.headers, robot_routes._ENGINEER_TOKEN_HEADER)) or None
        action = _case_insensitive_header(request.headers, robot_routes._ENGINEER_ACTION_HEADER) or None
        no_store = {"Cache-Control": "no-store", "Pragma": "no-cache"}

        def _resp(status: int, rbody: dict) -> Response:
            headers = dict(no_store)
            if status == 429:
                ra = (rbody or {}).get("data", {}).get("retry_after")
                if ra is not None:
                    headers["Retry-After"] = str(ra)  # R5
            return _http_json_response(rbody, status=status, headers=headers)

        def _bad(msg: str) -> Response:
            return _resp(400, {"error": {"code": "invalid_action", "message": msg}})

        query = _parse_query(request.path)

        # login / logout / audit — path-disambiguated (no action needed).
        if got == "/api/robot/engineer/login":
            client_key = (
                _case_insensitive_header(request.headers, "Authorization")
                or ""
            ).removeprefix("Bearer ").strip()
            if not client_key:
                client_key = _query_first(query, "token") or "anon"  # D2
            return _resp(*robot_routes.process_engineer_login(
                body, token_store=store, throttle=throttle, config_path=config_path,
                audit_path=audit_path, client_key=client_key))
        if got == "/api/robot/engineer/logout":
            return _resp(*robot_routes.process_engineer_logout(
                etok, token_store=store, audit_path=audit_path))
        if got == "/api/robot/engineer/audit":
            return _resp(*robot_routes.process_engineer_audit(
                audit_path=audit_path,
                limit=int((_query_first(query, "limit") or "50")),
                before=_query_first(query, "before"),
                token_store=store, engineer_token=etok))

        # commands collection: create (Action) vs list (no action).
        if got == "/api/robot/engineer/commands":
            if action is None:
                return _resp(*robot_routes.process_engineer_commands(
                    commands_path=commands_path, audit_path=audit_path,
                    token_store=store, engineer_token=etok))
            if action == "batch-archive":
                return _resp(*robot_routes.process_engineer_bulk_archive_commands(
                    body or {}, commands_path=commands_path, audit_path=audit_path,
                    token_store=store, engineer_token=etok))
            if action != "create":
                return _bad(f"Action {action!r} not valid on /commands.")
            return _resp(*robot_routes.process_engineer_create_command(
                body, commands_path=commands_path, audit_path=audit_path,
                token_store=store, engineer_token=etok))

        # flows collection: create (Action) vs list (no action).
        if got == "/api/robot/engineer/flows":
            if action is None:
                return _resp(*robot_routes.process_engineer_flows(
                    flows_path=flows_path, audit_path=audit_path,
                    token_store=store, engineer_token=etok))
            if action == "batch-archive":
                return _resp(*robot_routes.process_engineer_bulk_archive_flows(
                    body or {}, flows_path=flows_path, audit_path=audit_path,
                    token_store=store, engineer_token=etok))
            if action != "create":
                return _bad(f"Action {action!r} not valid on /flows.")
            return _resp(*robot_routes.process_engineer_create_flow(
                body, flows_path=flows_path, audit_path=audit_path,
                token_store=store, engineer_token=etok))

        # command sub-resources: {id} | {id}/draft | {id}/publish | {id}/archive
        if got.startswith("/api/robot/engineer/commands/"):
            rest = got[len("/api/robot/engineer/commands/"):]
            parts = rest.split("/")
            if not parts or not parts[0]:
                return _bad(f"Unknown engineer route {got!r}.")
            cid = unquote(parts[0])
            # /commands/{id} -> detail (read-only; no action required/allowed).
            if len(parts) == 1:
                return _resp(*robot_routes.process_engineer_command(
                    cid, commands_path=commands_path, audit_path=audit_path,
                    token_store=store, engineer_token=etok))
            if len(parts) != 2:
                return _bad(f"Unknown engineer route {got!r}.")
            sub = parts[1]
            if sub == "draft":
                if action == "start-draft":
                    return _resp(*robot_routes.process_engineer_start_draft(
                        cid, commands_path=commands_path, audit_path=audit_path,
                        token_store=store, engineer_token=etok))
                if action == "update-draft":
                    return _resp(*robot_routes.process_engineer_update_draft(
                        cid, body or {}, commands_path=commands_path, audit_path=audit_path,
                        token_store=store, engineer_token=etok))
                return _bad("draft path requires Action start-draft or update-draft.")
            if sub == "publish":
                return _resp(*robot_routes.process_engineer_publish(
                    cid, commands_path=commands_path, audit_path=audit_path,
                    token_store=store, engineer_token=etok))
            if sub == "archive":
                return _resp(*robot_routes.process_engineer_archive(
                    cid, commands_path=commands_path, audit_path=audit_path,
                    token_store=store, engineer_token=etok))
            if sub == "duplicate":
                if action != "duplicate":
                    return _bad("duplicate path requires Action duplicate.")
                return _resp(*robot_routes.process_engineer_duplicate_command(
                    cid, body or {}, commands_path=commands_path, audit_path=audit_path,
                    token_store=store, engineer_token=etok))
            return _bad(f"Unknown engineer route {got!r}.")

        # flow sub-resources: {id} | {id}/draft | {id}/validate | publish | archive
        if got.startswith("/api/robot/engineer/flows/"):
            rest = got[len("/api/robot/engineer/flows/"):]
            parts = rest.split("/")
            if not parts or not parts[0]:
                return _bad(f"Unknown engineer route {got!r}.")
            flow_id = unquote(parts[0])
            if len(parts) == 1:
                return _resp(*robot_routes.process_engineer_flow(
                    flow_id, flows_path=flows_path, audit_path=audit_path,
                    token_store=store, engineer_token=etok))
            if len(parts) != 2:
                return _bad(f"Unknown engineer route {got!r}.")
            sub = parts[1]
            if sub == "draft":
                if action == "start-draft":
                    return _resp(*robot_routes.process_engineer_start_flow_draft(
                        flow_id, flows_path=flows_path, audit_path=audit_path,
                        token_store=store, engineer_token=etok))
                if action == "update-draft":
                    return _resp(*robot_routes.process_engineer_update_flow_draft(
                        flow_id, body or {}, flows_path=flows_path, audit_path=audit_path,
                        token_store=store, engineer_token=etok))
                return _bad("draft path requires Action start-draft or update-draft.")
            if sub == "validate":
                if action != "validate":
                    return _bad("validate path requires Action validate.")
                return _resp(*robot_routes.process_engineer_validate_flow_draft(
                    flow_id, flows_path=flows_path, audit_path=audit_path,
                    token_store=store, engineer_token=etok))
            if sub == "publish":
                if action != "publish":
                    return _bad("publish path requires Action publish.")
                return _resp(*robot_routes.process_engineer_publish_flow(
                    flow_id, flows_path=flows_path, audit_path=audit_path,
                    token_store=store, engineer_token=etok))
            if sub == "archive":
                if action != "archive":
                    return _bad("archive path requires Action archive.")
                return _resp(*robot_routes.process_engineer_archive_flow(
                    flow_id, flows_path=flows_path, audit_path=audit_path,
                    token_store=store, engineer_token=etok))
            if sub == "duplicate":
                if action != "duplicate":
                    return _bad("duplicate path requires Action duplicate.")
                return _resp(*robot_routes.process_engineer_duplicate_flow(
                    flow_id, body or {}, flows_path=flows_path, audit_path=audit_path,
                    token_store=store, engineer_token=etok))
            return _bad(f"Unknown engineer route {got!r}.")

        return _bad(f"Unknown engineer route {got!r}.")

    def _dispatch_auth_routes(self, request: WsRequest, got: str) -> Response | None:
        """Mount /api/auth/* on the GET-only ws_http transport (Task 7).

        ``login`` / ``logout`` are path-disambiguated. Every response carries
        ``Cache-Control: no-store``; 429 also carries ``Retry-After`` (R5).
        """
        if not got.startswith(_AUTH_PATH_PREFIX):
            return None
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        from nanobot.api import robot_routes as robot_routes
        from robot_ai.library.auth import get_login_throttle, get_user_session_store
        store = getattr(self, "_user_session_store", None) or get_user_session_store()
        throttle = getattr(self, "_user_login_throttle", None) or get_login_throttle()
        audit_path = getattr(self, "_robot_audit_path", None)
        body = _robot_body_from_request(request)
        no_store = {"Cache-Control": "no-store", "Pragma": "no-cache"}

        def _resp(status, rbody):
            headers = dict(no_store)
            if status == 429:
                ra = (rbody or {}).get("data", {}).get("retry_after")
                if ra is not None:
                    headers["Retry-After"] = str(ra)
            return _http_json_response(rbody, status=status, headers=headers)

        if got == "/api/auth/login":
            client_key = ((_case_insensitive_header(request.headers, "Authorization") or "")
                          .removeprefix("Bearer ").strip() or "anon")
            return _resp(*robot_routes.process_auth_login(body, audit_path=audit_path, token_store=store,
                                                throttle=throttle, client_key=client_key))
        if got == "/api/auth/logout":
            tok = (_case_insensitive_header(request.headers, robot_routes._USER_TOKEN_HEADER)
                   or _case_insensitive_header(request.headers, robot_routes._ENGINEER_TOKEN_HEADER))
            session = store.check(tok) if tok else None
            return _resp(*robot_routes.process_auth_logout(tok, token_store=store, audit_path=audit_path, session=session))
        return None

    def _dispatch_users_routes(self, request: WsRequest, got: str) -> Response | None:
        """Mount /api/users/* on the GET-only ws_http transport (Task 7).

        Mutating intent is disambiguated by ``X-Nanobot-Engineer-Action: create``
        on the collection (read-only list otherwise); item routes are
        path-disambiguated. Every response carries ``Cache-Control: no-store``;
        429 also carries ``Retry-After`` (R5).
        """
        if not got.startswith(_USERS_PATH_PREFIX):
            return None
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        from nanobot.api import robot_routes as robot_routes
        from robot_ai.library.auth import get_user_session_store
        store = getattr(self, "_user_session_store", None) or get_user_session_store()
        users_path = getattr(self, "_robot_users_path", None)
        audit_path = getattr(self, "_robot_audit_path", None)
        body = _robot_body_from_request(request)
        action = _case_insensitive_header(request.headers, robot_routes._ENGINEER_ACTION_HEADER) or None
        tok = (_case_insensitive_header(request.headers, robot_routes._USER_TOKEN_HEADER)
               or _case_insensitive_header(request.headers, robot_routes._ENGINEER_TOKEN_HEADER))
        actor = robot_routes._actor_from(store, tok)
        no_store = {"Cache-Control": "no-store", "Pragma": "no-cache"}

        def _resp(status, rbody):
            headers = dict(no_store)
            if status == 429:
                ra = (rbody or {}).get("data", {}).get("retry_after")
                if ra is not None:
                    headers["Retry-After"] = str(ra)
            return _http_json_response(rbody, status=status, headers=headers)

        kw = dict(users_path=users_path, audit_path=audit_path, token_store=store, user_token=tok, actor=actor)
        if got == "/api/users":
            if action == "create":
                return _resp(*robot_routes.process_users_create(body, **kw))
            return _resp(*robot_routes.process_users_list(users_path=users_path, token_store=store, user_token=tok))
        if got == "/api/users/me/password":
            return _resp(*robot_routes.process_users_me_password(body, **kw))
        if got.startswith("/api/users/"):
            parts = got[len("/api/users/"):].split("/")
            if len(parts) == 2 and parts[1] == "password":
                return _resp(*robot_routes.process_users_reset_password(parts[0], body, **kw))
            if len(parts) == 1 and parts[0]:
                return _resp(*robot_routes.process_users_patch(parts[0], body, **kw))
        return None

    async def _handle_sessions_list(self, request: WsRequest) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        if self.session_manager is None:
            return _http_error(503, "session manager unavailable")
        ns = derive_namespace_from_user_token(_user_token_from_request(request))
        if ns is None:
            return _http_error(401, "user token required")
        supplied = _query_first(_parse_query(request.path), "namespace")
        if not validate_namespace_param(derived=ns, supplied=supplied):
            return _http_error(400, "namespace mismatch")
        payload = await asyncio.to_thread(self._sessions_list_payload, ns)
        return _http_json_response(payload)

    def _sessions_list_payload(self, namespace: str) -> dict[str, Any]:
        assert self.session_manager is not None
        sessions = list_webui_sessions(self.session_manager, namespace=namespace)
        from nanobot.session.webui_turns import websocket_turn_wall_started_at

        cleaned = []
        for s in sessions:
            key = s.get("key")
            if not (isinstance(key, str) and key.startswith("websocket:")):
                continue
            row = {k: v for k, v in s.items() if k not in ("path", "_namespace")}
            chat_id = key.split(":", 1)[1]
            started_at = websocket_turn_wall_started_at(chat_id)
            if started_at is not None:
                row["run_started_at"] = started_at
            scope = self.workspaces.scope_for_session_key(key)
            row["workspace_scope"] = scope.payload()
            cleaned.append(row)
        return {"sessions": cleaned}

    def _handle_session_messages(self, request: WsRequest, key: str) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        if self.session_manager is None:
            return _http_error(503, "session manager unavailable")
        ns = derive_namespace_from_user_token(_user_token_from_request(request))
        if ns is None:
            return _http_error(401, "user token required")
        decoded_key = _decode_session_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        try:
            enforce_session_owner(self.session_manager, decoded_key, ns)
        except SessionNotAvailableError:
            return _http_error(404, "session not available")
        if not _is_websocket_channel_session_key(decoded_key):
            return _http_error(404, "session not found")
        data = self.session_manager.read_session_file(decoded_key)
        if data is None:
            return _http_error(404, "session not found")
        messages = data.get("messages")
        if isinstance(messages, list):
            scrub_subagent_messages_for_channel(messages)
        self.media.augment_media_urls(data)
        return _http_json_response(data)

    def _handle_webui_thread_get(self, request: WsRequest, key: str) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        if self.session_manager is None:
            return _http_error(503, "session manager unavailable")
        ns = derive_namespace_from_user_token(_user_token_from_request(request))
        if ns is None:
            return _http_error(401, "user token required")
        decoded_key = _decode_session_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        try:
            enforce_session_owner(self.session_manager, decoded_key, ns)
        except SessionNotAvailableError:
            return _http_error(404, "session not available")
        if not _is_websocket_channel_session_key(decoded_key):
            return _http_error(404, "session not found")
        scope = self.workspaces.scope_for_session_key(decoded_key)
        session_messages: list[dict[str, Any]] | None = None
        if self.session_manager is not None:
            session_data = self.session_manager.read_session_file(decoded_key)
            raw_messages = session_data.get("messages") if isinstance(session_data, dict) else None
            if isinstance(raw_messages, list):
                session_messages = [m for m in raw_messages if isinstance(m, dict)]
        query = _parse_query(request.path)
        raw_limit = _query_first(query, "limit")
        limit: int | None = None
        if raw_limit is not None and raw_limit.strip():
            try:
                limit = int(raw_limit)
            except ValueError:
                return _http_error(400, "invalid limit")
        direction = _query_first(query, "direction")
        if direction is not None and direction not in {"latest"}:
            return _http_error(400, "invalid direction")
        before = _query_first(query, "before")
        data = build_webui_thread_response(
            decoded_key,
            augment_user_media=self.media.augment_transcript_media,
            augment_assistant_media=self.media.augment_transcript_media,
            augment_assistant_text=lambda text: self.media.rewrite_local_markdown_images(
                text,
                workspace_path=scope.project_path,
            ),
            session_messages=session_messages,
            limit=limit,
            direction=direction,
            before=before,
        )
        if data is None:
            return _http_error(404, "webui thread not found")
        data["workspace_scope"] = scope.payload()
        return _http_json_response(data)

    def _handle_file_preview(self, request: WsRequest, key: str) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        if self.session_manager is None:
            return _http_error(503, "session manager unavailable")
        ns = derive_namespace_from_user_token(_user_token_from_request(request))
        if ns is None:
            return _http_error(401, "user token required")
        decoded_key = _decode_session_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        try:
            enforce_session_owner(self.session_manager, decoded_key, ns)
        except SessionNotAvailableError:
            return _http_error(404, "session not available")
        if not _is_websocket_channel_session_key(decoded_key):
            return _http_error(404, "session not found")
        path = _query_first(_parse_query(request.path), "path")
        try:
            payload = file_preview_payload(
                path,
                scope=self.workspaces.scope_for_session_key(decoded_key),
            )
        except WebUIFilePreviewError as e:
            return _http_error(e.status, e.message)
        return _http_json_response(payload)

    def _handle_session_automations(self, request: WsRequest, key: str) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        if self.session_manager is None:
            return _http_error(503, "session manager unavailable")
        ns = derive_namespace_from_user_token(_user_token_from_request(request))
        if ns is None:
            return _http_error(401, "user token required")
        decoded_key = _decode_session_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        try:
            enforce_session_owner(self.session_manager, decoded_key, ns)
        except SessionNotAvailableError:
            return _http_error(404, "session not available")
        if not _is_websocket_channel_session_key(decoded_key):
            return _http_error(404, "session not found")
        pending_job_ids = self._pending_automation_ids_for_session(decoded_key)
        return _http_json_response(
            session_automations_payload(
                self.cron_service,
                decoded_key,
                local_trigger_store=self.local_trigger_store,
                pending_job_ids=pending_job_ids,
            )
        )

    def _handle_session_delete(self, request: WsRequest, key: str) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        if self.session_manager is None:
            return _http_error(503, "session manager unavailable")
        ns = derive_namespace_from_user_token(_user_token_from_request(request))
        if ns is None:
            return _http_error(401, "user token required")
        decoded_key = _decode_session_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        try:
            enforce_session_owner(self.session_manager, decoded_key, ns)
        except SessionNotAvailableError:
            return _http_error(404, "session not available")
        if not _is_websocket_channel_session_key(decoded_key):
            return _http_error(404, "session not found")
        query = _parse_query(request.path)
        delete_automations = (_query_first(query, "delete_automations") or "").lower()
        automation_jobs = session_automation_jobs(
            self.cron_service,
            decoded_key,
            local_trigger_store=self.local_trigger_store,
        )
        if automation_jobs and delete_automations not in {"1", "true", "yes"}:
            return _http_json_response(
                {
                    "deleted": False,
                    "blocked_by_automations": True,
                    "automations": serialize_automation_jobs(automation_jobs),
                }
            )
        if automation_jobs:
            for job in automation_jobs:
                if isinstance(job, LocalTrigger):
                    if self.local_trigger_store is not None:
                        self.local_trigger_store.delete(job.id)
                elif self.cron_service is not None:
                    self.cron_service.remove_job(job.id)
        deleted = self.session_manager.delete_session(decoded_key)
        delete_webui_thread(decoded_key)
        return _http_json_response({"deleted": bool(deleted)})

    # -- Automation routes --------------------------------------------------

    async def _dispatch_automation_routes(
        self,
        request: WsRequest,
        got: str,
    ) -> Response | None:
        if got == "/api/webui/automations":
            return self._handle_webui_automations(request)
        m = re.match(r"^/api/webui/automations/(enable|disable|delete|run|update)$", got)
        if m:
            return await self._handle_webui_automation_action(request, m.group(1))
        return None

    def _pending_cron_job_ids_for_all(self) -> set[str]:
        if self.cron_service is None or self.cron_pending_job_ids is None:
            return set()
        pending: set[str] = set()
        for job in self.cron_service.list_jobs(include_disabled=True):
            session_key = job.payload.session_key
            if not session_key and job.payload.origin_channel and job.payload.origin_chat_id:
                session_key = f"{job.payload.origin_channel}:{job.payload.origin_chat_id}"
            if session_key:
                pending.update(self.cron_pending_job_ids(session_key))
        return pending

    def _pending_local_trigger_ids_for_all(self) -> set[str]:
        if self.local_trigger_store is None or self.local_trigger_pending_ids is None:
            return set()
        pending: set[str] = set()
        for trigger in self.local_trigger_store.list_triggers(include_disabled=True):
            session_key = trigger.session_key
            if not session_key and trigger.channel and trigger.chat_id:
                session_key = f"{trigger.channel}:{trigger.chat_id}"
            if session_key:
                pending.update(self.local_trigger_pending_ids(session_key))
        return pending

    def _pending_automation_ids_for_session(self, session_key: str) -> set[str]:
        pending: set[str] = set()
        if self.cron_pending_job_ids is not None:
            pending.update(self.cron_pending_job_ids(session_key))
        if self.local_trigger_pending_ids is not None:
            pending.update(self.local_trigger_pending_ids(session_key))
        return pending

    def _handle_webui_automations(self, request: WsRequest) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        pending_job_ids = self._pending_cron_job_ids_for_all()
        pending_job_ids.update(self._pending_local_trigger_ids_for_all())
        return _http_json_response(
            all_automations_payload(
                self.cron_service,
                local_trigger_store=self.local_trigger_store,
                session_manager=self.session_manager,
                pending_job_ids=pending_job_ids,
            )
        )

    async def _handle_webui_automation_action(
        self,
        request: WsRequest,
        action: str,
    ) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        if self.cron_service is None and self.local_trigger_store is None:
            return _http_error(503, "automation service unavailable")

        query = _parse_query(request.path)
        job_id = (_query_first(query, "id") or _query_first(query, "job_id") or "").strip()
        if not job_id:
            return _http_error(400, "missing automation id")
        trigger = self.local_trigger_store.get(job_id) if self.local_trigger_store else None
        if trigger is not None:
            return self._handle_local_trigger_action(request, action, trigger)

        if self.cron_service is None:
            return _http_error(404, "automation not found")
        job = self.cron_service.get_job(job_id)
        if job is None:
            return _http_error(404, "automation not found")
        if job.payload.kind == "system_event":
            return _http_error(403, "system automation is protected")
        if action in {"enable", "run"} and not is_bound_cron_job(job):
            return _http_error(409, "automation has no linked chat")

        if action == "enable":
            if self.cron_service.enable_job(job_id, enabled=True) is None:
                return _http_error(404, "automation not found")
        elif action == "disable":
            if self.cron_service.enable_job(job_id, enabled=False) is None:
                return _http_error(404, "automation not found")
        elif action == "delete":
            result = self.cron_service.remove_job(job_id)
            if result == "not_found":
                return _http_error(404, "automation not found")
            if result == "protected":
                return _http_error(403, "system automation is protected")
        elif action == "run":
            if not job.enabled:
                return _http_error(409, "automation is disabled")
            task = asyncio.create_task(self.cron_service.run_job(job_id, force=False))
            task.add_done_callback(self._log_automation_run_result)
        elif action == "update":
            values = _automation_values_from_request(request)
            if values is None:
                return _http_error(400, "invalid automation update payload")
            parsed = _parse_automation_update(values, current_job=job)
            if isinstance(parsed, str):
                return _http_error(400, parsed)
            try:
                result = self.cron_service.update_job(job_id, **parsed)
            except ValueError as exc:
                return _http_error(400, str(exc))
            if result == "not_found":
                return _http_error(404, "automation not found")
            if result == "protected":
                return _http_error(403, "system automation is protected")
        else:
            return _http_error(404, "unknown automation action")

        return self._handle_webui_automations(request)

    def _handle_local_trigger_action(
        self,
        request: WsRequest,
        action: str,
        trigger: LocalTrigger,
    ) -> Response:
        if self.local_trigger_store is None:
            return _http_error(503, "trigger service unavailable")
        if action == "enable":
            if self.local_trigger_store.enable(trigger.id, enabled=True) is None:
                return _http_error(404, "automation not found")
        elif action == "disable":
            if self.local_trigger_store.enable(trigger.id, enabled=False) is None:
                return _http_error(404, "automation not found")
        elif action == "delete":
            if not self.local_trigger_store.delete(trigger.id):
                return _http_error(404, "automation not found")
        elif action == "run":
            return _http_error(409, "local trigger requires a CLI message")
        elif action == "update":
            values = _automation_values_from_request(request)
            if values is None:
                return _http_error(400, "invalid automation update payload")
            parsed = _parse_local_trigger_update(values)
            if isinstance(parsed, str):
                return _http_error(400, parsed)
            if parsed:
                if self.local_trigger_store.update(trigger.id, **parsed) is None:
                    return _http_error(404, "automation not found")
        else:
            return _http_error(404, "unknown automation action")

        return self._handle_webui_automations(request)

    @staticmethod
    def _log_automation_run_result(task: asyncio.Task[bool]) -> None:
        try:
            ran = task.result()
        except Exception:
            logger.exception("WebUI automation run-now task failed")
            return
        if not ran:
            logger.warning("WebUI automation run-now task did not execute")

    # -- Media routes -------------------------------------------------------

    def _dispatch_media_routes(self, request: WsRequest, got: str) -> Response | None:
        m = re.match(r"^/api/media/([A-Za-z0-9_-]+)/([A-Za-z0-9_-]+)$", got)
        if m:
            return self._handle_media_fetch(m.group(1), m.group(2), request)
        return None

    def _handle_media_fetch(
        self, sig: str, payload: str, request: WsRequest | None = None
    ) -> Response:
        return self.media.serve_signed_media(
            sig,
            payload,
            request=request,
        )

    # -- Misc routes --------------------------------------------------------

    async def _dispatch_misc_routes(
        self, connection: Any, request: WsRequest, got: str
    ) -> Response | None:
        if got == "/api/sessions":
            return await self._handle_sessions_list(request)
        if got == "/api/commands":
            return self._handle_commands(request)
        if got == "/api/workspaces":
            return self._handle_workspaces(connection, request)
        if got == "/api/webui/skills":
            return self._handle_webui_skills(request)
        m = re.match(r"^/api/webui/skills/([^/]+)$", got)
        if m:
            return self._handle_webui_skill_detail(request, m.group(1))
        if got == "/api/webui/sidebar-state":
            return self._handle_webui_sidebar_state(request)
        if got == "/api/webui/sidebar-state/update":
            return self._handle_webui_sidebar_state_update(request)
        return None

    def _handle_commands(self, request: WsRequest) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        return _http_json_response({"commands": builtin_command_palette()})

    def _handle_workspaces(self, connection: Any, request: WsRequest) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        return _http_json_response(
            self.workspaces.payload(
                controls_available=self.workspace_controls_available(connection)
            )
        )

    def _handle_webui_skills(self, request: WsRequest) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        return _http_json_response(
            webui_skills_payload(
                self.skills_workspace_path,
                disabled_skills=self.disabled_skills,
            )
        )

    def _handle_webui_skill_detail(self, request: WsRequest, raw_name: str) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        from urllib.parse import unquote

        name = unquote(raw_name)
        if not name or "/" in name or "\\" in name:
            return _http_error(400, "invalid skill name")
        payload = webui_skill_detail_payload(
            self.skills_workspace_path,
            name,
            disabled_skills=self.disabled_skills,
        )
        if payload is None:
            return _http_error(404, "skill not found")
        return _http_json_response(payload)

    def _handle_webui_sidebar_state(self, request: WsRequest) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        return _http_json_response(read_webui_sidebar_state())

    def _handle_webui_sidebar_state_update(self, request: WsRequest) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        query = _parse_query(request.path)
        raw_state = _query_first(query, "state")
        if raw_state is None:
            return _http_error(400, "missing state")
        try:
            decoded = json.loads(raw_state)
        except json.JSONDecodeError:
            return _http_error(400, "state must be JSON")
        if not isinstance(decoded, dict):
            return _http_error(400, "state must be an object")
        try:
            state = write_webui_sidebar_state(decoded)
        except ValueError as e:
            return _http_error(400, str(e))
        except OSError:
            self._log.exception("failed to write webui sidebar state")
            return _http_error(500, "failed to write sidebar state")
        return _http_json_response(state)

    # -- Static file serving ------------------------------------------------

    def _serve_static(self, request_path: str) -> Response | None:
        assert self.static_dist_path is not None
        rel = request_path.lstrip("/")
        if not rel:
            rel = "index.html"
        if ".." in rel.split("/") or rel.startswith("/"):
            return _http_error(403, "Forbidden")
        candidate = (self.static_dist_path / rel).resolve()
        try:
            candidate.relative_to(self.static_dist_path)
        except ValueError:
            return _http_error(403, "Forbidden")
        if not candidate.is_file():
            index = self.static_dist_path / "index.html"
            if index.is_file():
                candidate = index
            else:
                return None
        try:
            body = candidate.read_bytes()
        except OSError as e:
            self._log.warning("static: failed to read {}: {}", candidate, e)
            return _http_error(500, "Internal Server Error")
        ctype, _ = mimetypes.guess_type(candidate.name)
        if ctype is None:
            ctype = "application/octet-stream"
        if ctype.startswith("text/") or ctype in {"application/javascript", "application/json"}:
            ctype = f"{ctype}; charset=utf-8"
        if candidate.name == "index.html":
            cache = "no-cache"
        else:
            cache = "public, max-age=31536000, immutable"
        return _http_response(
            body,
            status=200,
            content_type=ctype,
            extra_headers=[("Cache-Control", cache)],
        )


def _automation_values_from_request(request: WsRequest) -> dict[str, Any] | None:
    raw = _case_insensitive_header(request.headers, _AUTOMATION_VALUES_HEADER)
    if not raw:
        return {}
    try:
        values = json.loads(raw)
    except Exception:
        try:
            values = json.loads(unquote(raw))
        except Exception:
            return None
    return values if isinstance(values, dict) else None


def _robot_body_from_request(request: WsRequest) -> Any | None:
    """Parse the JSON payload carried in the ``X-Nanobot-Robot-Body`` header.

    Returns the decoded object, or ``None`` when the header is missing or not
    valid JSON. A header value may be URL-encoded to dodge HTTP header
    character restrictions, so an encoded fallback is attempted.
    """
    raw = _case_insensitive_header(request.headers, _ROBOT_BODY_HEADER)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        try:
            return json.loads(unquote(raw))
        except Exception:
            return None


def _parse_automation_update(
    values: dict[str, Any],
    *,
    current_job: CronJob | None = None,
) -> dict[str, Any] | str:
    update: dict[str, Any] = {}
    if "name" in values:
        raw_name = values.get("name")
        if not isinstance(raw_name, str):
            return "name must be a string"
        name = raw_name.strip()
        if not name:
            return "name cannot be empty"
        update["name"] = name
    if "message" in values:
        raw_message = values.get("message")
        if not isinstance(raw_message, str):
            return "message must be a string"
        message = raw_message.strip()
        if not message:
            return "message cannot be empty"
        update["message"] = message
    if "schedule" in values:
        raw_schedule = values.get("schedule")
        if not isinstance(raw_schedule, dict):
            return "schedule must be an object"
        parsed_schedule = _parse_automation_schedule(raw_schedule)
        if isinstance(parsed_schedule, str):
            return parsed_schedule
        if current_job is not None and _schedule_matches_job(parsed_schedule, current_job):
            return update
        schedule_error = _validate_automation_schedule(parsed_schedule)
        if schedule_error:
            return schedule_error
        update["schedule"] = parsed_schedule
        update["delete_after_run"] = parsed_schedule.kind == "at"
    return update


def _parse_local_trigger_update(values: dict[str, Any]) -> dict[str, Any] | str:
    update: dict[str, Any] = {}
    if "name" in values:
        raw_name = values.get("name")
        if not isinstance(raw_name, str):
            return "name must be a string"
        name = raw_name.strip()
        if not name:
            return "name cannot be empty"
        update["name"] = name
    forbidden = [key for key in ("message", "schedule") if key in values]
    if forbidden:
        return "local trigger updates only support name"
    return update


def _parse_automation_schedule(values: dict[str, Any]) -> CronSchedule | str:
    raw_kind = values.get("kind")
    if not isinstance(raw_kind, str):
        return "schedule kind must be a string"
    kind = raw_kind.strip()
    if kind == "every":
        every_ms = _positive_int(values.get("every_ms"))
        if every_ms is None:
            return "every schedule requires positive every_ms"
        return CronSchedule(kind="every", every_ms=every_ms)
    if kind == "cron":
        raw_expr = values.get("expr")
        if not isinstance(raw_expr, str):
            return "cron schedule requires expr"
        expr = raw_expr.strip()
        if not expr:
            return "cron schedule requires expr"
        raw_tz = values.get("tz")
        if raw_tz is not None and not isinstance(raw_tz, str):
            return "cron schedule timezone must be a string"
        tz = raw_tz.strip() if isinstance(raw_tz, str) else ""
        return CronSchedule(kind="cron", expr=expr, tz=tz or None)
    if kind == "at":
        at_ms = _positive_int(values.get("at_ms"))
        if at_ms is None:
            return "one-time schedule requires positive at_ms"
        return CronSchedule(kind="at", at_ms=at_ms)
    return "unknown schedule kind"


def _schedule_matches_job(schedule: CronSchedule, job: CronJob) -> bool:
    current = job.schedule
    if schedule.kind != current.kind:
        return False
    if schedule.kind == "at":
        return schedule.at_ms == current.at_ms
    if schedule.kind == "every":
        return schedule.every_ms == current.every_ms
    if schedule.kind == "cron":
        return (schedule.expr or "") == (current.expr or "") and (
            schedule.tz or None
        ) == (current.tz or None)
    return False


def _validate_automation_schedule(schedule: CronSchedule) -> str | None:
    if schedule.kind == "at":
        if not schedule.at_ms or schedule.at_ms <= int(time.time() * 1000):
            return "one-time schedule must be in the future"
        return None
    if schedule.kind != "cron":
        return None

    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from croniter import croniter

        tz = ZoneInfo(schedule.tz) if schedule.tz else datetime.now().astimezone().tzinfo
        base = datetime.now(tz=tz)
        croniter(schedule.expr, base).get_next(datetime)
    except Exception:
        return "cron schedule is invalid"
    return None


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None


def _is_websocket_channel_session_key(key: str) -> bool:
    return key.startswith("websocket:")
