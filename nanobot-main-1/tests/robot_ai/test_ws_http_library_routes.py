from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from nanobot.webui.ws_http import GatewayHTTPHandler
from robot_ai.library.models import Command
from robot_ai.library.registry import CommandRegistry


def _fake_handler(token_ok: bool, commands_path: str) -> SimpleNamespace:
    return SimpleNamespace(
        check_api_token=lambda _req: token_ok,
        _robot_commands_path=commands_path,
    )


def _fake_request(path: str) -> SimpleNamespace:
    return SimpleNamespace(path=path, headers={})


def _seed(path: Path) -> None:
    CommandRegistry(path).add(
        Command(id="io0-off", name="IO0关闭", component_id="io_write", aliases=["grip"])
    )


def test_library_list_requires_token(tmp_path: Path) -> None:
    commands = tmp_path / "commands.json"
    _seed(commands)
    fake = _fake_handler(token_ok=False, commands_path=str(commands))
    resp = GatewayHTTPHandler._dispatch_robot_library_routes(
        fake, _fake_request("/api/robot/library/commands"), "/api/robot/library/commands"
    )
    assert resp is not None
    assert resp.status_code == 401


def test_library_list_returns_200_with_token(tmp_path: Path) -> None:
    commands = tmp_path / "commands.json"
    _seed(commands)
    fake = _fake_handler(token_ok=True, commands_path=str(commands))
    resp = GatewayHTTPHandler._dispatch_robot_library_routes(
        fake, _fake_request("/api/robot/library/commands"), "/api/robot/library/commands"
    )
    assert resp.status_code == 200


def test_library_command_detail_404(tmp_path: Path) -> None:
    commands = tmp_path / "commands.json"
    _seed(commands)
    fake = _fake_handler(token_ok=True, commands_path=str(commands))
    resp = GatewayHTTPHandler._dispatch_robot_library_routes(
        fake, _fake_request("/api/robot/library/commands/nope"),
        "/api/robot/library/commands/nope",
    )
    assert resp.status_code == 404


def test_library_version_param_rejected(tmp_path: Path) -> None:
    commands = tmp_path / "commands.json"
    _seed(commands)
    fake = _fake_handler(token_ok=True, commands_path=str(commands))
    # got is path-only (as _parse_request_path yields); the query lives in request.path.
    resp = GatewayHTTPHandler._dispatch_robot_library_routes(
        fake, _fake_request("/api/robot/library/commands?version=1"),
        "/api/robot/library/commands",
    )
    assert resp.status_code == 400


def test_library_components_list(tmp_path: Path) -> None:
    fake = _fake_handler(token_ok=True, commands_path=str(tmp_path / "commands.json"))
    resp = GatewayHTTPHandler._dispatch_robot_library_routes(
        fake, _fake_request("/api/robot/library/components"),
        "/api/robot/library/components",
    )
    assert resp.status_code == 200


def test_non_library_path_returns_none(tmp_path: Path) -> None:
    fake = _fake_handler(token_ok=True, commands_path=str(tmp_path / "commands.json"))
    resp = GatewayHTTPHandler._dispatch_robot_library_routes(
        fake, _fake_request("/api/robot/status"), "/api/robot/status"
    )
    assert resp is None


def test_library_flow_list_returns_200(tmp_path: Path) -> None:
    from robot_ai.flow.models import FlowEntry
    from robot_ai.flow.registry import FlowRegistry

    flows = tmp_path / "flows.json"
    FlowRegistry(flows).add(FlowEntry(name="PickPlace", description="x"))
    fake = SimpleNamespace(
        check_api_token=lambda _req: True,
        _robot_commands_path=str(tmp_path / "commands.json"),
        _robot_flow_registry_path=str(flows),
    )
    resp = GatewayHTTPHandler._dispatch_robot_library_routes(
        fake, _fake_request("/api/robot/library/flows"), "/api/robot/library/flows"
    )
    assert resp.status_code == 200


def test_library_flow_detail_404(tmp_path: Path) -> None:
    fake = SimpleNamespace(
        check_api_token=lambda _req: True,
        _robot_commands_path=str(tmp_path / "commands.json"),
        _robot_flow_registry_path=str(tmp_path / "flows.json"),
    )
    resp = GatewayHTTPHandler._dispatch_robot_library_routes(
        fake, _fake_request("/api/robot/library/flows/nope"),
        "/api/robot/library/flows/nope",
    )
    assert resp.status_code == 404
