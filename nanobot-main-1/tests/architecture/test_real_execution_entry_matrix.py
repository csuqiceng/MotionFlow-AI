"""Every public entry fails closed when offered legacy real-write credentials."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from ai_runtime.robot_tools.robot_arm import RobotArmTool
from ai_runtime.robot_tools.robot_flow import RobotFlowTool
from robot_platform.backends.factory import RobotBackendConfig
from robot_platform.backends.zmotion_adapter import (
    ZMotionOperatorRequest,
    _fully_confirmed,
    main as zmotion_cli_main,
    run_zmotion_operator_command,
)
from robot_platform.bridge import RobotApi
from robot_platform.flow import FlowEntry, FlowRegistry, FlowStep
from robot_platform.flow.executor import run_flow
from robot_platform.library.auth import hash_password
from robot_platform.library.users import UserRegistry, initialize_user_identity
from robot_server.app import RobotServerConfig, create_robot_server_app


INVENTORY = Path(__file__).with_name("fixtures") / "real-execution-entries-v1.json"
COVERED_REAL_ENTRY_IDS = {
    "zmotion_cli",
    "zmotion_backend_runner",
    "legacy_bridge",
    "flow_executor",
    "ai_robot_arm",
    "ai_robot_flow",
    "http_staged_command",
    "http_staged_flow",
    "http_legacy_flow",
    "http_library_command",
    "http_library_flow",
}


def test_real_execution_inventory_has_a_negative_case_for_every_entry() -> None:
    payload = json.loads(INVENTORY.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    inventory_ids = {entry["id"] for entry in payload["entries"]}
    assert len(inventory_ids) == len(payload["entries"])
    assert inventory_ids == COVERED_REAL_ENTRY_IDS


def test_static_confirmation_never_authorizes_backend_entry() -> None:
    request = ZMotionOperatorRequest(
        command="linear_move", parameters={}, execute_real=True,
        confirm_work_area_clear=True, confirm_estop_ready=True,
        confirmation_code="EXECUTE_ZMOTION_REAL",
    )
    assert _fully_confirmed(request) is False
    client_factory = MagicMock()
    result = run_zmotion_operator_command(
        request=request,
        config=RobotBackendConfig(
            mode="zmotion", controller_host="127.0.0.1",
            zmotion_wrapper_path="unused.py", zmotion_dll_dir="unused-dll-dir",
        ),
        client_factory=client_factory,
    )
    assert result["state"] == "zmotion_operator_confirmation_required"
    client_factory.assert_not_called()


def test_static_confirmation_never_authorizes_cli_entry(
    monkeypatch, capsys,
) -> None:
    monkeypatch.setenv("ROBOT_CONTROLLER_HOST", "127.0.0.1")
    monkeypatch.setenv("ROBOT_ZMOTION_WRAPPER_PATH", "unused.py")
    monkeypatch.setenv("ROBOT_ZMOTION_DLL_DIR", "unused-dll-dir")
    exit_code = zmotion_cli_main([
        "--execute-real", "--confirm-work-area-clear", "--confirm-estop-ready",
        "--confirmation-code", "EXECUTE_ZMOTION_REAL",
        "delay", "--seconds", "0.1",
    ])
    assert exit_code == 1
    assert "confirmations are required" in capsys.readouterr().out


def test_legacy_bridge_real_write_is_staged_rejection() -> None:
    runner = MagicMock()
    result = RobotApi(operator_runner=runner).operator_delay(
        0.1, execute_real=True, confirm_work_area_clear=True,
        confirm_estop_ready=True, confirmation_code="EXECUTE_ZMOTION_REAL",
    )
    assert result["state"] == "staged_execution_required"
    runner.assert_not_called()


def test_flow_top_level_credential_cannot_replace_child_permits() -> None:
    runner = MagicMock()
    result = run_flow(
        FlowEntry(name="flow", steps=[FlowStep(1, "delay", 110, {"seconds": 0})]),
        execute_real=True, confirm_work_area_clear=True, confirm_estop_ready=True,
        confirmation_code="EXECUTE_ZMOTION_REAL", operator_runner=runner,
    )
    assert result["state"] == "flow_step_permits_required"
    runner.assert_not_called()


def test_ai_tool_auto_mode_cannot_mint_real_execution_credential(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        "ai_runtime.robot_tools.robot_arm.get_robot_execution_mode",
        lambda: "auto_after_safety_check",
    )
    runner = MagicMock()
    tool = RobotArmTool(operator_runner=runner, positions_path=str(tmp_path / "positions.json"))
    result = json.loads(asyncio.run(tool.execute(action="delay", seconds=0.1)))
    assert result["state"] == "staged_execution_required"
    runner.assert_not_called()


def test_ai_flow_tool_auto_mode_cannot_mint_real_execution_credential(
    monkeypatch, tmp_path,
) -> None:
    monkeypatch.setattr(
        "ai_runtime.robot_tools.robot_flow.get_robot_execution_mode",
        lambda: "auto_after_safety_check",
    )
    flow_path = tmp_path / "flows.json"
    ok, message = FlowRegistry(flow_path).add(
        FlowEntry(name="flow", steps=[FlowStep(1, "delay", 110, {"seconds": 0})]),
    )
    assert ok, message
    tool = RobotFlowTool(
        registry_path=str(flow_path), alias_path=str(tmp_path / "aliases.json"),
    )
    result = json.loads(asyncio.run(tool.execute(
        action="run", name="flow", execute_real=True,
        confirmation_code="EXECUTE_ZMOTION_REAL",
    )))
    assert result["state"] == "staged_execution_required"


@pytest.mark.asyncio
async def test_http_legacy_flow_real_write_is_staged_rejection(
    tmp_path,
) -> None:
    initialize_user_identity(
        users_path=tmp_path / "users.json", audit_path=tmp_path / "audit.jsonl",
    )
    registry = UserRegistry(
        tmp_path / "users.json", audit_path=tmp_path / "audit.jsonl",
    )
    admin = registry.get_by_username("admin")
    assert admin is not None
    registry.bootstrap_set_password(
        admin["user_id"], hash_password("test-password", iterations=100_000),
    )
    (tmp_path / "commands.json").write_text(json.dumps({
        "schema_version": "2.0",
        "commands": {"wait": {"published_version": 1, "versions": {"1": {
            "id": "wait", "name": "Wait", "component_id": "delay",
            "parameters": {"delay_sec": 0.0},
        }}}},
    }), encoding="utf-8")
    ok, message = FlowRegistry(tmp_path / "flows.json").add(
        FlowEntry(name="flow", steps=[FlowStep(1, "delay", 110, {"seconds": 0})]),
    )
    assert ok, message
    platform = MagicMock()
    app = create_robot_server_app(
        platform=platform,
        config=RobotServerConfig(robot_data_dir=tmp_path),
    )
    async with TestClient(TestServer(app)) as client:
        login = await client.post(
            "/api/identity/login",
            json={"username": "admin", "password": "test-password", "role": "engineer"},
        )
        assert login.status == 200
        headers = {"X-Robot-User-Token": (await login.json())["data"]["user_token"]}
        legacy_flow = await client.post(
            "/api/robot/flows/run",
            headers=headers,
            json={"name": "flow", "execute_real": True,
                  "confirmation_code": "EXECUTE_ZMOTION_REAL"},
        )
        library_command = await client.post(
            "/api/library/commands/wait/executions", headers=headers,
            json={"execute_real": True, "confirmation_code": "EXECUTE_ZMOTION_REAL"},
        )
        library_flow = await client.post(
            "/api/library/flows/flow/executions", headers=headers,
            json={"execute_real": True, "confirmation_code": "EXECUTE_ZMOTION_REAL"},
        )
        staged_command = await client.post(
            "/api/robot/plans/missing/execute", headers=headers,
            json={"confirmation_code": "EXECUTE_ZMOTION_REAL"},
        )
        staged_flow = await client.post(
            "/api/robot/flow-execute", headers=headers,
            json={"plan_id": "missing", "confirmation_code": "EXECUTE_ZMOTION_REAL"},
        )
        assert legacy_flow.status == 409
        assert "staged flow plan" in (await legacy_flow.json())["error"]["message"]
        assert library_command.status == 409
        assert library_flow.status == 409
        assert 400 <= staged_command.status < 500
        assert 400 <= staged_flow.status < 500
        platform.run_flow.assert_not_called()
        platform.run_flow_entry.assert_not_called()
