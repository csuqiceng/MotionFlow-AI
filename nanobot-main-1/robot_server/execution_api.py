"""Authenticated HTTP facade for tracked library execution Application."""

from __future__ import annotations

from typing import Any

from robot_platform.application import (
    RobotLibraryExecutionApplicationPort,
    RobotLibraryExecutionCommand,
    RobotLibraryExecutionResponse,
)
from robot_server.identity_api import RobotIdentityService


class RobotExecutionService:
    def __init__(
        self,
        identity: RobotIdentityService,
        application: RobotLibraryExecutionApplicationPort,
    ) -> None:
        self._identity = identity
        self._application = application

    def start_command(
        self, token: str, command_id: str, body: Any,
    ) -> tuple[int, dict[str, Any]]:
        return self._execute(token, "start_command", source_id=command_id, body=body)

    def start_flow(
        self, token: str, flow_id: str, body: Any,
    ) -> tuple[int, dict[str, Any]]:
        return self._execute(token, "start_flow", source_id=flow_id, body=body)

    def get(self, token: str, execution_id: str) -> tuple[int, dict[str, Any]]:
        return self._execute(token, "get", execution_id=execution_id)

    def list(self, token: str) -> tuple[int, dict[str, Any]]:
        return self._execute(token, "list")

    def control(
        self, token: str, execution_id: str, body: Any,
    ) -> tuple[int, dict[str, Any]]:
        return self._execute(token, "control", execution_id=execution_id, body=body)

    def _execute(
        self,
        token: str,
        action: str,
        *,
        source_id: str = "",
        execution_id: str = "",
        body: Any = None,
    ) -> tuple[int, dict[str, Any]]:
        principal, error = self._identity.require_principal(token)
        if error is not None:
            return error
        assert principal is not None
        if body is not None and not isinstance(body, dict):
            return 400, {"error": {
                "code": "invalid_request",
                "message": "request body must be an object",
            }}
        return _result(self._application.execute(RobotLibraryExecutionCommand(
            principal=principal,
            action=action,
            source_id=source_id,
            execution_id=execution_id,
            body=body,
        )))


def _result(
    response: RobotLibraryExecutionResponse,
) -> tuple[int, dict[str, Any]]:
    if response.ok and isinstance(response.payload, dict):
        return (202 if response.accepted else 200), {
            "ok": True, "data": response.payload,
        }
    error = response.error
    code = getattr(error, "code", "execution_state_unavailable")
    message = getattr(error, "message", "Execution state is unavailable.")
    if code == "execution_forbidden":
        status = 403
    elif code in {"command_not_found", "flow_not_found", "execution_not_found"}:
        status = 404
    elif code in {"staged_execution_required", "execution_control_conflict"}:
        status = 409
    elif code == "execution_state_unavailable":
        status = 503
    else:
        status = 400
    return status, {"error": {"code": code, "message": message}}
