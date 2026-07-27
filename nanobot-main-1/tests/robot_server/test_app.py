from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from robot_platform.library.auth import hash_password
from robot_platform.library.users import UserRegistry, initialize_user_identity
from robot_platform.runtime import get_robot_data_dir, reset_robot_runtime_for_tests
from robot_server.app import LOCAL_MEDIA_SERVICE_KEY, RobotServerConfig, create_robot_server_app
from robot_server.cli import bundled_webui_dist
from robot_server.identity_api import RobotIdentityService
from robot_server.media_api import LocalMediaService
from robot_server.webui_compat import _load_voice_config, _transcription_frame
from ai_runtime.engine_contract import AgentEvent


class _FakeRuntime:
    def __init__(self) -> None:
        self.requests = []
        self.cancelled = []
        self._queues: set[asyncio.Queue] = set()

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def submit(self, request) -> None:
        self.requests.append(request)

    async def cancel(self, session_id: str) -> int:
        self.cancelled.append(session_id)
        return 1

    async def check_ai_connectivity(self) -> None:
        return None

    async def subscribe(self):
        queue: asyncio.Queue = asyncio.Queue()
        self._queues.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._queues.discard(queue)

    async def emit(self, event: AgentEvent) -> None:
        for queue in tuple(self._queues):
            await queue.put(event)


def test_identity_recovers_enabled_legacy_users_from_seeded_placeholders(tmp_path) -> None:
    runtime_root = tmp_path / "runtime"
    legacy_dir = runtime_root / "robot_ai"
    platform_dir = runtime_root / "robot_platform"
    legacy = UserRegistry(legacy_dir / "users.json", audit_path=legacy_dir / "audit.jsonl")
    legacy.create("admin", "engineer", hash_password("legacy-password"), enabled=True)
    placeholder = UserRegistry(platform_dir / "users.json", audit_path=platform_dir / "audit.jsonl")
    placeholder.create("admin", "engineer", "unusable-placeholder", enabled=False)

    service = RobotIdentityService(platform_dir)
    status, result = service.login(
        {"username": "admin", "password": "legacy-password", "role": "engineer"},
        client_key="test",
    )

    assert status == 200
    assert result["ok"] is True
    assert (platform_dir / "users.pre-legacy-recovery.json").is_file()


def test_source_checkout_locates_production_webui_bundle() -> None:
    dist = bundled_webui_dist()

    assert dist is not None
    assert (dist / "index.html").is_file()
    assert any((dist / "assets").glob("*.js"))
    index = (dist / "index.html").read_text(encoding="utf-8")
    assert "机械手智能控制平台" in index
    assert "nanobot web UI" not in index


