"""Authenticated HTTP facade for Flow management Application."""

from __future__ import annotations

from typing import Any

from robot_platform.application import (
    RobotFlowManagementApplicationPort,
    RobotFlowManagementCommand,
    RobotFlowManagementResponse,
)
from robot_server.identity_api import RobotIdentityService


class RobotFlowManagementService:
    def __init__(
        self,
        identity: RobotIdentityService,
        application: RobotFlowManagementApplicationPort,
    ) -> None:
        self._identity = identity
        self._application = application

    def list(self, token: str) -> tuple[int, dict[str, Any]]:
        return self._execute(token, "list")

    def get(self, token: str, flow_id: str) -> tuple[int, dict[str, Any]]:
        return self._execute(token, "get", flow_id)

    def create(self, token: str, body: Any) -> tuple[int, dict[str, Any]]:
        return self._execute(token, "create", body=body)

    def save(
        self, token: str, flow_id: str, body: Any,
    ) -> tuple[int, dict[str, Any]]:
        return self._execute(token, "save", flow_id, body)

    def delete(self, token: str, flow_id: str) -> tuple[int, dict[str, Any]]:
        return self._execute(token, "delete", flow_id)

    def update_draft(
        self, token: str, flow_id: str, body: Any,
    ) -> tuple[int, dict[str, Any]]:
        return self._execute(token, "update_draft", flow_id, body)

    def start_draft(
        self, token: str, flow_id: str,
    ) -> tuple[int, dict[str, Any]]:
        return self._execute(token, "start_draft", flow_id)

    def validate_draft(
        self, token: str, flow_id: str,
    ) -> tuple[int, dict[str, Any]]:
        return self._execute(token, "validate_draft", flow_id)

    def publish(self, token: str, flow_id: str) -> tuple[int, dict[str, Any]]:
        return self._execute(token, "publish", flow_id)

    def archive(self, token: str, flow_id: str) -> tuple[int, dict[str, Any]]:
        return self._execute(token, "archive", flow_id)

    def duplicate(
        self, token: str, flow_id: str, body: Any,
    ) -> tuple[int, dict[str, Any]]:
        return self._execute(token, "duplicate", flow_id, body)

    def bulk_archive(self, token: str, body: Any) -> tuple[int, dict[str, Any]]:
        return self._execute(token, "bulk_archive", body=body)

    def _execute(
        self,
        token: str,
        action: str,
        flow_id: str = "",
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
        return _result(self._application.execute(RobotFlowManagementCommand(
            principal=principal,
            action=action,
            flow_id=flow_id,
            body=body,
        )))


def _result(
    response: RobotFlowManagementResponse,
) -> tuple[int, dict[str, Any]]:
    if response.ok and isinstance(response.payload, dict):
        return (201 if response.created else 200), {
            "ok": True, "data": response.payload,
        }
    error = response.error
    code = getattr(error, "code", "flow_state_unavailable")
    message = getattr(error, "message", "Flow state is unavailable.")
    if code == "flow_forbidden":
        status = 403
    elif code in {"flow_not_found", "no_draft"}:
        status = 404
    elif code in {
        "save_conflict", "draft_conflict", "archive_blocked",
        "duplicate_blocked", "flow_exists",
    }:
        status = 409
    elif code == "flow_state_unavailable":
        status = 503
    else:
        status = 400
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    details = getattr(error, "details", None)
    if isinstance(details, dict):
        body.update({"ok": False, "data": details})
    return status, body
