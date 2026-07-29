"""Read-only position and published-library lookup use cases."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Protocol

from .principal import AuthenticatedPrincipal


@dataclass(frozen=True)
class RobotPositionQuery:
    principal: AuthenticatedPrincipal
    action: str
    name: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("RobotPositionQuery requires AuthenticatedPrincipal")


@dataclass(frozen=True)
class RobotPositionError:
    code: str
    message: str


@dataclass(frozen=True)
class RobotPositionResponse:
    payload: dict[str, Any] | None = None
    error: RobotPositionError | None = None

    def __post_init__(self) -> None:
        if (self.payload is None) == (self.error is None):
            raise ValueError("RobotPositionResponse requires payload or error")

    @property
    def ok(self) -> bool:
        return self.error is None


class RobotPositionCatalogPort(Protocol):
    def positions(self) -> list[dict[str, Any]]: ...
    def position_commands(self) -> list[dict[str, Any]]: ...
    def flows(self) -> list[dict[str, Any]]: ...
    def find(self, name: str) -> tuple[str, dict[str, Any]] | None: ...
    def resolve(self, name: str) -> dict[str, float] | None: ...


class RobotPositionApplicationPort(Protocol):
    def query(self, query: RobotPositionQuery) -> RobotPositionResponse: ...


class RobotPositionApplicationService:
    def __init__(self, catalog: RobotPositionCatalogPort) -> None:
        self._catalog = catalog

    def query(self, query: RobotPositionQuery) -> RobotPositionResponse:
        if not isinstance(query, RobotPositionQuery):
            return _failure("invalid_position_request", "Position request is invalid.")
        if query.principal.role not in {"operator", "engineer"}:
            return _failure("position_forbidden", "Operator role is required.")
        action = str(query.action).strip()
        name = str(query.name).strip()
        try:
            if action == "list":
                positions = [_position(item) for item in self._catalog.positions()]
                commands = [
                    _position_command(item)
                    for item in self._catalog.position_commands()
                ]
                flows = [_flow_summary(item) for item in self._catalog.flows()]
                return RobotPositionResponse(payload={
                    "state": "position_list",
                    "positions": positions,
                    "position_commands": commands,
                    "flows": flows,
                    "count": len(positions) + len(commands) + len(flows),
                })
            if action not in {"get", "resolve"} or not name:
                return _failure(
                    "invalid_position_request", "Position action or name is invalid.",
                )
            if action == "get":
                found = self._catalog.find(name)
                if found is None:
                    return _failure(
                        "position_not_found", "Position or library resource was not found.",
                    )
                resource_type, resource = found
                if resource_type == "position":
                    public = _position(resource)
                elif resource_type == "position_command":
                    public = _position_command(resource)
                elif resource_type == "flow":
                    public = _flow_summary(resource)
                else:
                    raise ValueError("unsupported catalog resource")
                return RobotPositionResponse(payload={
                    "state": f"{resource_type}_found",
                    "resource_type": resource_type,
                    resource_type: public,
                })
            found = self._catalog.find(name)
            if found is not None and found[0] == "flow":
                return _failure(
                    "position_not_single_pose",
                    "A flow cannot be resolved as one position.",
                )
            pose = self._catalog.resolve(name)
            if pose is None:
                return _failure("position_not_found", "Position was not found.")
            return RobotPositionResponse(payload={
                "state": "position_resolved", "name": name, "pose": _pose_dict(pose),
            })
        except Exception:
            return _failure("position_state_unavailable", "Position state is unavailable.")


def _position(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("invalid position")
    name = _name(raw.get("name"))
    pose = _pose_list(raw.get("pose"))
    speed = raw.get("spd", raw.get("speed_pct", 50.0))
    if not _finite_number(speed):
        raise ValueError("invalid position speed")
    return {"name": name, "pose": pose, "spd": float(speed)}


def _position_command(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("invalid position command")
    aliases = raw.get("aliases", [])
    if not isinstance(aliases, list) or not all(isinstance(item, str) for item in aliases):
        raise ValueError("invalid position aliases")
    return {
        "id": _name(raw.get("id", raw.get("command_id"))),
        "name": _name(raw.get("name")),
        "aliases": [item[:256] for item in aliases[:100]],
        "command_id": _name(raw.get("command_id", raw.get("id"))),
        "func_id": 108,
        "pose": _pose_dict(raw.get("pose")),
    }


def _flow_summary(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("invalid flow summary")
    steps = raw.get("steps", [])
    if not isinstance(steps, list):
        raise ValueError("invalid flow steps")
    description = raw.get("description", "")
    if not isinstance(description, str):
        description = ""
    return {
        "flow_id": _name(raw.get("flow_id")),
        "name": _name(raw.get("name")),
        "description": description[:4096],
        "step_count": len(steps),
    }


def _pose_dict(raw: Any) -> dict[str, float]:
    axes = ("x", "y", "z", "rx", "ry", "rz")
    if not isinstance(raw, dict) or set(raw) != set(axes):
        raise ValueError("invalid pose")
    result = {axis: float(raw[axis]) for axis in axes}
    if not all(math.isfinite(value) for value in result.values()):
        raise ValueError("invalid pose")
    return result


def _pose_list(raw: Any) -> list[float]:
    if not isinstance(raw, (list, tuple)) or len(raw) != 6:
        raise ValueError("invalid pose")
    values = [float(value) for value in raw]
    if not all(math.isfinite(value) for value in values):
        raise ValueError("invalid pose")
    return values


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("missing name")
    return value.strip()[:256]


def _failure(code: str, message: str) -> RobotPositionResponse:
    return RobotPositionResponse(error=RobotPositionError(code, message))