def test_retained_webui_pages_have_a_complete_robot_server_route_contract() -> None:
    """Keep every retained WebUI page on the direct local-server surface.

    The React application intentionally keeps its existing pages (sessions,
    settings, automation, library and engineer workbench).  This contract is
    deliberately broader than a single end-to-end smoke test: removing one
    compatibility route must fail here instead of leaving a navigation item
    that opens to a 404 in the desktop app.
    """

    app = create_robot_server_app(platform=MagicMock())
    registered = {
        (route.method, route.resource.canonical)
        for route in app.router.routes()
        if route.method != "HEAD"
    }
    expected = {
        # Login and the retained WebSocket conversation UI.
        ("GET", "/webui/bootstrap"), ("GET", "/webui"),
        ("GET", "/api/auth/login"), ("GET", "/api/auth/logout"),
        ("GET", "/api/login/preflight"),
        # Sessions, history, attachments and sidebar state.
        ("GET", "/api/sessions"),
        ("GET", "/api/sessions/{key}/webui-thread"),
        ("GET", "/api/sessions/{key}/file-preview"),
        ("POST", "/api/sessions/{key}/delete"),
        ("GET", "/api/sessions/{key}/automations"),
        ("GET", "/api/webui/sidebar-state"),
        ("POST", "/api/webui/sidebar-state"),
        ("GET", "/api/webui/sidebar-state/update"),
        ("GET", "/api/webui/skills"),
        ("GET", "/api/webui/skills/{name}"),
        ("GET", "/api/workspaces"), ("GET", "/api/commands"),
        ("GET", "/api/media/{signature}/{payload}"),
        # Automation and the retained non-AI settings screen.
        ("GET", "/api/webui/automations"),
        ("GET", "/api/webui/automations/enable"),
        ("GET", "/api/webui/automations/disable"),
        ("GET", "/api/webui/automations/delete"),
        ("GET", "/api/webui/automations/run"),
        ("GET", "/api/webui/automations/update"),
        ("GET", "/api/settings"), ("GET", "/api/settings/usage"),
        ("GET", "/api/settings/version-check"),
        ("GET", "/api/settings/web-search/update"),
        ("GET", "/api/settings/network-safety/update"),
        ("GET", "/api/settings/image-generation/update"),
        ("GET", "/api/settings/transcription/update"),
        ("GET", "/api/settings/cli-apps"),
        ("GET", "/api/settings/cli-apps/install"),
        ("GET", "/api/settings/cli-apps/update"),
        ("GET", "/api/settings/cli-apps/uninstall"),
        ("GET", "/api/settings/cli-apps/test"),
        ("GET", "/api/settings/mcp-presets"),
        ("GET", "/api/settings/mcp-presets/enable"),
        ("GET", "/api/settings/mcp-presets/remove"),
        ("GET", "/api/settings/mcp-presets/test"),
        ("GET", "/api/settings/mcp-presets/custom"),
        ("GET", "/api/settings/mcp-presets/import"),
        ("GET", "/api/settings/mcp-presets/tools"),
        # Robot operation, published library and engineer workbench.
        ("GET", "/api/robot/status"), ("POST", "/api/robot/plans"),
        ("POST", "/api/robot/plans/{plan_id}/confirm"),
        ("POST", "/api/robot/plans/{plan_id}/execute"),
        ("POST", "/api/robot/flow-pending-plan"),
        ("POST", "/api/robot/flow-confirm"),
        ("POST", "/api/robot/flow-execute"),
        ("POST", "/api/robot/emergency-stop"),
        ("POST", "/api/robot/flows/run"),
        ("GET", "/api/library/components"),
        ("GET", "/api/library/components/{component_id}"),
        ("GET", "/api/library/commands"),
        ("GET", "/api/library/commands/{command_id}"),
        ("POST", "/api/library/commands/{command_id}/executions"),
        ("GET", "/api/library/flows"),
        ("GET", "/api/library/flows/{flow_id}"),
        ("POST", "/api/library/flows/{flow_id}/executions"),
        ("GET", "/api/library/executions"),
        ("GET", "/api/library/executions/{execution_id}"),
        ("POST", "/api/library/executions/{execution_id}/control"),
        ("GET", "/api/identity/users"), ("POST", "/api/identity/users"),
        ("PATCH", "/api/identity/users/{user_id}"),
        ("POST", "/api/identity/users/{user_id}/password"),
        ("GET", "/api/management/commands"),
        ("POST", "/api/management/commands"),
        ("GET", "/api/management/commands/{command_id}"),
        ("PUT", "/api/management/commands/{command_id}/draft"),
        ("POST", "/api/management/commands/{command_id}/draft"),
        ("POST", "/api/management/commands/{command_id}/publish"),
        ("POST", "/api/management/commands/{command_id}/archive"),
        ("POST", "/api/management/commands/{command_id}/duplicate"),
        ("POST", "/api/management/commands/bulk-archive"),
        ("GET", "/api/management/flows"),
        ("POST", "/api/management/flows"),
        ("GET", "/api/management/flows/{flow_id}"),
        ("PUT", "/api/management/flows/{flow_id}/draft"),
        ("POST", "/api/management/flows/{flow_id}/draft"),
        ("POST", "/api/management/flows/{flow_id}/validate"),
        ("POST", "/api/management/flows/{flow_id}/publish"),
        ("POST", "/api/management/flows/{flow_id}/archive"),
        ("POST", "/api/management/flows/{flow_id}/duplicate"),
        ("POST", "/api/management/flows/bulk-archive"),
        ("GET", "/api/management/diagnostics"),
        ("GET", "/api/management/audit"),
        ("GET", "/api/management/library/export"),
        ("POST", "/api/management/library/import"),
    }

    assert expected <= registered
    removed_ai_settings_routes = {
        ("GET", "/api/settings/update"),
        ("GET", "/api/settings/model-configurations/create"),
        ("GET", "/api/settings/model-configurations/update"),
        ("GET", "/api/settings/provider/update"),
        ("GET", "/api/settings/provider-models"),
        ("GET", "/api/settings/provider/oauth-login"),
        ("GET", "/api/settings/provider/oauth-logout"),
    }
    assert registered.isdisjoint(removed_ai_settings_routes)


@pytest.fixture
async def aiohttp_client():
    clients: list[TestClient] = []

    async def create(app):
        client = TestClient(TestServer(app))
        await client.start_server()
        clients.append(client)
        return client

    yield create
    for client in clients:
        await client.close()


@pytest.mark.asyncio
async def test_health_is_available_without_authentication(aiohttp_client) -> None:
    platform = MagicMock()
    app = create_robot_server_app(
        platform=platform,
        config=RobotServerConfig(access_token="local-secret"),
    )
    client = await aiohttp_client(app)

    response = await client.get("/health")

    assert response.status == 200
    assert await response.json() == {"status": "ok", "service": "robot-server"}


@pytest.mark.asyncio
async def test_webui_bootstrap_advertises_the_compatible_protocol_version(aiohttp_client) -> None:
    client = await aiohttp_client(create_robot_server_app(platform=MagicMock()))

    response = await client.get("/webui/bootstrap")

    assert response.status == 200
    assert (await response.json())["protocol_version"] == 1


def test_server_composition_does_not_create_identity_data_before_first_login(tmp_path) -> None:
    create_robot_server_app(
        platform=MagicMock(), config=RobotServerConfig(robot_data_dir=tmp_path)
    )

    assert not (tmp_path / "users.json").exists()


def test_server_configures_platform_runtime_data_dir_before_constructing_default_platform(tmp_path) -> None:
    try:
        create_robot_server_app(config=RobotServerConfig(robot_data_dir=tmp_path))

        assert get_robot_data_dir() == tmp_path
    finally:
        reset_robot_runtime_for_tests()


@pytest.mark.asyncio
async def test_robot_single_page_is_served_by_robot_server(aiohttp_client) -> None:
    app = create_robot_server_app(
        platform=MagicMock(),
        config=RobotServerConfig(static_dist_path=bundled_webui_dist()),
    )
    client = await aiohttp_client(app)

    response = await client.get("/")
    page = await response.text()
    entry = re.search(r'src="(/assets/index-[^"]+\.js)"', page)

    assert response.status == 200
    assert "机械手智能控制平台" in page
    assert entry is not None
    script = await client.get(entry.group(1))
    assert script.status == 200


