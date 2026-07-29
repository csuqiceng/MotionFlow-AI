"""Vendor-neutral read-only robot status use case."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol

from robot_platform.models import ControllerCapabilities


@dataclass(frozen=True)
class RobotStatusQuery:
    correlation_id: str = ""


@dataclass(frozen=True)
class RobotStatusError:
    code: str
    message: str

    def __post_init__(self) -> None:
        if not self.code.strip() or not self.message.strip():
            raise ValueError("RobotStatusError requires non-empty code and message")


@dataclass(frozen=True)
class RobotStatusResponse:
    payload: dict[str, Any] | None = None
    error: RobotStatusError | None = None

    def __post_init__(self) -> None:
        has_payload = self.payload is not None
        has_error = self.error is not None
        if has_payload == has_error:
            raise ValueError("RobotStatusResponse requires exactly one of payload or error")
        if has_payload and not isinstance(self.payload, dict):
            raise TypeError("RobotStatusResponse payload must be a dict")

    @property
    def ok(self) -> bool:
        return self.payload is not None


class RobotStatusReaderPort(Protocol):
    def get_status(self) -> dict[str, Any]: ...


class RobotStatusApplicationPort(Protocol):
    def query(self, request: RobotStatusQuery | None = None) -> RobotStatusResponse: ...


class RobotStatusApplicationService:
    """Read status once, sanitize failures, and stabilize the public v1 shape."""

    def __init__(self, reader: RobotStatusReaderPort) -> None:
        self._reader = reader

    def query(self, request: RobotStatusQuery | None = None) -> RobotStatusResponse:
        del request
        try:
            payload = self._reader.get_status()
            normalized = deepcopy(_with_public_capabilities(payload))
        except Exception:
            return RobotStatusResponse(error=RobotStatusError(
                code="robot_status_unavailable",
                message="robot status unavailable",
            ))
        return RobotStatusResponse(payload=normalized)


def _with_public_capabilities(result: dict[str, Any]) -> dict[str, Any]:
    data = result.get("data")
    if not isinstance(data, dict) or isinstance(data.get("capabilities"), dict):
        return result
    legacy = data.get("controller_capabilities")
    if not isinstance(legacy, dict):
        return result
    primitives = legacy.get("motion_primitives", ())
    if not isinstance(primitives, (list, tuple)):
        primitives = ()
    public = ControllerCapabilities(
        vendor=str(legacy.get("vendor", "")),
        supports_state_read=bool(legacy.get("supports_state_read", True)),
        supports_real_writes=bool(legacy.get("supports_real_writes", False)),
        motion_primitives=tuple(str(item) for item in primitives),
    ).to_public_dict()
    return {**result, "data": {**data, "capabilities": public}}
