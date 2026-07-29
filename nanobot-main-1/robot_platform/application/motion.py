"""Confirmed single-motion execution use case."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Protocol

from .confirmed_execution import (
    ConfirmedExecutionPlatformPort as RobotMotionPlatformPort,
)
from .confirmed_execution import (
    ConfirmedExecutionPolicy,
    ConfirmedPlanExecutionEngine,
    public_execution_metadata,
)
from .confirmed_execution import (
    ConfirmedPendingPlanPort as MotionPendingPlanPort,
)
from .confirmed_execution import (
    ConfirmedPermitStorePort as MotionPermitStorePort,
)
from .confirmed_execution import (
    ConfirmedSessionGatePort as MotionSessionGatePort,
)
from .principal import AuthenticatedPrincipal

MOTION_COMMANDS = frozenset({"linear_move", "linear_path"})


@dataclass(frozen=True)
class RobotMotionExecutionCommand:
    principal: AuthenticatedPrincipal
    plan_id: str
    confirmation_receipt: str

    def __post_init__(self) -> None:
        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("RobotMotionExecutionCommand requires AuthenticatedPrincipal")
        if not str(self.plan_id).strip() or not str(self.confirmation_receipt).strip():
            raise ValueError("RobotMotionExecutionCommand requires plan ID and receipt")


@dataclass(frozen=True)
class RobotMotionError:
    code: str
    message: str

    def __post_init__(self) -> None:
        if not self.code.strip() or not self.message.strip():
            raise ValueError("RobotMotionError requires code and message")


@dataclass(frozen=True)
class RobotMotionResponse:
    payload: dict[str, Any] | None = None
    error: RobotMotionError | None = None
    replayed: bool = False

    def __post_init__(self) -> None:
        if (self.payload is None) == (self.error is None):
            raise ValueError("RobotMotionResponse requires exactly one of payload or error")
        if self.payload is not None and not isinstance(self.payload, dict):
            raise TypeError("RobotMotionResponse payload must be a dict")
        if self.error is not None and self.replayed:
            raise ValueError("Failed motion response cannot be replayed")

    @property
    def ok(self) -> bool:
        return self.error is None


class RobotMotionApplicationPort(Protocol):
    def execute(self, command: RobotMotionExecutionCommand) -> RobotMotionResponse: ...


_MOTION_POLICY = ConfirmedExecutionPolicy(
    family="motion",
    title="Motion",
    subject="motion",
    plan_description="a single-motion plan",
    allowed_commands=MOTION_COMMANDS,
    validate_parameters=lambda _command, _parameters: True,
    public_data=lambda _command, _parameters, raw: _public_motion_data(raw),
    success_message="Robot motion completed.",
    failure_message="Robot motion did not complete; reconcile controller state.",
)


class RobotMotionApplicationService:
    """Motion-specific DTO boundary over the shared confirmed execution engine."""

    def __init__(
        self,
        platform: RobotMotionPlatformPort | None = None,
        pending_plans: MotionPendingPlanPort | None = None,
        session_gates: MotionSessionGatePort | None = None,
        permits: MotionPermitStorePort | None = None,
        *,
        robot_id: str = "",
        controller_id: str = "",
        product_profile_version: str = "",
        capability_version: str = "",
        deployment_instance_id: str = "",
        core_version: str = "",
        engine: ConfirmedPlanExecutionEngine | None = None,
    ) -> None:
        if engine is not None:
            if any(value is not None for value in (
                platform, pending_plans, session_gates, permits,
            )):
                raise ValueError("motion engine cannot be combined with direct dependencies")
            self._engine = engine
            return
        if any(value is None for value in (
            platform, pending_plans, session_gates, permits,
        )):
            raise ValueError("RobotMotionApplicationService requires execution dependencies")
        self._engine = ConfirmedPlanExecutionEngine(
            platform, pending_plans, session_gates, permits,
            robot_id=robot_id,
            controller_id=controller_id,
            product_profile_version=product_profile_version,
            capability_version=capability_version,
            deployment_instance_id=deployment_instance_id,
            core_version=core_version,
        )

    def execute(self, command: RobotMotionExecutionCommand) -> RobotMotionResponse:
        if not isinstance(command, RobotMotionExecutionCommand):
            return _failure("invalid_motion_request", "Motion request is invalid.")
        outcome = self._engine.execute(
            principal=command.principal,
            plan_id=command.plan_id,
            confirmation_receipt=command.confirmation_receipt,
            policy=_MOTION_POLICY,
        )
        if outcome.payload is not None:
            return RobotMotionResponse(
                payload=outcome.payload, replayed=outcome.replayed,
            )
        return _failure(
            _public_error_code("motion", str(outcome.error_key)),
            str(outcome.error_message),
        )

    # Compatibility properties keep existing tests and adapters able to inject
    # faulting ports while the shared engine remains the single source of state.
    @property
    def _platform(self) -> RobotMotionPlatformPort:
        return self._engine.platform

    @_platform.setter
    def _platform(self, value: RobotMotionPlatformPort) -> None:
        self._engine.platform = value

    @property
    def _pending_plans(self) -> MotionPendingPlanPort:
        return self._engine.pending_plans

    @_pending_plans.setter
    def _pending_plans(self, value: MotionPendingPlanPort) -> None:
        self._engine.pending_plans = value

    @property
    def _permits(self) -> MotionPermitStorePort:
        return self._engine.permits

    @_permits.setter
    def _permits(self, value: MotionPermitStorePort) -> None:
        self._engine.permits = value

    @property
    def _session_gates(self) -> MotionSessionGatePort:
        return self._engine.session_gates

    @_session_gates.setter
    def _session_gates(self, value: MotionSessionGatePort) -> None:
        self._engine.session_gates = value

    @property
    def _robot_id(self) -> str:
        return self._engine.robot_id

    @_robot_id.setter
    def _robot_id(self, value: str) -> None:
        self._engine.robot_id = value

    @property
    def _controller_id(self) -> str:
        return self._engine.controller_id

    @_controller_id.setter
    def _controller_id(self, value: str) -> None:
        self._engine.controller_id = value

    @property
    def _product_profile_version(self) -> str:
        return self._engine.product_profile_version

    @_product_profile_version.setter
    def _product_profile_version(self, value: str) -> None:
        self._engine.product_profile_version = value

    @property
    def _capability_version(self) -> str:
        return self._engine.capability_version

    @_capability_version.setter
    def _capability_version(self, value: str) -> None:
        self._engine.capability_version = value

    @property
    def _deployment_instance_id(self) -> str:
        return self._engine.deployment_instance_id

    @_deployment_instance_id.setter
    def _deployment_instance_id(self, value: str) -> None:
        self._engine.deployment_instance_id = value

    @property
    def _core_version(self) -> str:
        return self._engine.core_version

    @_core_version.setter
    def _core_version(self, value: str) -> None:
        self._engine.core_version = value


def _public_error_code(family: str, key: str) -> str:
    if key == "invalid_request":
        return f"invalid_{family}_request"
    if key == "unsupported_plan":
        return f"unsupported_{family}_plan"
    return f"{family}_{key}"


def _public_motion_data(raw: Any) -> dict[str, Any]:
    public = public_execution_metadata(raw)
    if not isinstance(raw, dict):
        return public
    for key in ("expected_pose", "actual_pose"):
        pose = _public_numeric_vector(raw.get(key), maximum=6)
        if pose is not None:
            public[key] = pose
    states = raw.get("segment_states")
    if (
        isinstance(states, list)
        and len(states) <= 100
        and all(
            isinstance(item, str)
            and re.fullmatch(r"[a-z][a-z0-9_]{0,95}", item) is not None
            for item in states
        )
    ):
        public["segment_states"] = list(states)
    return public


def _public_numeric_vector(raw: Any, *, maximum: int) -> list[float] | None:
    if not isinstance(raw, list) or not 1 <= len(raw) <= maximum:
        return None
    values: list[float] = []
    for item in raw:
        if not isinstance(item, (int, float)) or isinstance(item, bool):
            return None
        number = float(item)
        if not math.isfinite(number):
            return None
        values.append(number)
    return values


def _failure(code: str, message: str) -> RobotMotionResponse:
    return RobotMotionResponse(error=RobotMotionError(code, message))
