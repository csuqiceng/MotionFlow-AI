"""Authenticated HTTP facade for position-maintenance Application."""

from __future__ import annotations

from typing import Any

from robot_platform.application import (
    RobotMaintenanceResponse,
    RobotPositionMaintenanceApplicationService,
)
from robot_server.identity_api import RobotIdentityService


class RobotPositionMaintenanceService:
    def __init__(
        self,
        identity: RobotIdentityService,
        application: RobotPositionMaintenanceApplicationService,
    ) -> None:
        self._identity = identity
        self._application = application

    def preview(self, token: str) -> tuple[int, dict[str, Any]]:
        return self._execute(token, "preview")

    def apply(self, token: str, body: Any) -> tuple[int, dict[str, Any]]:
        if not isinstance(body, dict) or body.get("action") != "apply":
            return 400, {
                "error": {
                    "code": "invalid_action", "message": "action must be 'apply'.",
                }
            }
        return self._execute(token, "apply")

    def _execute(self, token: str, action: str) -> tuple[int, dict[str, Any]]:
        principal, error = self._identity.require_principal(token)
        if error is not None:
            return error
        assert principal is not None
        return _result(self._application.execute(principal, action))


def _result(response: RobotMaintenanceResponse) -> tuple[int, dict[str, Any]]:
    if response.ok and isinstance(response.payload, dict):
        return 200, {"ok": True, "data": response.payload}
    error = response.error
    code = getattr(error, "code", "position_state_unavailable")
    message = getattr(error, "message", "Position state is unavailable.")
    status = 403 if code == "library_forbidden" else 400 if code in {
        "invalid_action", "invalid_request", "invalid_positions",
    } else 503
    return status, {"error": {"code": code, "message": message}}