@pytest.mark.asyncio
async def test_bootstrap_and_status_require_configured_token(aiohttp_client) -> None:
    platform = MagicMock()
    platform.get_status.return_value = {"ok": True, "data": {"mode": "simulation"}}
    app = create_robot_server_app(
        platform=platform,
        config=RobotServerConfig(access_token="local-secret"),
    )
    client = await aiohttp_client(app)

    assert (await client.get("/api/bootstrap")).status == 401
    headers = {"Authorization": "Bearer local-secret"}
    bootstrap = await client.get("/api/bootstrap", headers=headers)
    status = await client.get("/api/robot/status", headers=headers)

    assert (await bootstrap.json())["auth_required"] is True
    assert await status.json() == {"ok": True, "data": {"mode": "simulation"}}
    platform.get_status.assert_called_once_with()


@pytest.mark.asyncio
async def test_robot_status_exposes_versioned_vendor_neutral_capabilities(aiohttp_client) -> None:
    platform = MagicMock()
    platform.get_status.return_value = {
        "ok": True,
        "data": {
            "controller_capabilities": {
                "vendor": "simulation",
                "supports_state_read": True,
                "supports_real_writes": False,
                "motion_primitives": ["axis_move", "home", "stop"],
            }
        },
    }
    client = await aiohttp_client(create_robot_server_app(platform=platform))

    response = await client.get("/api/robot/status")
    payload = await response.json()
    expected = json.loads(
        (Path(__file__).parent / "fixtures" / "capabilities-v1.json").read_text(encoding="utf-8")
    )

    assert response.status == 200
    assert payload["data"]["capabilities"] == expected
    assert payload["data"]["controller_capabilities"]["vendor"] == "simulation"


@pytest.mark.asyncio
async def test_status_does_not_expose_controller_exception(aiohttp_client) -> None:
    platform = MagicMock()
    platform.get_status.side_effect = RuntimeError("controller password should not leak")
    client = await aiohttp_client(create_robot_server_app(platform=platform))

    response = await client.get("/api/robot/status")

    assert response.status == 503
    assert await response.json() == {"error": "robot status unavailable"}


@pytest.mark.asyncio
async def test_engineer_diagnostics_are_read_only_and_engineer_scoped(aiohttp_client, tmp_path) -> None:
    platform = MagicMock()
    platform.get_status.return_value = {"ok": True, "data": {"robot_state": {
        "mode": "idle", "axes_mm": {"x": 12.5}, "alarms": [], "connected_real_device": True,
    }}}
    initialize_user_identity(users_path=tmp_path / "users.json", audit_path=tmp_path / "audit.jsonl")
    registry = UserRegistry(tmp_path / "users.json", audit_path=tmp_path / "audit.jsonl")
    admin = registry.get_by_username("admin")
    assert admin is not None
    registry.bootstrap_set_password(admin["user_id"], hash_password("test-password", iterations=100_000))
    client = await aiohttp_client(create_robot_server_app(
        platform=platform, config=RobotServerConfig(robot_data_dir=tmp_path)
    ))
    blocked = await client.get("/api/management/diagnostics")
    login = await client.post(
        "/api/identity/login",
        json={"username": "admin", "password": "test-password", "role": "engineer"},
    )
    token = (await login.json())["data"]["user_token"]
    response = await client.get("/api/management/diagnostics", headers={"X-Robot-User-Token": token})

    assert blocked.status == 401
    assert response.status == 200
    assert await response.json() == {"ok": True, "data": {
        "connection": {"mode": "idle", "real_device": True},
        "execution_mode": "dry_run_only",
        "position": {"x": 12.5}, "io": {}, "alarms": [], "task": "idle", "command_echo": {},
    }}


@pytest.mark.asyncio
async def test_product_profile_is_engineer_only_and_does_not_return_ai_configuration(aiohttp_client, tmp_path) -> None:
    initialize_user_identity(users_path=tmp_path / "users.json", audit_path=tmp_path / "audit.jsonl")
    registry = UserRegistry(tmp_path / "users.json", audit_path=tmp_path / "audit.jsonl")
    admin = registry.get_by_username("admin")
    assert admin is not None
    registry.bootstrap_set_password(admin["user_id"], hash_password("test-password", iterations=100_000))
    client = await aiohttp_client(create_robot_server_app(config=RobotServerConfig(robot_data_dir=tmp_path)))

    blocked = await client.get("/api/management/product-profile")
    login = await client.post(
        "/api/identity/login",
        json={"username": "admin", "password": "test-password", "role": "engineer"},
    )
    token = (await login.json())["data"]["user_token"]
    response = await client.get("/api/management/product-profile", headers={"X-Robot-User-Token": token})

    assert blocked.status == 401
    assert response.status == 200
    payload = await response.json()
    assert payload["data"]["backend_mode"] == "simulation"
    assert "provider" not in str(payload["data"]).lower()
    assert "model" not in str(payload["data"]).lower()


