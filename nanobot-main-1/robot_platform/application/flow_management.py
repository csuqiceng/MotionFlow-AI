"""Engineer-only Flow authoring Application boundary."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol

from .principal import AuthenticatedPrincipal


@dataclass(frozen=True)
class RobotFlowManagementCommand:
    principal: AuthenticatedPrincipal
    action: str
    flow_id: str = ""
    body: dict[str, Any] | None = None


@dataclass(frozen=True)
class RobotFlowManagementError:
    code: str
    message: str
    details: dict[str, Any] | None = None


@dataclass(frozen=True)
class RobotFlowManagementResponse:
    payload: dict[str, Any] | None = None
    error: RobotFlowManagementError | None = None
    created: bool = False

    def __post_init__(self) -> None:
        if (self.payload is None) == (self.error is None):
            raise ValueError("RobotFlowManagementResponse requires payload or error")
        if self.error is not None and self.created:
            raise ValueError("Failed Flow management response cannot be created")

    @property
    def ok(self) -> bool:
        return self.error is None


class RobotFlowManagementPort(Protocol):
    def execute(
        self,
        action: str,
        flow_id: str,
        body: dict[str, Any] | None,
        *,
        actor: str,
    ) -> RobotFlowManagementResponse: ...


class RobotFlowManagementApplicationPort(Protocol):
    def execute(
        self, command: RobotFlowManagementCommand,
    ) -> RobotFlowManagementResponse: ...


class RobotFlowManagementApplicationService:
    _ACTIONS = frozenset({
        "list", "get", "create", "save", "delete", "start_draft",
        "update_draft", "validate_draft", "publish", "archive",
        "duplicate", "bulk_archive",
    })

    def __init__(self, management: RobotFlowManagementPort) -> None:
        self._management = management

    def execute(
        self, command: RobotFlowManagementCommand,
    ) -> RobotFlowManagementResponse:
        if not isinstance(command, RobotFlowManagementCommand):
            return _failure("invalid_request", "Flow management request is invalid.")
        if command.principal.role != "engineer":
            return _failure("flow_forbidden", "Engineer role is required.")
        if command.action not in self._ACTIONS:
            return _failure("invalid_request", "Flow management action is invalid.")
        try:
            body = deepcopy(command.body)
            response = self._management.execute(
                command.action,
                str(command.flow_id),
                body,
                actor=f"{command.principal.auth_source}:{command.principal.actor_id}",
            )
            if not isinstance(response, RobotFlowManagementResponse):
                raise TypeError("Flow management response is invalid")
            if response.ok:
                return RobotFlowManagementResponse(
                    payload=deepcopy(response.payload), created=response.created,
                )
            error = response.error
            if error is None:
                raise TypeError("Flow management error is invalid")
            return RobotFlowManagementResponse(error=RobotFlowManagementError(
                str(error.code), str(error.message), deepcopy(error.details),
            ))
        except Exception:
            return _failure(
                "flow_state_unavailable", "Flow state is unavailable.",
            )


def _failure(code: str, message: str) -> RobotFlowManagementResponse:
    return RobotFlowManagementResponse(error=RobotFlowManagementError(code, message))
