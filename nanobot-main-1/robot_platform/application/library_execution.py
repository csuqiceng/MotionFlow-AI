"""Tracked dry-run execution of published commands and flows."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from .dry_run import RobotDryRunApplicationPort
from .flow import RobotFlowApplicationPort, RobotFlowQuery
from .library_catalog import RobotLibraryCatalogApplicationPort
from .principal import AuthenticatedPrincipal


@dataclass(frozen=True)
class RobotLibraryExecutionCommand:
    principal: AuthenticatedPrincipal
    action: str
    source_id: str = ""
    execution_id: str = ""
    body: dict[str, Any] | None = None


@dataclass(frozen=True)
class RobotLibraryExecutionError:
    code: str
    message: str


@dataclass(frozen=True)
class RobotLibraryExecutionResponse:
    payload: dict[str, Any] | None = None
    error: RobotLibraryExecutionError | None = None
    accepted: bool = False

    def __post_init__(self) -> None:
        if (self.payload is None) == (self.error is None):
            raise ValueError("RobotLibraryExecutionResponse requires payload or error")
        if self.error is not None and self.accepted:
            raise ValueError("Failed execution response cannot be accepted")

    @property
    def ok(self) -> bool:
        return self.error is None


class LibraryExecutionRegistryPort(Protocol):
    def start(
        self,
        total_steps: int,
        worker: Callable[..., dict[str, Any]],
        *,
        kind: str,
        source_id: str,
        actor: str,
    ) -> str: ...
    def get(self, execution_id: str) -> dict[str, Any] | None: ...
    def list(self) -> list[dict[str, Any]]: ...
    def pause(self, execution_id: str) -> dict[str, Any]: ...
    def resume(self, execution_id: str) -> dict[str, Any]: ...
    def step_once(self, execution_id: str) -> dict[str, Any]: ...
    def stop(self, execution_id: str) -> dict[str, Any]: ...
    def reset(self, execution_id: str) -> dict[str, Any]: ...


class RobotLibraryExecutionApplicationPort(Protocol):
    def execute(
        self, command: RobotLibraryExecutionCommand,
    ) -> RobotLibraryExecutionResponse: ...


class RobotLibraryExecutionApplicationService:
    def __init__(
        self,
        registry: LibraryExecutionRegistryPort,
        catalog: RobotLibraryCatalogApplicationPort,
        flows: RobotFlowApplicationPort,
        dry_run: RobotDryRunApplicationPort,
    ) -> None:
        self._registry = registry
        self._catalog = catalog
        self._flows = flows
        self._dry_run = dry_run

    def execute(
        self, command: RobotLibraryExecutionCommand,
    ) -> RobotLibraryExecutionResponse:
        if not isinstance(command, RobotLibraryExecutionCommand):
            return _failure("invalid_request", "Execution request is invalid.")
        if command.principal.role not in {"operator", "engineer"}:
            return _failure("execution_forbidden", "Operator role is required.")
        actions = {
            "start_command": self._start_command,
            "start_flow": self._start_flow,
            "get": self._get,
            "list": self._list,
            "control": self._control,
        }
        handler = actions.get(command.action)
        if handler is None:
            return _failure("invalid_request", "Execution action is invalid.")
        try:
            return handler(command)
        except Exception:
            return _failure(
                "execution_state_unavailable", "Execution state is unavailable.",
            )

    def _start_command(
        self, command: RobotLibraryExecutionCommand,
    ) -> RobotLibraryExecutionResponse:
        published = self._catalog.get_command(command.source_id)
        if not published.ok or not isinstance(published.payload, dict):
            return _failure("command_not_found", "Command was not found.")
        component_id = str(published.payload.get("component_id", ""))
        component = self._catalog.get_component(component_id)
        if not component.ok or not isinstance(component.payload, dict):
            return _failure(
                "unknown_component", "Command component is not executable.",
            )
        func_num = component.payload.get("func_num")
        if not isinstance(func_num, int) or isinstance(func_num, bool):
            return _failure(
                "unknown_component", "Command component is not executable.",
            )
        parameters = published.payload.get("parameters", {})
        if not isinstance(parameters, dict):
            return _failure("invalid_command", "Published command is invalid.")
        from robot_platform.flow.models import FlowEntry, FlowStep

        entry = FlowEntry(
            name=str(published.payload.get("name", command.source_id)),
            steps=[FlowStep(
                step_id=1,
                action=component_id,
                func_id=func_num,
                params=dict(parameters),
                description=str(published.payload.get("description", "")),
            )],
        )
        return self._start(command, entry, "command")

    def _start_flow(
        self, command: RobotLibraryExecutionCommand,
    ) -> RobotLibraryExecutionResponse:
        response = self._flows.query(RobotFlowQuery(
            command.principal, "get", command.source_id,
        ))
        if not response.ok or not isinstance(response.payload, dict):
            return _failure("flow_not_found", "Flow was not found.")
        flow = response.payload.get("flow")
        if not isinstance(flow, dict):
            return _failure("invalid_flow", "Published Flow is invalid.")
        try:
            from robot_platform.flow.models import FlowEntry

            entry = FlowEntry.from_dict(flow)
        except (TypeError, ValueError):
            return _failure("invalid_flow", "Published Flow is invalid.")
        return self._start(command, entry, "flow")

    def _start(
        self,
        command: RobotLibraryExecutionCommand,
        entry: Any,
        kind: str,
    ) -> RobotLibraryExecutionResponse:
        if command.body is not None and not isinstance(command.body, dict):
            return _failure("invalid_request", "Request body must be an object.")
        body = command.body or {}
        if bool(body.get("execute_real")):
            return _failure(
                "staged_execution_required",
                "Real execution must use the authenticated staged workflow.",
            )

        def worker(on_step: Any, before_step: Any) -> dict[str, Any]:
            preview = self._dry_run.preview_flow_entry(
                entry, on_step=on_step, before_step=before_step,
            )
            if preview.ok and isinstance(preview.payload, dict):
                return preview.payload
            error = preview.error
            code = getattr(error, "code", "dry_run_unavailable")
            return {
                "ok": False,
                "state": code,
                "message": getattr(
                    error, "message", "Robot dry-run is unavailable.",
                ),
                "data": {},
                "errors": [{"code": code}],
            }

        execution_id = self._registry.start(
            len(entry.steps),
            worker,
            kind=kind,
            source_id=command.source_id,
            actor=_actor(command.principal),
        )
        return RobotLibraryExecutionResponse(payload={
            "execution_id": execution_id, "state": "queued",
        }, accepted=True)

    def _get(
        self, command: RobotLibraryExecutionCommand,
    ) -> RobotLibraryExecutionResponse:
        data = self._registry.get(command.execution_id)
        if data is None or data.get("actor") != _actor(command.principal):
            return _failure("execution_not_found", "Execution was not found.")
        return RobotLibraryExecutionResponse(payload=_public_execution(data))

    def _list(
        self, command: RobotLibraryExecutionCommand,
    ) -> RobotLibraryExecutionResponse:
        items = [
            _public_execution(item)
            for item in self._registry.list()
            if item.get("actor") == _actor(command.principal)
        ]
        return RobotLibraryExecutionResponse(payload={
            "items": items, "total": len(items),
        })

    def _control(
        self, command: RobotLibraryExecutionCommand,
    ) -> RobotLibraryExecutionResponse:
        body = command.body
        action = body.get("action") if isinstance(body, dict) else None
        methods = {
            "pause": "pause",
            "resume": "resume",
            "step": "step_once",
            "stop": "stop",
            "reset": "reset",
        }
        method = methods.get(action)
        if method is None:
            return _failure(
                "invalid_execution_action", "Unsupported execution action.",
            )
        existing = self._registry.get(command.execution_id)
        if existing is None or existing.get("actor") != _actor(command.principal):
            return _failure("execution_not_found", "Execution was not found.")
        try:
            result = getattr(self._registry, method)(command.execution_id)
        except ValueError:
            return _failure(
                "execution_control_conflict", "Execution control conflicted.",
            )
        return RobotLibraryExecutionResponse(payload=_public_execution(result))


def _actor(principal: AuthenticatedPrincipal) -> str:
    return f"user:{principal.actor_id}"


def _public_execution(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError("Execution state is invalid")
    steps = value.get("steps", [])
    actions = value.get("allowed_actions", [])
    if not isinstance(steps, list) or not isinstance(actions, list):
        raise TypeError("Execution state is invalid")
    result = value.get("result")
    return {
        "execution_id": _text(value.get("execution_id")),
        "kind": _text(value.get("kind")),
        "source_id": _text(value.get("source_id")),
        "actor": _text(value.get("actor")),
        "state": _text(value.get("state")),
        "control_state": _text(value.get("control_state")),
        "message": _text(value.get("message")),
        "steps": [_public_execution_step(step) for step in steps],
        "result": _safe_value(result) if result is not None else None,
        "created_at": _text(value.get("created_at")),
        "updated_at": _text(value.get("updated_at")),
        "completed_at": (
            _text(value.get("completed_at"))
            if value.get("completed_at") is not None else None
        ),
        "allowed_actions": [_text(action) for action in actions],
    }


def _public_execution_step(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError("Execution step is invalid")
    result = value.get("result")
    return {
        "step_index": _integer(value.get("step_index")),
        "state": _text(value.get("state")),
        **({"result": _safe_value(result)} if result is not None else {}),
    }


_SENSITIVE = (
    "password", "secret", "token", "permit", "scope", "sdk", "path",
    "host", "controller", "config", "credential",
)


def _safe_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 10:
        raise ValueError("Execution result is too deep")
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, list):
        return [_safe_value(item, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        return {
            key: _safe_value(item, depth=depth + 1)
            for key, item in value.items()
            if isinstance(key, str)
            and not any(part in key.casefold() for part in _SENSITIVE)
        }
    raise TypeError("Execution result is invalid")


def _text(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 8192:
        raise TypeError("Execution text is invalid")
    return value


def _integer(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError("Execution integer is invalid")
    return value


def _failure(code: str, message: str) -> RobotLibraryExecutionResponse:
    return RobotLibraryExecutionResponse(error=RobotLibraryExecutionError(code, message))