@pytest.mark.asyncio
async def test_login_preflight_checks_the_local_ai_runtime(aiohttp_client) -> None:
    platform = MagicMock()
    platform.get_status.return_value = {
        "ok": True,
        "data": {"robot_state": {"mode": "idle", "connected_real_device": True}},
    }
    runtime = _FakeRuntime()
    client = await aiohttp_client(create_robot_server_app(
        platform=platform,
        config=RobotServerConfig(
            agent_runtime=runtime,
            controller_probe=lambda _host: {"mode": "idle", "connected_real_device": True},
        ),
    ))

    response = await client.get(
        "/api/login/preflight",
        headers={"X-Nanobot-Robot-Body": json.dumps({"controller_host": "127.0.0.1"})},
    )

    assert response.status == 200
    body = await response.json()
    assert body["ok"] is True
    assert body["data"]["controller"]["state"] == "healthy"
    assert body["data"]["ai"]["state"] == "healthy"
    assert body["data"]["voice"]["state"] == "unhealthy"


@pytest.mark.asyncio
async def test_login_preflight_probes_the_requested_controller_host(aiohttp_client) -> None:
    """The address entered in the login page must be the address probed.

    It is a diagnostic-only probe: it must not reconfigure the running robot
    backend or issue a controller write.
    """
    requested_hosts: list[str] = []

    def controller_probe(host: str) -> dict[str, object]:
        requested_hosts.append(host)
        return {"mode": "idle", "connected_real_device": host == "10.20.30.40"}

    client = await aiohttp_client(create_robot_server_app(
        platform=MagicMock(),
        config=RobotServerConfig(agent_runtime=_FakeRuntime(), controller_probe=controller_probe),
    ))

    response = await client.get(
        "/api/login/preflight",
        headers={"X-Nanobot-Robot-Body": json.dumps({"controller_host": "10.20.30.40"})},
    )

    assert response.status == 200
    controller = (await response.json())["data"]["controller"]
    assert requested_hosts == ["10.20.30.40"]
    assert controller["state"] == "healthy"
    assert controller["host"] == "10.20.30.40"


@pytest.mark.asyncio
async def test_login_preflight_uses_the_deployment_config_for_voice(aiohttp_client, monkeypatch, tmp_path) -> None:
    platform = MagicMock()
    platform.get_status.return_value = {
        "ok": True,
        "data": {"robot_state": {"mode": "idle", "connected_real_device": True}},
    }
    deployment_config_path = tmp_path / "deployment-config.json"
    loaded_paths: list[Path | None] = []
    probed_keys: list[str] = []

    def fake_load_config(path: Path | None = None):
        loaded_paths.append(path)
        return SimpleNamespace(
            providers=SimpleNamespace(dashscope=SimpleNamespace(api_key="deployment-voice-key")),
        )

    async def fake_probe(api_key: str) -> None:
        probed_keys.append(api_key)

    monkeypatch.setattr("robot_server.app.load_config", fake_load_config)
    monkeypatch.setattr("robot_server.app.probe_bailian_realtime_asr", fake_probe)
    client = await aiohttp_client(create_robot_server_app(
        platform=platform,
        config=RobotServerConfig(
            agent_runtime=_FakeRuntime(),
            deployment_config_path=deployment_config_path,
            controller_probe=lambda _host: {"mode": "idle", "connected_real_device": True},
        ),
    ))

    response = await client.get(
        "/api/login/preflight",
        headers={"X-Nanobot-Robot-Body": json.dumps({"controller_host": "127.0.0.1"})},
    )

    assert response.status == 200
    assert (await response.json())["data"]["voice"] == {
        "state": "healthy", "latency_ms": pytest.approx(0, abs=100), "provider": "bailian-realtime-asr",
    }
    assert loaded_paths == [deployment_config_path]
    assert probed_keys == ["deployment-voice-key"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("robot_state", "reason"),
    [
        ({"mode": "disconnected", "connected_real_device": False}, "lower_machine_not_connected"),
        ({"mode": "simulation", "connected_real_device": False}, "simulation_mode"),
    ],
)
async def test_login_preflight_requires_a_real_lower_machine_connection(
    aiohttp_client, robot_state, reason: str,
) -> None:
    platform = MagicMock()
    platform.get_status.return_value = {"ok": True, "data": {"robot_state": robot_state}}
    client = await aiohttp_client(create_robot_server_app(
        platform=platform,
        config=RobotServerConfig(controller_probe=lambda _host: robot_state),
    ))

    response = await client.get(
        "/api/login/preflight",
        headers={"X-Nanobot-Robot-Body": json.dumps({"controller_host": "127.0.0.1"})},
    )

    assert response.status == 200
    controller = (await response.json())["data"]["controller"]
    assert controller["state"] == "unhealthy"
    assert controller["reason"] == reason


@pytest.mark.asyncio
async def test_settings_and_usage_are_available_without_exposing_ai_configuration(aiohttp_client) -> None:
    client = await aiohttp_client(create_robot_server_app(platform=MagicMock()))

    settings = await client.get("/api/settings")
    usage = await client.get("/api/settings/usage")

    assert settings.status == 200
    payload = await settings.json()
    assert payload["runtime_surface"] == "native"
    assert payload["agent"] == {
        "configured": True,
        "bot_name": payload["agent"]["bot_name"],
        "bot_icon": payload["agent"]["bot_icon"],
        "tool_hint_max_length": payload["agent"]["tool_hint_max_length"],
    }
    assert payload["providers"] == []
    assert payload["model_presets"] == []
    assert usage.status == 200
    assert await usage.json() == {
        "days": [], "total_tokens": 0, "total_tokens_30d": 0,
        "total_tokens_365d": 0, "peak_day_tokens": 0,
        "current_streak_days": 0, "longest_streak_days": 0,
        "active_days_30d": 0, "requests_30d": 0, "updated_at": None,
    }


