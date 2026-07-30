"""Confirmed robot-library mutation use cases."""

from __future__ import annotations

import math
import secrets
import time
from copy import deepcopy
from dataclasses import dataclass
from threading import RLock
from typing import Any, Protocol

from .principal import AuthenticatedPrincipal


@dataclass(frozen=True)
class RobotLibraryPreviewCommand:
    principal: AuthenticatedPrincipal
    operation: str
    resource_type: str
    payload: dict[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("RobotLibraryPreviewCommand requires AuthenticatedPrincipal")
        if not isinstance(self.payload, dict):
            raise TypeError("RobotLibraryPreviewCommand payload must be a dict")


@dataclass(frozen=True)
class RobotLibraryConfirmCommand:
    principal: AuthenticatedPrincipal
    confirmation_token: str

    def __post_init__(self) -> None:
        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("RobotLibraryConfirmCommand requires AuthenticatedPrincipal")


@dataclass(frozen=True)
class RobotLibraryError:
    code: str
    message: str


@dataclass(frozen=True)
class RobotLibraryResponse:
    payload: dict[str, Any] | None = None
    error: RobotLibraryError | None = None
    confirmation_issued: bool = False
    mutation_applied: bool = False

    def __post_init__(self) -> None:
        if (self.payload is None) == (self.error is None):
            raise ValueError("RobotLibraryResponse requires payload or error")
        if self.error is not None and (self.confirmation_issued or self.mutation_applied):
            raise ValueError("Failed library response cannot report success")
        if self.confirmation_issued and self.mutation_applied:
            raise ValueError("Library response cannot preview and apply together")

    @property
    def ok(self) -> bool:
        return self.error is None


class RobotLibraryMutationPort(Protocol):
    def create(
        self, resource_type: str, payload: dict[str, Any], *, actor: str,
    ) -> dict[str, Any]: ...
    def update_position(
        self, payload: dict[str, Any], *, actor: str,
    ) -> dict[str, Any]: ...
    def delete_position(
        self, payload: dict[str, Any], *, actor: str,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class PendingLibraryMutation:
    principal: AuthenticatedPrincipal
    operation: str
    resource_type: str
    payload: dict[str, Any]
    expires_at: float


class LibraryConfirmationStorePort(Protocol):
    def issue(
        self,
        principal: AuthenticatedPrincipal,
        operation: str,
        resource_type: str,
        payload: dict[str, Any],
    ) -> tuple[str, float]: ...
    def claim(
        self, token: str, principal: AuthenticatedPrincipal,
    ) -> tuple[str, PendingLibraryMutation | None]: ...


class InMemoryLibraryConfirmationStore:
    """Per-container, one-use confirmation state with atomic actor binding."""

    def __init__(self, *, ttl_sec: float = 300.0) -> None:
        self._ttl_sec = max(float(ttl_sec), 1.0)
        self._lock = RLock()
        self._pending: dict[str, PendingLibraryMutation] = {}

    def issue(
        self,
        principal: AuthenticatedPrincipal,
        operation: str,
        resource_type: str,
        payload: dict[str, Any],
    ) -> tuple[str, float]:
        token = secrets.token_urlsafe(24)
        expires_at = time.monotonic() + self._ttl_sec
        pending = PendingLibraryMutation(
            principal=principal,
            operation=operation,
            resource_type=resource_type,
            payload=deepcopy(payload),
            expires_at=expires_at,
        )
        with self._lock:
            self._pending[token] = pending
        return token, self._ttl_sec

    def claim(
        self, token: str, principal: AuthenticatedPrincipal,
    ) -> tuple[str, PendingLibraryMutation | None]:
        with self._lock:
            pending = self._pending.get(str(token))
            if pending is None:
                return "expired", None
            if pending.expires_at <= time.monotonic():
                self._pending.pop(str(token), None)
                return "expired", None
            if pending.principal != principal:
                return "forbidden", None
            self._pending.pop(str(token), None)
            return "claimed", PendingLibraryMutation(
                principal=pending.principal,
                operation=pending.operation,
                resource_type=pending.resource_type,
                payload=deepcopy(pending.payload),
                expires_at=pending.expires_at,
            )


class RobotLibraryApplicationPort(Protocol):
    def preview(
        self, command: RobotLibraryPreviewCommand,
    ) -> RobotLibraryResponse: ...
    def confirm(
        self, command: RobotLibraryConfirmCommand,
    ) -> RobotLibraryResponse: ...


class RobotLibraryApplicationService:
    def __init__(
        self,
        mutations: RobotLibraryMutationPort,
        confirmations: LibraryConfirmationStorePort,
    ) -> None:
        self._mutations = mutations
        self._confirmations = confirmations

    def preview(self, command: RobotLibraryPreviewCommand) -> RobotLibraryResponse:
        if not isinstance(command, RobotLibraryPreviewCommand):
            return _failure("invalid_library_request", "Library request is invalid.")
        if command.principal.role not in {"operator", "engineer"}:
            return _failure("library_forbidden", "Operator role is required.")
        operation = str(command.operation).strip()
        resource_type = str(command.resource_type).strip()
        if operation not in {"create", "update", "delete"}:
            return _failure("library_preview_invalid", "Library operation is invalid.")
        if resource_type not in {"position", "command", "flow"}:
            return _failure("library_preview_invalid", "Library resource type is invalid.")
        if operation in {"update", "delete"}:
            if command.principal.role != "engineer":
                return _failure(
                    "library_forbidden",
                    "Only engineers may update or delete library resources.",
                )
            if resource_type != "position":
                return _failure(
                    "library_preview_invalid",
                    "Only positions support this confirmed mutation.",
                )
        try:
            payload = _json_snapshot(command.payload)
        except (TypeError, ValueError):
            return _failure("library_preview_invalid", "Library payload is invalid.")
        if not isinstance(payload.get("name"), str) or not payload["name"].strip():
            return _failure("library_preview_invalid", "Library resource name is required.")
        if operation == "create" and resource_type == "flow":
            from robot_platform.flow.schema import validate_flow_draft_payload

            errors = validate_flow_draft_payload(payload)
            if errors:
                return _failure(
                    "library_preview_invalid",
                    "Library flow is invalid: " + " ".join(errors),
                )
        try:
            token, ttl = self._confirmations.issue(
                command.principal, operation, resource_type, payload,
            )
        except Exception:
            return _failure(
                "library_state_unavailable", "Library confirmation is unavailable.",
            )
        return RobotLibraryResponse(
            payload={
                "state": "library_save_preview",
                "operation": operation,
                "resource_type": resource_type,
                "preview": payload,
                "confirmation_token": token,
                "expires_in_seconds": ttl,
            },
            confirmation_issued=True,
        )

    def confirm(self, command: RobotLibraryConfirmCommand) -> RobotLibraryResponse:
        if not isinstance(command, RobotLibraryConfirmCommand):
            return _failure("invalid_library_request", "Library request is invalid.")
        if command.principal.role not in {"operator", "engineer"}:
            return _failure("library_forbidden", "Operator role is required.")
        try:
            state, pending = self._confirmations.claim(
                command.confirmation_token, command.principal,
            )
        except Exception:
            return _failure(
                "library_state_unavailable", "Library confirmation is unavailable.",
            )
        if state == "forbidden":
            return _failure(
                "library_confirmation_forbidden",
                "Library confirmation belongs to another principal.",
            )
        if state != "claimed" or pending is None:
            return _failure(
                "library_confirmation_expired",
                "Library confirmation is missing or expired.",
            )
        actor = (
            f"{pending.principal.auth_source}:"
            f"{pending.principal.role}:{pending.principal.actor_id}"
        )
        try:
            if pending.operation == "create":
                result = self._mutations.create(
                    pending.resource_type, deepcopy(pending.payload), actor=actor,
                )
            elif pending.operation == "update":
                result = self._mutations.update_position(
                    deepcopy(pending.payload), actor=actor,
                )
            else:
                result = self._mutations.delete_position(
                    deepcopy(pending.payload), actor=actor,
                )
            if not isinstance(result, dict):
                raise TypeError("library mutation result is invalid")
            public = {
                "operation": pending.operation,
                "resource_type": pending.resource_type,
                "name": str(pending.payload["name"]).strip(),
            }
            if pending.resource_type == "position":
                if pending.operation == "delete":
                    public["deleted"] = {"name": public["name"]}
                else:
                    pose = pending.payload.get("pose")
                    if not isinstance(pose, dict):
                        raise TypeError("position pose is invalid")
                    axes = ("x", "y", "z", "rx", "ry", "rz")
                    values = [float(pose[axis]) for axis in axes]
                    if any(not math.isfinite(value) for value in values):
                        raise TypeError("position pose is invalid")
                    public["position"] = {
                        "name": public["name"],
                        "pose": values,
                    }
        except ValueError:
            return _failure("library_save_invalid", "Library mutation is invalid.")
        except Exception:
            return _failure("library_state_unavailable", "Library state is unavailable.")
        return RobotLibraryResponse(
            payload={"state": "library_saved", **public},
            mutation_applied=True,
        )


def _json_snapshot(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        raise ValueError("payload is too deep")
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        if len(value) > 8192:
            raise ValueError("string is too long")
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("number is not finite")
        return value
    if isinstance(value, list):
        if len(value) > 1000:
            raise ValueError("list is too long")
        return [_json_snapshot(item, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        if len(value) > 100:
            raise ValueError("object is too large")
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 256:
                raise ValueError("object key is invalid")
            result[key] = _json_snapshot(item, depth=depth + 1)
        return result
    raise TypeError("payload is not JSON-compatible")


def _failure(code: str, message: str) -> RobotLibraryResponse:
    return RobotLibraryResponse(error=RobotLibraryError(code, message))
