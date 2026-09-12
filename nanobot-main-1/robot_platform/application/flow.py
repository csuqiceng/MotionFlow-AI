"""Read and dry-run published robot flows through one Application boundary."""

from __future__ import annotations

import math
import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from .dry_run import RobotDryRunApplicationPort
from .principal import AuthenticatedPrincipal


@dataclass(frozen=True)
class RobotFlowQuery:
    principal: AuthenticatedPrincipal
    action: str
    name: str = ""
    alias: str = ""
    expected_snapshot_hash: str = ""


@dataclass(frozen=True)
class RobotFlowError:
    code: str
    message: str


@dataclass(frozen=True)
class RobotFlowResponse:
    payload: dict[str, Any] | None = None
    error: RobotFlowError | None = None

    def __post_init__(self) -> None:
        if (self.payload is None) == (self.error is None):
            raise ValueError("RobotFlowResponse requires payload or error")

    @property
    def ok(self) -> bool:
        return self.error is None


class RobotFlowCatalogPort(Protocol):
    def list_entries(self) -> list[Any]: ...
    def resolve(self, name: str, *, alias: str = "") -> tuple[str, Any | None]: ...


class RobotFlowApplicationPort(Protocol):
    def query(
        self,
        query: RobotFlowQuery,
        *,
        on_resolved: Callable[[dict[str, Any]], None] | None = None,
        on_step: Callable[[int, str, dict[str, Any] | None], None] | None = None,
    ) -> RobotFlowResponse: ...


class RobotFlowApplicationService:
    def __init__(
        self,
        catalog: RobotFlowCatalogPort,
        dry_run: RobotDryRunApplicationPort,
    ) -> None:
        self._catalog = catalog
        self._dry_run = dry_run

    def query(
        self,
        query: RobotFlowQuery,
        *,
        on_resolved: Callable[[dict[str, Any]], None] | None = None,
        on_step: Callable[[int, str, dict[str, Any] | None], None] | None = None,
    ) -> RobotFlowResponse:
        if not isinstance(query, RobotFlowQuery):
            return _failure("invalid_flow_request", "Flow request is invalid.")
        if query.principal.role not in {"operator", "engineer"}:
            return _failure("flow_forbidden", "Operator role is required.")
        action = str(query.action).strip()
        if action == "list":
            return self._list()
        if action not in {"get", "preview"}:
            return _failure("unknown_flow_action", "Flow action is invalid.")
        name = str(query.name).strip()
        alias = str(query.alias).strip()
        if not name and not alias:
            return _failure("flow_not_found", "Flow name or alias is required.")
        try:
            state, entry = self._catalog.resolve(name, alias=alias)
        except Exception:
            return _failure("flow_state_unavailable", "Flow state is unavailable.")
        if state == "alias_not_found":
            return _failure("flow_alias_not_found", "Flow alias was not found.")
        if state != "found" or entry is None:
            return _failure("flow_not_found", "Flow was not found.")
        try:
            public = _public_flow(entry)
        except Exception:
            return _failure("flow_state_unavailable", "Flow state is unavailable.")
        if (
            query.expected_snapshot_hash
            and query.expected_snapshot_hash != _flow_snapshot_hash(public)
        ):
            return _failure(
                "flow_snapshot_changed",
                "Flow changed after the Tool effect was frozen; retry with a new request.",
            )
        if action == "get":
            return RobotFlowResponse(payload={"flow": public})
        if on_resolved is not None:
            try:
                on_resolved(deepcopy(public))
            except Exception:
                pass
        preview = self._dry_run.preview_flow_entry(deepcopy(entry), on_step=on_step)
        if not preview.ok or not isinstance(preview.payload, dict):
            error = preview.error
            return _failure(
                getattr(error, "code", "dry_run_unavailable"),
                getattr(error, "message", "Robot dry-run is unavailable."),
            )
        return RobotFlowResponse(payload={
            "flow": public,
            "result": deepcopy(preview.payload),
        })

    def _list(self) -> RobotFlowResponse:
        try:
            flows = [_public_flow(entry) for entry in self._catalog.list_entries()]
        except Exception:
            return _failure("flow_state_unavailable", "Flow state is unavailable.")
        return RobotFlowResponse(payload={"flows": flows, "count": len(flows)})


def _public_flow(entry: Any) -> dict[str, Any]:
    raw = entry.to_dict()
    if not isinstance(raw, dict):
        raise TypeError("flow is invalid")
    steps = raw.get("steps")
    if not isinstance(steps, list):
        raise TypeError("flow steps are invalid")
    result = {
        "name": _text(raw.get("name"), required=True),
        "flow_id": _text(raw.get("flow_id")),
        "description": _text(raw.get("description")),
        "steps": [_public_step(step) for step in steps],
        "step_delay_ms": _finite_number(raw.get("step_delay_ms", 1000)),
        "rehearsal_spd": _finite_number(raw.get("rehearsal_spd", 20)),
        "confirmed": bool(raw.get("confirmed", False)),
        "version": _integer(raw.get("version", 1)),
        "state": _text(raw.get("state")),
    }
    if raw.get("node_graph") is not None:
        result["node_graph"] = _json_value(raw["node_graph"])
    return result


def _public_step(step: Any) -> dict[str, Any]:
    if not isinstance(step, dict):
        raise TypeError("flow step is invalid")
    return {
        "step_id": _integer(step.get("step_id")),
        "action": _text(step.get("action")),
        "func_id": _integer(step.get("func_id")),
        "params": _json_value(step.get("params", {})),
        "position_name": (
            _text(step.get("position_name"))
            if step.get("position_name") is not None else None
        ),
        "spd_pct": _integer(step.get("spd_pct", 50)),
        "description": _text(step.get("description")),
    }


def _flow_snapshot_hash(flow: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        flow, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _json_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        raise ValueError("flow value is too deep")
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, list):
        return [_json_value(item, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        return {
            _text(key, required=True): _json_value(item, depth=depth + 1)
            for key, item in value.items()
        }
    raise TypeError("flow value is invalid")


def _text(value: Any, *, required: bool = False) -> str:
    if not isinstance(value, str) or len(value) > 8192:
        raise TypeError("flow text is invalid")
    result = value.strip() if required else value
    if required and not result:
        raise ValueError("flow text is required")
    return result


def _integer(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError("flow integer is invalid")
    return value


def _finite_number(value: Any) -> int | float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError("flow number is invalid")
    if not math.isfinite(float(value)):
        raise ValueError("flow number is invalid")
    return value


def _failure(code: str, message: str) -> RobotFlowResponse:
    return RobotFlowResponse(error=RobotFlowError(code, message))