@pytest.mark.asyncio
async def test_direct_settings_apps_endpoints_preserve_webui_catalogs(aiohttp_client) -> None:
    client = await aiohttp_client(create_robot_server_app(platform=MagicMock()))

    mcp = await client.get("/api/settings/mcp-presets")
    automations = await client.get("/api/webui/automations")

    assert mcp.status == 200
    mcp_payload = await mcp.json()
    assert set(mcp_payload) >= {"presets", "installed_count"}
    assert {item["name"] for item in mcp_payload["presets"]} >= {
        "playwright", "github", "figma", "supabase"
    }
    assert automations.status == 200
    assert (await automations.json()) == {"jobs": []}


@pytest.mark.asyncio
async def test_webui_voice_frame_returns_legacy_transcription_error_shape() -> None:
    frame = await _transcription_frame({
        "type": "transcribe_audio", "request_id": "voice-1", "data_url": "data:audio/webm;base64,AA==",
    })

    assert frame["event"] == "transcription_error"
    assert frame["request_id"] == "voice-1"
    assert frame["detail"] in {"not_configured", "disabled", "decode"}


def test_webui_voice_config_uses_server_deployment_config(monkeypatch) -> None:
    deployment_config = Path("C:/controlled-runtime/deployment-config.json")
    loaded_paths: list[Path | None] = []
    sentinel = object()

    def fake_load_config(path: Path | None = None):
        loaded_paths.append(path)
        return sentinel

    monkeypatch.setattr("robot_server.webui_compat.load_config", fake_load_config)

    assert _load_voice_config(deployment_config) is sentinel
    assert loaded_paths == [deployment_config]


@pytest.mark.asyncio
async def test_file_preview_rejects_missing_or_out_of_workspace_paths(aiohttp_client) -> None:
    client = await aiohttp_client(create_robot_server_app(platform=MagicMock()))

    missing = await client.get("/api/sessions/anything/file-preview")
    outside = await client.get("/api/sessions/anything/file-preview?path=C%3A%2FWindows%2Fwin.ini")

    assert missing.status == 400
    assert outside.status in {403, 404}


@pytest.mark.asyncio
async def test_signed_media_is_rooted_in_local_media_directory(aiohttp_client, tmp_path, monkeypatch) -> None:
    media_root = tmp_path / "media"; media_root.mkdir()
    image = media_root / "status.png"; image.write_bytes(b"png")
    monkeypatch.setattr("robot_server.media_api.get_media_dir", lambda: media_root)
    service = LocalMediaService()
    url = service.sign(image)
    app = create_robot_server_app(platform=MagicMock())
    app[LOCAL_MEDIA_SERVICE_KEY] = service
    client = await aiohttp_client(app)

    response = await client.get(url or "/api/media/no/no")
    assert response.status == 200
    assert response.headers["Content-Type"] == "image/png"
    assert await response.read() == b"png"


@pytest.mark.asyncio
async def test_robot_library_read_routes_only_expose_published_records(aiohttp_client, tmp_path) -> None:
    client = await aiohttp_client(create_robot_server_app(
        platform=MagicMock(), config=RobotServerConfig(robot_data_dir=tmp_path)
    ))

    components = await client.get("/api/library/components")
    commands = await client.get("/api/library/commands")
    unknown = await client.get("/api/library/commands/not-a-command")
    invalid_risk = await client.get("/api/library/commands?risk_level=unsafe")
    flows = await client.get("/api/library/flows")

    component_items = (await components.json())["data"]["items"]
    command_items = (await commands.json())["data"]["items"]
    assert components.status == 200
    assert {item["id"] for item in component_items} >= {"linear_move", "system_action"}
    assert commands.status == 200
    assert command_items
    assert all(item["status"] == "published" for item in command_items)
    assert unknown.status == 404
    assert invalid_risk.status == 400
    assert flows.status == 200


@pytest.mark.asyncio
async def test_identity_uses_local_user_token_and_revokes_it_on_logout(aiohttp_client, tmp_path) -> None:
    initialize_user_identity(
        users_path=tmp_path / "users.json", audit_path=tmp_path / "audit.jsonl"
    )
    app = create_robot_server_app(
        platform=MagicMock(), config=RobotServerConfig(robot_data_dir=tmp_path)
    )
    admin = UserRegistry(tmp_path / "users.json", audit_path=tmp_path / "audit.jsonl").get_by_username("admin")
    assert admin is not None
    UserRegistry(tmp_path / "users.json", audit_path=tmp_path / "audit.jsonl").bootstrap_set_password(
        admin["user_id"], hash_password("test-password", iterations=100_000)
    )
    client = await aiohttp_client(app)

    login = await client.post(
        "/api/identity/login",
        json={"username": "admin", "password": "test-password", "role": "engineer"},
    )
    payload = await login.json()
    token = payload["data"]["user_token"]
    headers = {"X-Robot-User-Token": token}
    me = await client.get("/api/identity/me", headers=headers)
    create_operator = await client.post(
        "/api/identity/users",
        headers=headers,
        json={"username": "operator-a", "role": "operator", "password": "operator-password"},
    )
    operator_id = (await create_operator.json())["data"]["user_id"]
    users = await client.get("/api/identity/users", headers=headers)
    self_reset = await client.post(
        f"/api/identity/users/{admin['user_id']}/password",
        headers=headers,
        json={"new_password": "not-used"},
    )
    reset_operator = await client.post(
        f"/api/identity/users/{operator_id}/password",
        headers=headers,
        json={"new_password": "new-operator-password"},
    )
    logout = await client.post("/api/identity/logout", headers=headers)
    revoked = await client.get("/api/identity/me", headers=headers)

    assert login.status == 200
    assert payload["data"]["user"] == {
        "user_id": admin["user_id"], "username": "admin", "role": "engineer"
    }
    assert (await me.json())["data"]["user"]["username"] == "admin"
    assert create_operator.status == 201
    assert {item["username"] for item in (await users.json())["data"]["users"]} >= {
        "admin", "operator", "operator-a"
    }
    assert self_reset.status == 409
    assert reset_operator.status == 200
    assert logout.status == 200
    assert revoked.status == 401


