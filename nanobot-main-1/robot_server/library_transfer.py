"""Authenticated HTTP facade for library transfer Application."""

from __future__ import annotations

from typing import Any

from robot_platform.application import (
    RobotLibraryTransferApplicationService,
    RobotMaintenanceResponse,
)
from robot_server.identity_api import RobotIdentityService


class RobotLibraryTransferService:
    def __init__(
        self,
        identity: RobotIdentityService,
        application: RobotLibraryTransferApplicationService,
    ) -> None:
        self._identity = identity
        self._application = application

    def export(self, token: str) -> tuple[int, dict[str, Any]]:
        principal, error = self._identity.require_principal(token)
        if error is not None:
            return error
        assert principal is not None
        return _result(self._application.export(principal))

    def import_payload(self, token: str, body: Any) -> tuple[int, dict[str, Any]]:
        principal, error = self._identity.require_principal(token)
        if error is not None:
            return error
        assert principal is not None
        if not isinstance(body, dict):
            return 400, {
                "error": {"code": "invalid_request", "message": "body must be an object."}
            }
        return _result(self._application.import_payload(
            principal,
            body.get("payload"),
            strategy=str(body.get("strategy", "skip")),
        ))


def _result(response: RobotMaintenanceResponse) -> tuple[int, dict[str, Any]]:
    if response.ok and isinstance(response.payload, dict):
        return 200, {"ok": True, "data": response.payload}
    error = response.error
    code = getattr(error, "code", "library_state_unavailable")
    message = getattr(error, "message", "Library state is unavailable.")
    status = 403 if code == "library_forbidden" else 400 if code in {
        "invalid_request", "invalid_transfer",
    } else 503
    return status, {"error": {"code": code, "message": message}}
