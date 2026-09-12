"""Authenticated HTTP facade for command-library management Application."""

from __future__ import annotations

from typing import Any

from robot_platform.application import (
    RobotLibraryManagementApplicationPort,
    RobotLibraryManagementCommand,
    RobotLibraryManagementResponse,
)
from robot_server.identity_api import RobotIdentityService


class RobotCommandManagementService:
    def __init__(
        self,
        identity: RobotIdentityService,
        application: RobotLibraryManagementApplicationPort,
    ) -> None:
        self._identity = identity
        self._application = application

    def list(self, token: str) -> tuple[int, dict[str, Any]]:
        return self._execute(token, "list")

    def get(self, token: str, command_id: str) -> tuple[int, dict[str, Any]]:
        return self._execute(token, "get", command_id)

    def create(self, token: str, body: Any) -> tuple[int, dict[str, Any]]:
        return self._execute(token, "create", body=body)

    def save(
        self, token: str, command_id: str, body: Any,
    ) -> tuple[int, dict[str, Any]]:
        return self._execute(token, "save", command_id, body)

    def delete(self, token: str, command_id: str) -> tuple[int, dict[str, Any]]:
        return self._execute(token, "delete", command_id)

    def update_draft(
        self, token: str, command_id: str, body: Any,
    ) -> tuple[int, dict[str, Any]]:
        return self._execute(token, "update_draft", command_id, body)

    def start_draft(
        self, token: str, command_id: str,
    ) -> tuple[int, dict[str, Any]]:
        return self._execute(token, "start_draft", command_id)

    def publish(self, token: str, command_id: str) -> tuple[int, dict[str, Any]]:
        return self._execute(token, "publish", command_id)

    def archive(self, token: str, command_id: str) -> tuple[int, dict[str, Any]]:
        return self._execute(token, "archive", command_id)

    def duplicate(
        self, token: str, command_id: str, body: Any,
    ) -> tuple[int, dict[str, Any]]:
        return self._execute(token, "duplicate", command_id, body)

    def bulk_archive(self, token: str, body: Any) -> tuple[int, dict[str, Any]]:
        return self._execute(token, "bulk_archive", body=body)

    def _execute(
        self,
        token: str,
        action: str,
        resource_id: str = "",
        body: Any = None,
    ) -> tuple[int, dict[str, Any]]:
        principal, error = self._identity.require_principal(token)
        if error is not None:
            return error
        assert principal is not None
        if body is not None and not isinstance(body, dict):
            return 400, {
                "error": {
                    "code": "invalid_request",
                    "message": "request body must be an object",
                }
            }
        response = self._application.execute(RobotLibraryManagementCommand(
            principal=principal,
            action=action,
            resource_id=resource_id,
            body=body,
        ))
        return _result(response)


def _result(
    response: RobotLibraryManagementResponse,
) -> tuple[int, dict[str, Any]]:
    if response.ok and isinstance(response.payload, dict):
        return (201 if response.created else 200), {
            "ok": True, "data": response.payload,
        }
    error = response.error
    code = getattr(error, "code", "library_state_unavailable")
    message = getattr(error, "message", "Library state is unavailable.")
    if code == "library_forbidden":
        status = 403
    elif code in {"command_not_found", "no_draft"}:
        status = 404
    elif code in {
        "command_exists", "save_conflict", "draft_conflict",
        "namespace_conflict", "archive_blocked", "duplicate_blocked",
    }:
        status = 409
    elif code == "library_state_unavailable":
        status = 503
    else:
        status = 400
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    details = getattr(error, "details", None)
    if isinstance(details, dict):
        body.update({"ok": False, "data": details})
    return status, body