@pytest.mark.asyncio
async def test_engineer_command_publish_is_versioned_and_then_visible_to_operators(aiohttp_client, tmp_path) -> None:
    initialize_user_identity(
        users_path=tmp_path / "users.json", audit_path=tmp_path / "audit.jsonl"
    )
    registry = UserRegistry(tmp_path / "users.json", audit_path=tmp_path / "audit.jsonl")
    admin = registry.get_by_username("admin")
    assert admin is not None
    registry.bootstrap_set_password(admin["user_id"], hash_password("test-password", iterations=100_000))
    client = await aiohttp_client(create_robot_server_app(
        platform=MagicMock(), config=RobotServerConfig(robot_data_dir=tmp_path)
    ))
    blocked = await client.get("/api/management/commands")
    login = await client.post(
        "/api/identity/login",
        json={"username": "admin", "password": "test-password", "role": "engineer"},
    )
    token = (await login.json())["data"]["user_token"]
    headers = {"X-Robot-User-Token": token}

    created = await client.post(
        "/api/management/commands",
        headers=headers,
        json={
            "name": "工程师测试延时",
            "component_id": "delay",
            "parameters": {"delay_sec": 1.0},
        },
    )
    command_id = (await created.json())["data"]["command_id"]
    published = await client.post(
        f"/api/management/commands/{command_id}/publish", headers=headers
    )
    public = await client.get(f"/api/library/commands/{command_id}")
    audit = await client.get("/api/management/audit?limit=100", headers=headers)
    exported = await client.get("/api/management/library/export", headers=headers)
    invalid_import = await client.post(
        "/api/management/library/import",
        headers=headers,
        json={"payload": {"schema_version": 2, "commands": [], "flows": []}},
    )
    duplicate = await client.post(
        f"/api/management/commands/{command_id}/duplicate",
        headers=headers,
        json={"name": "工程师测试延时副本"},
    )
    duplicate_id = (await duplicate.json())["data"]["command_id"]
    bulk_archive = await client.post(
        "/api/management/commands/bulk-archive",
        headers=headers,
        json={"ids": [duplicate_id, command_id]},
    )

    assert blocked.status == 401
    assert created.status == 201
    assert published.status == 200
    assert (await published.json())["data"]["published_version"] == 1
    assert public.status == 200
    assert (await public.json())["data"]["status"] == "published"
    assert audit.status == 200
    assert "command_publish" in {entry["action"] for entry in (await audit.json())["data"]["items"]}
    assert exported.status == 200
    assert command_id in {item["command_id"] for item in (await exported.json())["data"]["commands"]}
    assert invalid_import.status == 400
    assert duplicate.status == 201
    assert (await bulk_archive.json())["data"] == {
        "archived": [duplicate_id], "failed": [{"id": command_id, "code": "archive_blocked"}]
    }


@pytest.mark.asyncio
async def test_engineer_flow_publish_validates_and_projects_to_operator_library(aiohttp_client, tmp_path) -> None:
    initialize_user_identity(
        users_path=tmp_path / "users.json", audit_path=tmp_path / "audit.jsonl"
    )
    registry = UserRegistry(tmp_path / "users.json", audit_path=tmp_path / "audit.jsonl")
    admin = registry.get_by_username("admin")
    assert admin is not None
    registry.bootstrap_set_password(admin["user_id"], hash_password("test-password", iterations=100_000))
    client = await aiohttp_client(create_robot_server_app(
        platform=MagicMock(), config=RobotServerConfig(robot_data_dir=tmp_path)
    ))
    login = await client.post(
        "/api/identity/login",
        json={"username": "admin", "password": "test-password", "role": "engineer"},
    )
    headers = {"X-Robot-User-Token": (await login.json())["data"]["user_token"]}
    created = await client.post(
        "/api/management/flows",
        headers=headers,
        json={
            "name": "工程师测试流程",
            "steps": [{"step_id": 1, "action": "delay", "func_id": 110, "params": {"delay_sec": 1.0}}],
        },
    )
    flow_id = (await created.json())["data"]["flow_id"]
    validation = await client.post(f"/api/management/flows/{flow_id}/validate", headers=headers)
    published = await client.post(f"/api/management/flows/{flow_id}/publish", headers=headers)
    public = await client.get(f"/api/library/flows/{flow_id}")

    assert created.status == 201
    assert await validation.json() == {"ok": True, "data": {"errors": []}}
    assert published.status == 200
    assert public.status == 200
    assert (await public.json())["data"]["name"] == "工程师测试流程"


