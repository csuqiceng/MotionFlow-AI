"""Engineer-scoped, read-only diagnostics projection."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol

from .principal import AuthenticatedPrincipal
from .status import RobotStatusApplicationPort


@dataclass(frozen=True)
class RobotDiagnosticsQuery:
    principal: AuthenticatedPrincipal

    def __post_init__(self) -> None:
        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("RobotDiagnosticsQuery requires AuthenticatedPrincipal")


@dataclass(frozen=True)
class RobotDiagnosticsError:
    code: str
    message: str

    def __post_init__(self) -> None:
        if not self.code.strip() or not self.message.strip():
            raise ValueError("RobotDiagnosticsError requires code and message")


@dataclass(frozen=True)
class RobotDiagnosticsResponse:
    payload: dict[str, Any] | None = None
    error: RobotDiagnosticsError | None = None

    def __post_init__(self) -> None:
        if (self.payload is None) == (self.error is None):
            raise ValueError(
                "RobotDiagnosticsResponse requires exactly one of payload or error"
            )
        if self.payload is not None and not isinstance(self.payload, dict):
            raise TypeError("RobotDiagnosticsResponse payload must be a dict")

    @property
    def ok(self) -> bool:
        return self.payload is not None


class RobotDiagnosticsApplicationPort(Protocol):
    def query(self, request: RobotDiagnosticsQuery) -> RobotDiagnosticsResponse: ...


class RobotDiagnosticsApplicationService:
    def __init__(self, status: RobotStatusApplicationPort) -> None:
        self._status = status

    def query(self, request: RobotDiagnosticsQuery) -> RobotDiagnosticsResponse:
        if request.principal.role != "engineer":
            return RobotDiagnosticsResponse(error=RobotDiagnosticsError(
                code="engineer_required", message="Engineer role required.",
            ))
        try:
            status = self._status.query()
            status_payload = getattr(status, "payload", None)
            if (
                not bool(getattr(status, "ok", False))
                or not isinstance(status_payload, dict)
            ):
                raise ValueError("status response is unavailable")
            snapshot = deepcopy(status_payload)
            data = snapshot.get("data", {})
            if not isinstance(data, dict):
                data = {}
            state = data.get("robot_state", {})
            if not isinstance(state, dict):
                state = {}
            mode = str(state.get("mode", "unknown"))
            return RobotDiagnosticsResponse(payload={"ok": True, "data": {
                "connection": {
                    "mode": mode,
                    "real_device": bool(state.get("connected_real_device", False)),
                },
                "execution_mode": str(data.get("execution_mode", "dry_run_only")),
                "position": (
                    state.get("axes_mm", {})
                    if isinstance(state.get("axes_mm"), dict) else {}
                ),
                "io": data.get("io", {}) if isinstance(data.get("io"), dict) else {},
                "alarms": (
                    state.get("alarms", [])
                    if isinstance(state.get("alarms"), list) else []
                ),
                "task": mode,
                "command_echo": data.get("command_echo", {}),
            }})
        except Exception:
            return RobotDiagnosticsResponse(error=RobotDiagnosticsError(
                code="robot_status_unavailable", message="Robot status unavailable.",
            ))
