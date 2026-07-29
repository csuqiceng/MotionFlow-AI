"""Engineer-only library transfer and position-maintenance use cases."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol

from .principal import AuthenticatedPrincipal


@dataclass(frozen=True)
class RobotMaintenanceError:
    code: str
    message: str


@dataclass(frozen=True)
class RobotMaintenanceResponse:
    payload: dict[str, Any] | None = None
    error: RobotMaintenanceError | None = None

    def __post_init__(self) -> None:
        if (self.payload is None) == (self.error is None):
            raise ValueError("RobotMaintenanceResponse requires payload or error")

    @property
    def ok(self) -> bool:
        return self.error is None


class RobotPositionMaintenancePort(Protocol):
    def preview(self, *, actor: str) -> dict[str, Any]: ...
    def apply(self, *, actor: str) -> dict[str, Any]: ...


class RobotPositionMaintenanceApplicationService:
    def __init__(self, maintenance: RobotPositionMaintenancePort) -> None:
        self._maintenance = maintenance

    def execute(
        self, principal: AuthenticatedPrincipal, action: str,
    ) -> RobotMaintenanceResponse:
        if not isinstance(principal, AuthenticatedPrincipal):
            return _failure("invalid_request", "Maintenance principal is invalid.")
        if principal.role != "engineer":
            return _failure("library_forbidden", "Engineer role is required.")
        if action not in {"preview", "apply"}:
            return _failure("invalid_action", "Maintenance action is invalid.")
        actor = f"{principal.auth_source}:{principal.actor_id}"
        try:
            result = (
                self._maintenance.preview(actor=actor)
                if action == "preview"
                else self._maintenance.apply(actor=actor)
            )
            if not isinstance(result, dict):
                raise TypeError("maintenance result is invalid")
            payload = _position_maintenance_payload(result, action)
        except (ValueError, TypeError):
            return _failure("invalid_positions", "Position registry is invalid.")
        except Exception:
            return _failure(
                "position_state_unavailable", "Position state is unavailable.",
            )
        return RobotMaintenanceResponse(payload=payload)


class RobotLibraryTransferPort(Protocol):
    def export(self) -> dict[str, Any]: ...
    def import_payload(
        self, payload: dict[str, Any], *, strategy: str, actor: str,
    ) -> dict[str, Any]: ...


class RobotLibraryTransferApplicationService:
    def __init__(self, transfer: RobotLibraryTransferPort) -> None:
        self._transfer = transfer

    def export(
        self, principal: AuthenticatedPrincipal,
    ) -> RobotMaintenanceResponse:
        forbidden = self._authorize(principal)
        if forbidden is not None:
            return forbidden
        try:
            payload = deepcopy(self._transfer.export())
            if not isinstance(payload, dict):
                raise TypeError("transfer result is invalid")
        except Exception:
            return _failure("library_state_unavailable", "Library state is unavailable.")
        return RobotMaintenanceResponse(payload=payload)

    def import_payload(
        self,
        principal: AuthenticatedPrincipal,
        payload: Any,
        *,
        strategy: str,
    ) -> RobotMaintenanceResponse:
        forbidden = self._authorize(principal)
        if forbidden is not None:
            return forbidden
        if not isinstance(payload, dict):
            return _failure("invalid_request", "payload must be an object.")
        if strategy not in {"skip", "rename", "overwrite-draft-only"}:
            return _failure("invalid_request", "transfer strategy is invalid.")
        try:
            result = deepcopy(self._transfer.import_payload(
                deepcopy(payload),
                strategy=strategy,
                actor=f"{principal.auth_source}:{principal.actor_id}",
            ))
            if not isinstance(result, dict):
                raise TypeError("transfer result is invalid")
        except ValueError:
            return _failure("invalid_transfer", "Library transfer is invalid.")
        except Exception:
            return _failure("library_state_unavailable", "Library state is unavailable.")
        errors = result.get("errors")
        if isinstance(errors, list) and errors:
            return _failure("invalid_transfer", "Library transfer is invalid.")
        return RobotMaintenanceResponse(payload=result)

    @staticmethod
    def _authorize(
        principal: AuthenticatedPrincipal,
    ) -> RobotMaintenanceResponse | None:
        if not isinstance(principal, AuthenticatedPrincipal):
            return _failure("invalid_request", "Transfer principal is invalid.")
        if principal.role != "engineer":
            return _failure("library_forbidden", "Engineer role is required.")
        return None


def _failure(code: str, message: str) -> RobotMaintenanceResponse:
    return RobotMaintenanceResponse(error=RobotMaintenanceError(code, message))


def _position_maintenance_payload(
    result: dict[str, Any], action: str,
) -> dict[str, Any]:
    if action == "preview":
        return {
            "candidate_count": _count(result, "candidate_count"),
            "candidate_names": _names(result, "candidate_names"),
            "preserved_referenced_count": _count(
                result, "preserved_referenced_count",
            ),
            "preserved_referenced_names": _names(
                result, "preserved_referenced_names",
            ),
        }
    backup_id = result.get("backup_id")
    if backup_id is not None and (
        not isinstance(backup_id, str)
        or not backup_id
        or len(backup_id) > 255
        or "/" in backup_id
        or "\\" in backup_id
        or backup_id in {".", ".."}
    ):
        raise TypeError("backup id is invalid")
    return {
        "removed_count": _count(result, "removed_count"),
        "removed_names": _names(result, "removed_names"),
        "preserved_referenced_count": _count(
            result, "preserved_referenced_count",
        ),
        "preserved_referenced_names": _names(
            result, "preserved_referenced_names",
        ),
        "backup_id": backup_id,
    }


def _count(result: dict[str, Any], key: str) -> int:
    value = result.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise TypeError(f"{key} is invalid")
    return value


def _names(result: dict[str, Any], key: str) -> list[str]:
    value = result.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise TypeError(f"{key} is invalid")
    return list(value)