@pytest.mark.asyncio
async def test_position_cleanup_preserves_published_references_and_requires_apply(aiohttp_client, tmp_path) -> None:
    initialize_user_identity(
        users_path=tmp_path / "users.json", audit_path=tmp_path / "audit.jsonl"
    )
    registry = UserRegistry(tmp_path / "users.json", audit_path=tmp_path / "audit.jsonl")
    admin = registry.get_by_username("admin")
    assert admin is not None
    registry.bootstrap_set_password(admin["user_id"], hash_password("test-password", iterations=100_000))
    (tmp_path / "positions.json").write_text(json.dumps({"version": "1.0", "positions": [
        {"name": "home"}, {"name": "flowdraft:published"},
        {"name": "agent:draft-only"}, {"name": "ai_first:orphan"},
    ]}), encoding="utf-8")
    (tmp_path / "commands.json").write_text(json.dumps({"schema_version": "2.0", "commands": {
        "published": {"published_version": 1, "versions": {"1": {
            "parameters": {"target": "flowdraft:published"}
        }}, "draft": {"parameters": {"target": "agent:draft-only"}}}
    }}), encoding="utf-8")
    client = await aiohttp_client(create_robot_server_app(
        platform=MagicMock(), config=RobotServerConfig(robot_data_dir=tmp_path)
    ))
    login = await client.post(
        "/api/identity/login",
        json={"username": "admin", "password": "test-password", "role": "engineer"},
    )
    headers = {"X-Robot-User-Token": (await login.json())["data"]["user_token"]}

    preview = await client.get("/api/management/positions/cleanup-preview", headers=headers)
    invalid = await client.post("/api/management/positions/cleanup", headers=headers, json={})
    applied = await client.post(
        "/api/management/positions/cleanup", headers=headers, json={"action": "apply"}
    )

    preview_data = (await preview.json())["data"]
    apply_data = (await applied.json())["data"]
    assert preview.status == 200
    assert preview_data["candidate_names"] == ["agent:draft-only", "ai_first:orphan"]
    assert preview_data["preserved_referenced_names"] == ["flowdraft:published"]
    assert invalid.status == 400
    assert applied.status == 200
    assert apply_data["removed_names"] == ["agent:draft-only", "ai_first:orphan"]
    assert apply_data["backup_path"]
    assert [entry["name"] for entry in json.loads((tmp_path / "positions.json").read_text(encoding="utf-8"))["positions"]] == [
        "home", "flowdraft:published"
    ]


@pytest.mark.asyncio
async def test_published_library_execution_is_tracked_and_requires_confirmation_for_real_run(aiohttp_client, tmp_path) -> None:
    initialize_user_identity(
        users_path=tmp_path / "users.json", audit_path=tmp_path / "audit.jsonl"
    )
    registry = UserRegistry(tmp_path / "users.json", audit_path=tmp_path / "audit.jsonl")
    admin = registry.get_by_username("admin")
    assert admin is not None
    registry.bootstrap_set_password(admin["user_id"], hash_password("test-password", iterations=100_000))
    (tmp_path / "commands.json").write_text(json.dumps({"schema_version": "2.0", "commands": {
        "wait": {"published_version": 1, "versions": {"1": {
            "id": "wait", "name": "Wait", "component_id": "delay", "parameters": {"delay_sec": 0.0}
        }}}
    }}), encoding="utf-8")
    platform = MagicMock()
    platform.run_flow_entry.return_value = {"ok": True, "state": "flow_completed"}
    client = await aiohttp_client(create_robot_server_app(
        platform=platform, config=RobotServerConfig(robot_data_dir=tmp_path)
    ))
    login = await client.post(
        "/api/identity/login",
        json={"username": "admin", "password": "test-password", "role": "engineer"},
    )
    headers = {"X-Robot-User-Token": (await login.json())["data"]["user_token"]}
    missing_proof = await client.post(
        "/api/library/commands/wait/executions",
        headers=headers,
        json={"execute_real": True},
    )
    started = await client.post("/api/library/commands/wait/executions", headers=headers, json={})
    execution_id = (await started.json())["data"]["execution_id"]
    status = await client.get(f"/api/library/executions/{execution_id}", headers=headers)

    assert missing_proof.status == 400
    assert started.status == 202
    assert status.status == 200
    assert (await status.json())["data"]["actor"] == f"user:{admin['user_id']}"
    assert platform.run_flow_entry.call_count >= 1


@pytest.mark.asyncio
async def test_plan_confirm_execute_uses_immutable_plan_and_platform_boundary(aiohttp_client) -> None:
    platform = MagicMock()
    platform.plan_motion.return_value = {"ok": True, "state": "planned"}
    platform.execute_confirmed_plan.return_value = {"ok": True, "state": "executed"}
    client = await aiohttp_client(create_robot_server_app(platform=platform))
    request_body = {
        "session_id": "operator-1",
        "command": "linear_move",
        "parameters": {"target_pose": {"x": 1}},
    }

    planned = await client.post("/api/robot/plans", json=request_body)
    plan_payload = await planned.json()
    confirmed = await client.post(
        f"/api/robot/plans/{plan_payload['plan_id']}/confirm",
        json={
            "session_id": "operator-1",
            "confirm_work_area_clear": True,
            "confirm_estop_ready": True,
        },
    )
    confirmation = await confirmed.json()
    executed = await client.post(
        f"/api/robot/plans/{plan_payload['plan_id']}/execute",
        json={"session_id": "operator-1", "confirm_code": confirmation["confirm_code"]},
    )

    assert planned.status == 201
    assert confirmed.status == 200
    assert await executed.json() == {"ok": True, "state": "executed"}
    platform.execute_confirmed_plan.assert_called_once_with(
        "linear_move", {"target_pose": {"x": 1}}, confirmation_code="",
        confirm_work_area_clear=True, confirm_estop_ready=True,
        pending_plan_id=plan_payload["plan_id"], confirm_code=confirmation["confirm_code"],
    )


