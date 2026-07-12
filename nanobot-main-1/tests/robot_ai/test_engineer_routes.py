from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from robot_ai.library.auth import EngineerTokenStore, LoginThrottle, hash_password
from robot_ai.library.versioned_registry import VersionedCommandRegistry

# ---------------------------------------------------------------------------
# aiohttp transport (real POST/PUT; D9: ignores X-Nanobot-Engineer-Action)
# ---------------------------------------------------------------------------

async def _make_client(
    tmp_path: Path, configured: bool = True, throttle: LoginThrottle | None = None
):
    from nanobot.api.robot_routes import register_engineer_routes

    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps(
            {
                "robotAi": {
                    "engineer": {
                        "passwordHash": hash_password("s3cret", iterations=100_000) if configured else "",
                        "pbkdf2Iterations": 200_000,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    app = web.Application()
    app["robot_commands_path"] = str(tmp_path / "commands.json")
    app["robot_audit_path"] = str(tmp_path / "audit.jsonl")
    app["engineer_config_path"] = str(cfg)
    store = EngineerTokenStore()
    app["engineer_token_store"] = store
    if throttle is not None:
        app["engineer_login_throttle"] = throttle
    register_engineer_routes(app)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client, store


@pytest.mark.asyncio
async def test_login_then_commands_require_engineer_token(tmp_path: Path) -> None:
    client, _store = await _make_client(tmp_path)
    VersionedCommandRegistry(
        tmp_path / "commands.json", audit_path=tmp_path / "audit.jsonl"
    ).create_entity("home", "linear_move", "Home", {})
    # 1) commands without an engineer token -> 401 (gateway token via ?token= is
    #    accepted by aiohttp standalone since these routes are not token-gated at
    #    the transport layer here).
    r = await client.get("/api/robot/engineer/commands", params={"token": "gtok"})
    assert r.status == 401
    # 2) login via GET + body header -> 200 + no-store + engineer token.
    r = await client.get(
        "/api/robot/engineer/login",
        params={"token": "gtok"},
        headers={"X-Nanobot-Robot-Body": '{"password": "s3cret"}'},
    )
    assert r.status == 200
    assert r.headers.get("Cache-Control") == "no-store"
    etok = (await r.json())["data"]["engineer_token"]
    # 3) commands with engineer token -> 200 + no-store.
    r = await client.get(
        "/api/robot/engineer/commands",
        params={"token": "gtok"},
        headers={"X-Nanobot-Engineer-Token": etok},
    )
    assert r.status == 200
    assert r.headers.get("Cache-Control") == "no-store"


@pytest.mark.asyncio
async def test_login_throttle_sets_retry_after_header(tmp_path: Path) -> None:
    """R5: 429 must carry the HTTP Retry-After header (not just JSON body)."""
    client, _store = await _make_client(
        tmp_path, throttle=LoginThrottle(max_attempts=2, window_seconds=300)
    )
    for _ in range(2):
        await client.get(
            "/api/robot/engineer/login",
            params={"token": "gtok"},
            headers={"X-Nanobot-Robot-Body": '{"password": "wrong"}'},
        )
    r = await client.get(
        "/api/robot/engineer/login",
        params={"token": "gtok"},
        headers={"X-Nanobot-Robot-Body": '{"password": "wrong"}'},
    )
    assert r.status == 429
    assert r.headers.get("Retry-After") is not None
    assert int(r.headers["Retry-After"]) >= 1
    assert r.headers.get("Cache-Control") == "no-store"


@pytest.mark.asyncio
async def test_create_command_slug_via_aiohttp_post(tmp_path: Path) -> None:
    """D9: aiohttp uses real POST; ignores the X-Nanobot-Engineer-Action header."""
    client, store = await _make_client(tmp_path)
    etok = store.issue()
    r = await client.post(
        "/api/robot/engineer/commands",
        params={"token": "gtok"},
        headers={
            "X-Nanobot-Engineer-Token": etok,
            # aiohttp must IGNORE this header entirely (real POST = create).
            "X-Nanobot-Engineer-Action": "bogus",
        },
        json={"name": "Pick Place", "component_id": "linear_move",
              "parameters": {"target_x": 1.0}},
    )
    assert r.status == 201
    assert (await r.json())["data"]["command_id"] == "pick-place"
    assert r.headers.get("Cache-Control") == "no-store"


@pytest.mark.asyncio
async def test_audit_endpoint_paginates_and_no_store(tmp_path: Path) -> None:
    client, store = await _make_client(tmp_path)
    etok = store.issue()
    audit = tmp_path / "audit.jsonl"
    with open(audit, "w", encoding="utf-8") as f:
        for i in range(3):
            f.write(json.dumps({"action": "command_publish", "actor": "engineer",
                                "audit_id": f"id-{i}", "timestamp": f"2026-07-12T00:00:0{i}"}) + "\n")
    r = await client.get(
        "/api/robot/engineer/audit",
        params={"token": "gtok", "limit": 2},
        headers={"X-Nanobot-Engineer-Token": etok},
    )
    assert r.status == 200
    assert r.headers.get("Cache-Control") == "no-store"
    body = await r.json()
    assert [e["audit_id"] for e in body["data"]["items"]] == ["id-2", "id-1"]


# ---------------------------------------------------------------------------
# ws_http transport (GET-only; D9: X-Nanobot-Engineer-Action disambiguates)
# ---------------------------------------------------------------------------

def _make_ws_handler(tmp_path: Path, *, throttle: LoginThrottle | None = None):
    """Build a minimal GatewayHTTPHandler with the attributes the engineer
    dispatcher reads. Mirrors how the real composition layer would set
    ``_robot_commands_path`` / ``_robot_audit_path`` / ``_engineer_config_path``.
    """
    from nanobot.webui.gateway_tokens import GatewayTokenStore
    from nanobot.webui.ws_http import GatewayHTTPHandler

    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps(
            {"robotAi": {"engineer": {
                "passwordHash": hash_password("s3cret", iterations=100_000),
                "pbkdf2Iterations": 200_000}}}
        ),
        encoding="utf-8",
    )
    reg = VersionedCommandRegistry(tmp_path / "commands.json", audit_path=tmp_path / "audit.jsonl")
    reg.create_entity("home", "linear_move", "Home", {"target_x": 1.0})
    reg.publish("home", component_risk_level="high")

    handler = GatewayHTTPHandler.__new__(GatewayHTTPHandler)
    # check_api_token delegates to self.tokens.check_api_token(request); seed a
    # long-lived API token "gtok" that the ?token= query param supplies.
    tokens = GatewayTokenStore()
    tokens.api_tokens["gtok"] = __import__("time").monotonic() + 9999
    handler.tokens = tokens
    handler._robot_commands_path = str(tmp_path / "commands.json")
    handler._robot_audit_path = str(tmp_path / "audit.jsonl")
    handler._engineer_config_path = str(cfg)
    handler._engineer_token_store = EngineerTokenStore()
    handler._engineer_login_throttle = throttle or LoginThrottle(max_attempts=5, window_seconds=300)
    return handler


class _FakeRequest:
    """Minimal stand-in for the websockets WsRequest the dispatcher reads."""

    def __init__(self, path: str, headers: dict[str, str]):
        self.path = path
        self.headers = headers
        self.remote = "127.0.0.1"

    @property
    def got(self) -> str:
        # The real dispatcher receives the normalized path (no query string).
        return self.path.split("?", 1)[0]


def _eng_dispatch(handler, request: _FakeRequest):
    """Call the engineer dispatcher with (request, got) — mirrors how the main
    dispatch in ws_http._dispatch_resolved invokes it."""
    return handler._dispatch_robot_engineer_routes(request, request.got)


def test_ws_http_engineer_dispatch_action_header_and_gates(tmp_path: Path) -> None:
    """D9: ws_http GET path uses X-Nanobot-Engineer-Action to disambiguate
    create/start-draft/update-draft; gateway token + engineer token gated;
    no-store on every response; Retry-After header on 429."""
    handler = _make_ws_handler(tmp_path)
    store = handler._engineer_token_store

    # 1) login via GET + body header -> 200 + no-store + engineer token issued
    resp = _eng_dispatch(
        handler,
        _FakeRequest(
            "/api/robot/engineer/login?token=gtok",
            {"X-Nanobot-Robot-Body": quote(json.dumps({"password": "s3cret"}))},
        ),
    )
    assert resp is not None and resp.status_code == 200
    assert resp.headers.get("Cache-Control") == "no-store"
    etok = json.loads(resp.body.decode("utf-8"))["data"]["engineer_token"]
    assert store.check(etok) is True

    # 2) create via GET + Action: create -> 201 slug
    resp = _eng_dispatch(
        handler,
        _FakeRequest(
            "/api/robot/engineer/commands?token=gtok",
            {
                "X-Nanobot-Engineer-Token": etok,
                "X-Nanobot-Engineer-Action": "create",
                "X-Nanobot-Robot-Body": quote(json.dumps(
                    {"name": "Pick Place", "component_id": "linear_move",
                     "parameters": {"target_x": 1.0}})),
            },
        ),
    )
    assert resp.status_code == 201
    assert json.loads(resp.body.decode("utf-8"))["data"]["command_id"] == "pick-place"

    # 3) list via GET, no action -> 200 (read-only)
    resp = _eng_dispatch(
        handler,
        _FakeRequest(
            "/api/robot/engineer/commands?token=gtok",
            {"X-Nanobot-Engineer-Token": etok},
        ),
    )
    assert resp.status_code == 200

    # 3b) detail via GET /commands/{id}, no action -> 200 (path-disambiguated read)
    resp = _eng_dispatch(
        handler,
        _FakeRequest(
            "/api/robot/engineer/commands/home?token=gtok",
            {"X-Nanobot-Engineer-Token": etok},
        ),
    )
    assert resp.status_code == 200
    assert json.loads(resp.body.decode("utf-8"))["data"]["command_id"] == "home"

    # 4) start-draft via GET + Action: start-draft on published 'home' -> 201
    resp = _eng_dispatch(
        handler,
        _FakeRequest(
            "/api/robot/engineer/commands/home/draft?token=gtok",
            {"X-Nanobot-Engineer-Token": etok, "X-Nanobot-Engineer-Action": "start-draft"},
        ),
    )
    assert resp.status_code == 201

    # 5) update-draft via GET + Action: update-draft -> 200
    resp = _eng_dispatch(
        handler,
        _FakeRequest(
            "/api/robot/engineer/commands/home/draft?token=gtok",
            {
                "X-Nanobot-Engineer-Token": etok,
                "X-Nanobot-Engineer-Action": "update-draft",
                "X-Nanobot-Robot-Body": quote(json.dumps(
                    {"expected_revision": 1, "name": "Home", "aliases": [], "description": "",
                     "component_id": "linear_move", "parameters": {"target_x": 2.0}})),
            },
        ),
    )
    assert resp.status_code == 200

    # 6) draft path with NO action -> 400
    resp = _eng_dispatch(
        handler,
        _FakeRequest(
            "/api/robot/engineer/commands/home/draft?token=gtok",
            {"X-Nanobot-Engineer-Token": etok},
        ),
    )
    assert resp.status_code == 400

    # 7) unknown action -> 400
    resp = _eng_dispatch(
        handler,
        _FakeRequest(
            "/api/robot/engineer/commands?token=gtok",
            {"X-Nanobot-Engineer-Token": etok, "X-Nanobot-Engineer-Action": "bogus"},
        ),
    )
    assert resp.status_code == 400

    # 8) no engineer token on a write -> 401
    resp = _eng_dispatch(
        handler,
        _FakeRequest(
            "/api/robot/engineer/commands?token=gtok",
            {
                "X-Nanobot-Engineer-Action": "create",
                "X-Nanobot-Robot-Body": quote(json.dumps(
                    {"name": "X", "component_id": "delay", "parameters": {}})),
            },
        ),
    )
    assert resp.status_code == 401

    # 9) gateway-token gate: no ?token= -> 401 (before any engineer logic)
    resp = _eng_dispatch(
        handler,
        _FakeRequest(
            "/api/robot/engineer/commands",
            {"X-Nanobot-Engineer-Token": etok},
        ),
    )
    assert resp.status_code == 401


def test_ws_http_engineer_login_429_sets_retry_after_header(tmp_path: Path) -> None:
    """R5: ws_http 429 carries the HTTP Retry-After header."""
    throttle = LoginThrottle(max_attempts=2, window_seconds=300)
    handler = _make_ws_handler(tmp_path, throttle=throttle)
    for _ in range(2):
        _eng_dispatch(
            handler,
            _FakeRequest(
                "/api/robot/engineer/login?token=gtok",
                {"X-Nanobot-Robot-Body": quote(json.dumps({"password": "wrong"}))},
            ),
        )
    resp = _eng_dispatch(
        handler,
        _FakeRequest(
            "/api/robot/engineer/login?token=gtok",
            {"X-Nanobot-Robot-Body": quote(json.dumps({"password": "wrong"}))},
        ),
    )
    assert resp.status_code == 429
    assert resp.headers.get("Retry-After") is not None
    assert int(resp.headers["Retry-After"]) >= 1
    assert resp.headers.get("Cache-Control") == "no-store"
