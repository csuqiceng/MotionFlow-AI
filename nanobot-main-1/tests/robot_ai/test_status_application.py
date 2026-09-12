from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ai_runtime.robot_tools.robot_arm import RobotArmTool
from robot_platform.application import (
    RobotStatusApplicationService,
    RobotStatusError,
    RobotStatusResponse,
)


def test_status_response_rejects_impossible_states() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        RobotStatusResponse()
    with pytest.raises(ValueError, match="exactly one"):
        RobotStatusResponse(
            payload={"ok": True},
            error=RobotStatusError("unexpected", "unexpected"),
        )
    with pytest.raises(ValueError, match="non-empty"):
        RobotStatusError("", "missing code")


def test_status_service_preserves_payload_and_adds_v1_capabilities() -> None:
    source = {
        "ok": True,
        "data": {
            "robot_state": {"mode": "idle"},
            "controller_capabilities": {
                "vendor": "simulation",
                "supports_state_read": True,
                "supports_real_writes": False,
                "motion_primitives": ["home"],
            },
        },
    }
    reader = MagicMock()
    reader.get_status.return_value = source

    outcome = RobotStatusApplicationService(reader).query()

    assert outcome.ok is True
    assert outcome.payload["data"]["robot_state"] == {"mode": "idle"}
    assert outcome.payload["data"]["capabilities"] == {
        "protocol_version": 1,
        "supports_state_read": True,
        "supports_real_writes": False,
        "motion_primitives": ["home"],
    }
    outcome.payload["data"]["robot_state"]["mode"] = "mutated"
    assert source["data"]["robot_state"]["mode"] == "idle"


def test_status_service_sanitizes_reader_exception() -> None:
    reader = MagicMock()
    reader.get_status.side_effect = RuntimeError("controller secret")

    outcome = RobotStatusApplicationService(reader).query()

    assert outcome.ok is False
    assert outcome.payload is None
    assert outcome.error.code == "robot_status_unavailable"
    assert outcome.error.message == "robot status unavailable"


def test_status_service_sanitizes_invalid_reader_contract() -> None:
    reader = MagicMock()
    reader.get_status.return_value = None

    outcome = RobotStatusApplicationService(reader).query()

    assert outcome.ok is False
    assert outcome.error.code == "robot_status_unavailable"


def test_robot_arm_status_uses_application_port_not_platform(tmp_path) -> None:
    platform = MagicMock()
    platform.get_status.side_effect = AssertionError("Tool bypassed Application")
    status_application = MagicMock()
    status_application.query.return_value = RobotStatusResponse(
        payload={"ok": True, "state": "status_report", "data": {"mode": "idle"}},
    )
    tool = RobotArmTool(
        platform=platform,
        status_application=status_application,
        positions_path=str(tmp_path / "positions.json"),
    )

    result = json.loads(asyncio.run(tool.execute(action="status")))

    assert result["state"] == "status_report"
    status_application.query.assert_called_once_with()
    platform.get_status.assert_not_called()


def test_robot_arm_status_fails_closed_for_invalid_application_result(tmp_path) -> None:
    status_application = MagicMock()
    status_application.query.return_value = SimpleNamespace(
        ok=False, payload=None, error=None,
    )
    tool = RobotArmTool(
        platform=MagicMock(),
        status_application=status_application,
        positions_path=str(tmp_path / "positions.json"),
    )

    result = json.loads(asyncio.run(tool.execute(action="status")))

    assert result["ok"] is False
    assert result["state"] == "robot_status_unavailable"