@pytest.mark.asyncio
async def test_execute_requires_a_confirmed_plan_from_same_session(aiohttp_client) -> None:
    platform = MagicMock()
    platform.plan_motion.return_value = {"ok": True}
    client = await aiohttp_client(create_robot_server_app(platform=platform))
    planned = await client.post(
        "/api/robot/plans",
        json={"session_id": "one", "command": "linear_move", "parameters": {}},
    )
    plan_id = (await planned.json())["plan_id"]
    confirm = await client.post(
        f"/api/robot/plans/{plan_id}/confirm",
        json={"session_id": "two", "confirm_work_area_clear": True, "confirm_estop_ready": True},
    )

    assert confirm.status == 409
    assert platform.execute_confirmed_plan.call_count == 0


@pytest.mark.asyncio
async def test_flow_plan_confirm_execute_uses_the_same_server_owned_safety_proof(aiohttp_client) -> None:
    platform = MagicMock()
    platform.run_flow.side_effect = [
        {"ok": True, "state": "flow_dry_run"},
        {"ok": True, "state": "flow_completed"},
    ]
    client = await aiohttp_client(create_robot_server_app(platform=platform))
    body = {"session_id": "operator-1", "flow_name": "pick-and-place"}

    planned = await client.post("/api/robot/flow-pending-plan", json=body)
    plan = await planned.json()
    confirmed = await client.post("/api/robot/flow-confirm", json={
        "session_id": "operator-1", "plan_id": plan["plan_id"],
        "confirm_work_area_clear": True, "confirm_estop_ready": True,
    })
    confirmation = await confirmed.json()
    executed = await client.post("/api/robot/flow-execute", json={
        "session_id": "operator-1", "plan_id": plan["plan_id"],
        "confirm_code": confirmation["confirm_code"],
    })

    assert planned.status == 201
    assert confirmed.status == 200
    assert await executed.json() == {"ok": True, "state": "flow_completed"}
    assert platform.run_flow.call_count == 2
    assert platform.run_flow.call_args.kwargs["execute_real"] is True
    assert platform.run_flow.call_args.kwargs["confirmation_code"] != confirmation["confirm_code"]


@pytest.mark.asyncio
async def test_legacy_flow_route_cannot_bypass_the_staged_real_execution_gate(aiohttp_client) -> None:
    platform = MagicMock()
    client = await aiohttp_client(create_robot_server_app(platform=platform))

    response = await client.post("/api/robot/flows/run", json={
        "name": "pick-and-place", "execute_real": True,
        "confirmation_code": "browser-supplied-proof",
        "confirm_work_area_clear": True, "confirm_estop_ready": True,
    })

    assert response.status == 409
    assert platform.run_flow.call_count == 0


@pytest.mark.asyncio
async def test_emergency_stop_keeps_explicit_confirmation(aiohttp_client) -> None:
    platform = MagicMock()
    platform.emergency_stop.return_value = {"ok": True, "state": "estopped"}
    client = await aiohttp_client(create_robot_server_app(platform=platform))

    rejected = await client.post("/api/robot/emergency-stop", json={})
    accepted = await client.post(
        "/api/robot/emergency-stop",
        json={
            "confirmation_code": "operator-proof",
            "confirm_work_area_clear": True,
            "confirm_estop_ready": True,
        },
    )

    assert rejected.status == 400
    assert await accepted.json() == {"ok": True, "state": "estopped"}
    platform.emergency_stop.assert_called_once_with(
        confirmation_code="operator-proof",
        confirm_work_area_clear=True,
        confirm_estop_ready=True,
    )


@pytest.mark.asyncio
async def test_agent_websocket_uses_runtime_events_without_a_channel_manager(aiohttp_client) -> None:
    runtime = _FakeRuntime()
    client = await aiohttp_client(create_robot_server_app(
        platform=MagicMock(), config=RobotServerConfig(agent_runtime=runtime)
    ))
    socket = await client.ws_connect("/ws/agent")
    try:
        ready = await socket.receive_json()
        await socket.send_json({"type": "message", "session_id": "session-1", "content": "hello"})
        for _ in range(10):
            if runtime.requests:
                break
            await asyncio.sleep(0)
        assert ready == {"event": "ready", "service": "robot-server"}
        assert runtime.requests[0].conversation_id == "session-1"

        await runtime.emit(AgentEvent("session-1", "delta", {"content": "Hel", "stream_id": "s1"}))
        assert await socket.receive_json() == {
            "event": "delta", "session_id": "session-1", "text": "Hel", "stream_id": "s1"
        }

        await socket.send_json({"type": "cancel", "session_id": "session-1"})
        assert await socket.receive_json() == {"event": "cancelled", "session_id": "session-1", "count": 1}
    finally:
        await socket.close()
