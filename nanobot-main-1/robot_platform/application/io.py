"""Confirmed digital-I/O execution use case."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import Any, Protocol

from robot_platform.io_policy import (
    normalize_io_output_channels,
    valid_io_channel,
)

from .confirmed_execution import (
    ConfirmedExecutionPlatformPort as RobotIOPlatformPort,
)
from .confirmed_execution import (
    ConfirmedExecutionPolicy,
    ConfirmedPlanExecutionEngine,
    public_execution_metadata,
)
from .confirmed_execution import (
    ConfirmedPendingPlanPort as IOPendingPlanPort,
)
from .confirmed_execution import (
    ConfirmedPermitStorePort as IOPermitStorePort,
)
from .confirmed_execution import (
    ConfirmedSessionGatePort as IOSessionGatePort,
)
from .principal import AuthenticatedPrincipal

IO_COMMANDS = frozenset({"io"})


@dataclass(frozen=True)
class RobotIOExecutionCommand:
    principal: AuthenticatedPrincipal
    plan_id: str
    confirmation_receipt: str

    def __post_init__(self) -> None:
        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("RobotIOExecutionCommand requires AuthenticatedPrincipal")
        if not str(self.plan_id).strip() or not str(self.confirmation_receipt).strip():
            raise ValueError("RobotIOExecutionCommand requires plan ID and receipt")


@dataclass(frozen=True)
class RobotIOError:
    code: str
    message: str

    def __post_init__(self) -> None:
        if not self.code.strip() or not self.message.strip():
            raise ValueError("RobotIOError requires code and message")


@dataclass(frozen=True)
class RobotIOResponse:
    payload: dict[str, Any] | None = None
    error: RobotIOError | None = None
    replayed: bool = False

    def __post_init__(self) -> None:
        if (self.payload is None) == (self.error is None):
            raise ValueError("RobotIOResponse requires exactly one of payload or error")
        if self.payload is not None and not isinstance(self.payload, dict):
            raise TypeError("RobotIOResponse payload must be a dict")
        if self.error is not None and self.replayed:
            raise ValueError("Failed IO response cannot be replayed")

    @property
    def ok(self) -> bool:
        return self.error is None


class RobotIOApplicationPort(Protocol):
    def execute(self, command: RobotIOExecutionCommand) -> RobotIOResponse: ...


class RobotIOApplicationService:
    """IO-specific policy and DTO boundary over confirmed execution."""

    def __init__(
        self,
        platform: RobotIOPlatformPort | None = None,
        pending_plans: IOPendingPlanPort | None = None,
        session_gates: IOSessionGatePort | None = None,
        permits: IOPermitStorePort | None = None,
        *,
        robot_id: str = "",
        controller_id: str = "",
        product_profile_version: str = "",
        capability_version: str = "",
        deployment_instance_id: str = "",
        core_version: str = "",
        engine: ConfirmedPlanExecutionEngine | None = None,
        allowed_io_output_channels: Collection[int] = (),
    ) -> None:
        self._allowed_io_output_channels = normalize_io_output_channels(
            allowed_io_output_channels
        )
        self._policy = _io_policy(self._allowed_io_output_channels)
        if engine is not None:
            if any(value is not None for value in (
                platform, pending_plans, session_gates, permits,
            )):
                raise ValueError("IO engine cannot be combined with direct dependencies")
            self._engine = engine
            return
        if any(value is None for value in (
            platform, pending_plans, session_gates, permits,
        )):
            raise ValueError("RobotIOApplicationService requires execution dependencies")
        self._engine = ConfirmedPlanExecutionEngine(
            platform, pending_plans, session_gates, permits,
            robot_id=robot_id,
            controller_id=controller_id,
            product_profile_version=product_profile_version,
            capability_version=capability_version,
            deployment_instance_id=deployment_instance_id,
            core_version=core_version,
        )

    def execute(self, command: RobotIOExecutionCommand) -> RobotIOResponse:
        if not isinstance(command, RobotIOExecutionCommand):
            return _failure("invalid_io_request", "IO request is invalid.")
        outcome = self._engine.execute(
            principal=command.principal,
            plan_id=command.plan_id,
            confirmation_receipt=command.confirmation_receipt,
            policy=self._policy,
        )
        if outcome.payload is not None:
            return RobotIOResponse(payload=outcome.payload, replayed=outcome.replayed)
        return _failure(
            _public_error_code(str(outcome.error_key)), str(outcome.error_message),
        )


def _io_policy(
    allowed_io_output_channels: tuple[int, ...],
) -> ConfirmedExecutionPolicy:
    return ConfirmedExecutionPolicy(
        family="io",
        title="IO",
        subject="IO",
        plan_description="an IO plan",
        allowed_commands=IO_COMMANDS,
        validate_parameters=lambda _command, parameters: _valid_io_parameters(
            parameters, allowed_io_output_channels,
        ),
        public_data=lambda command, parameters, raw: _public_io_data(
            command, parameters, raw,
        ),
        success_message="Robot IO completed.",
        failure_message="Robot IO did not complete; reconcile controller state.",
    )


def _valid_io_parameters(
    parameters: dict[str, Any],
    allowed_io_output_channels: tuple[int, ...],
) -> bool:
    if set(parameters) != {"io_number", "enabled", "allowed_io_channels"}:
        return False
    io_number = parameters.get("io_number")
    enabled = parameters.get("enabled")
    allowed = parameters.get("allowed_io_channels")
    return bool(
        valid_io_channel(io_number)
        and isinstance(enabled, bool)
        and isinstance(allowed, list)
        and tuple(allowed) == allowed_io_output_channels
        and io_number in allowed_io_output_channels
    )


def _public_io_data(
    command: str, parameters: dict[str, Any], raw: Any,
) -> dict[str, Any]:
    public = public_execution_metadata(raw)
    public["action"] = command
    # Echo only the immutable, validated plan snapshot; backend output cannot
    # change which channel/value the API reports as having been requested.
    public["io_number"] = parameters["io_number"]
    public["enabled"] = parameters["enabled"]
    return public


def _public_error_code(key: str) -> str:
    if key == "invalid_request":
        return "invalid_io_request"
    if key == "unsupported_plan":
        return "unsupported_io_plan"
    return f"io_{key}"


def _failure(code: str, message: str) -> RobotIOResponse:
    return RobotIOResponse(error=RobotIOError(code, message))
