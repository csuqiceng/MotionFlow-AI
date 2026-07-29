"""Engineer-scoped command-library management boundary."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol

from .principal import AuthenticatedPrincipal


@dataclass(frozen=True)
class RobotLibraryManagementCommand:
    principal: AuthenticatedPrincipal
    action: str
    resource_id: str = ""
    body: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("RobotLibraryManagementCommand requires principal")
        if self.body is not None and not isinstance(self.body, dict):
            raise TypeError("RobotLibraryManagementCommand body must be a dict")


@dataclass(frozen=True)
class RobotLibraryManagementError:
    code: str
    message: str
    details: dict[str, Any] | None = None


@dataclass(frozen=True)
class RobotLibraryManagementResponse:
    payload: dict[str, Any] | None = None
    error: RobotLibraryManagementError | None = None
    created: bool = False

    def __post_init__(self) -> None:
        if (self.payload is None) == (self.error is None):
            raise ValueError("RobotLibraryManagementResponse requires payload or error")
        if self.error is not None and self.created:
            raise ValueError("Failed management response cannot be created")

    @property
    def ok(self) -> bool:
        return self.error is None


class RobotLibraryManagementPort(Protocol):
    def execute(
        self,
        action: str,
        resource_id: str,
        body: dict[str, Any] | None,
        *,
        actor: str,
    ) -> RobotLibraryManagementResponse: ...


class RobotLibraryManagementApplicationPort(Protocol):
    def execute(
        self, command: RobotLibraryManagementCommand,
    ) -> RobotLibraryManagementResponse: ...


class RobotLibraryManagementApplicationService:
    _ACTIONS = frozenset({
        "list", "get", "create", "save", "delete", "update_draft",
        "start_draft", "publish", "archive", "duplicate", "bulk_archive",
    })

    def __init__(self, management: RobotLibraryManagementPort) -> None:
        self._management = management

    def execute(
        self, command: RobotLibraryManagementCommand,
    ) -> RobotLibraryManagementResponse:
        if not isinstance(command, RobotLibraryManagementCommand):
            return _failure("invalid_request", "Management request is invalid.")
        if command.principal.role != "engineer":
            return _failure("library_forbidden", "Engineer role is required.")
        action = str(command.action).strip()
        if action not in self._ACTIONS:
            return _failure("invalid_request", "Management action is invalid.")
        try:
            response = self._management.execute(
                action,
                str(command.resource_id),
                deepcopy(command.body),
                actor=(
                    f"{command.principal.auth_source}:"
                    f"{command.principal.actor_id}"
                ),
            )
        except Exception:
            return _failure("library_state_unavailable", "Library state is unavailable.")
        if not isinstance(response, RobotLibraryManagementResponse):
            return _failure("library_state_unavailable", "Library state is unavailable.")
        if response.payload is not None:
            try:
                payload = deepcopy(response.payload)
                if not isinstance(payload, dict):
                    raise TypeError("management payload is invalid")
            except Exception:
                return _failure(
                    "library_state_unavailable", "Library state is unavailable.",
                )
            return RobotLibraryManagementResponse(
                payload=payload, created=response.created,
            )
        error = response.error
        if error is None:
            return _failure("library_state_unavailable", "Library state is unavailable.")
        return RobotLibraryManagementResponse(error=RobotLibraryManagementError(
            str(error.code), str(error.message), deepcopy(error.details),
        ))


def _failure(code: str, message: str) -> RobotLibraryManagementResponse:
    return RobotLibraryManagementResponse(
        error=RobotLibraryManagementError(code, message),
    )
