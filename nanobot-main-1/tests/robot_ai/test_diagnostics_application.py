from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from robot_platform.application import (
    AuthenticatedPrincipal,
    RobotDiagnosticsApplicationService,
    RobotDiagnosticsQuery,
    RobotDiagnosticsResponse,
    RobotStatusError,
    RobotStatusResponse,
)


def _principal(role: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        actor_id=f"{role}-1", role=role, session_id="session-1",
        auth_source="test",
    )


def test_diagnostics_is_engineer_scoped_before_status_read() -> None:
    status = MagicMock()
    result = RobotDiagnosticsApplicationService(status).query(
        RobotDiagnosticsQuery(_principal("operator")),
    )
    assert result.error.code == "engineer_required"
    status.query.assert_not_called()


def test_diagnostics_projects_status_without_mutating_it() -> None:
    status = MagicMock()
    source = {"ok": True, "data": {"robot_state": {
        "mode": "idle", "axes_mm": {"x": 12.5}, "alarms": [],
        "connected_real_device": True,
    }}}
    status.query.return_value = RobotStatusResponse(payload=source)

    result = RobotDiagnosticsApplicationService(status).query(
        RobotDiagnosticsQuery(_principal("engineer")),
    )

    assert result.payload == {"ok": True, "data": {
        "connection": {"mode": "idle", "real_device": True},
        "execution_mode": "dry_run_only", "position": {"x": 12.5},
        "io": {}, "alarms": [], "task": "idle", "command_echo": {},
    }}
    result.payload["data"]["position"]["x"] = 99
    assert source["data"]["robot_state"]["axes_mm"]["x"] == 12.5


def test_diagnostics_maps_status_failure_to_public_error() -> None:
    status = MagicMock()
    status.query.return_value = RobotStatusResponse(
        error=RobotStatusError("robot_status_unavailable", "robot status unavailable"),
    )
    result = RobotDiagnosticsApplicationService(status).query(
        RobotDiagnosticsQuery(_principal("engineer")),
    )
    assert result.error.code == "robot_status_unavailable"
    assert "secret" not in result.error.message


def test_diagnostics_deeply_detaches_nested_status_values() -> None:
    status = MagicMock()
    source = {"ok": True, "data": {
        "robot_state": {
            "mode": "idle",
            "axes_mm": {"x": {"nested": 1}},
            "alarms": [{"code": 1}],
        },
        "io": {"1": {"enabled": True}},
        "command_echo": {"command": {"name": "status"}},
    }}
    status.query.return_value = RobotStatusResponse(payload=source)
    result = RobotDiagnosticsApplicationService(status).query(
        RobotDiagnosticsQuery(_principal("engineer")),
    )

    projected = result.payload["data"]
    projected["position"]["x"]["nested"] = 2
    projected["alarms"][0]["code"] = 2
    projected["io"]["1"]["enabled"] = False
    projected["command_echo"]["command"]["name"] = "mutated"

    assert source["data"]["robot_state"]["axes_mm"]["x"]["nested"] == 1
    assert source["data"]["robot_state"]["alarms"][0]["code"] == 1
    assert source["data"]["io"]["1"]["enabled"] is True
    assert source["data"]["command_echo"]["command"]["name"] == "status"
    assert projected["task"] == "idle"


def test_diagnostics_sanitizes_projection_failure() -> None:
    class SecretString:
        def __str__(self) -> str:
            raise RuntimeError("controller secret")

    status = MagicMock()
    status.query.return_value = RobotStatusResponse(payload={
        "ok": True, "data": {"robot_state": {"mode": SecretString()}},
    })
    result = RobotDiagnosticsApplicationService(status).query(
        RobotDiagnosticsQuery(_principal("engineer")),
    )

    assert result.error.code == "robot_status_unavailable"
    assert result.error.message == "Robot status unavailable."


def test_diagnostics_response_rejects_impossible_state() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        RobotDiagnosticsResponse()
    with pytest.raises(TypeError, match="payload must be a dict"):
        RobotDiagnosticsResponse(payload=[])  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="AuthenticatedPrincipal"):
        RobotDiagnosticsQuery(None)  # type: ignore[arg-type]
