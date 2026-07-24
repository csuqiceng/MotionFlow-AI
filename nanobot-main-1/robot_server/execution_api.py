"""Tracked execution of published robot-library commands and flows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from robot_platform import (
    ComponentCatalog, ExecutionHistory, FlowEntry, FlowRegistry, FlowStep,
    LibraryExecutionRegistry, RobotPlatform,
)
from robot_server.identity_api import RobotIdentityService


class RobotExecutionService:
    """Start and control library executions without bypassing ``RobotPlatform``."""

    def __init__(
        self,
        data_dir: Path,
        identity: RobotIdentityService,
        platform: RobotPlatform,
        *,
        registry: LibraryExecutionRegistry | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._identity = identity
        self._platform = platform
        self._registry = registry or LibraryExecutionRegistry(
            history=ExecutionHistory(data_dir / "library_executions.json")
        )

    def start_command(self, token: str, command_id: str, body: Any) -> tuple[int, dict[str, Any]]:
        session, error = self._identity.require_session(token)
        if error is not None:
            return error
        command = self._published_command(command_id)
        if command is None:
            return _not_found("command", command_id)
        component = ComponentCatalog().get(str(command.get("component_id", "")))
        if component is None:
            return 400, {"error": {"code": "unknown_component", "message": "Command component is not executable."}}
        entry = FlowEntry(
            name=str(command.get("name", command_id)),
            steps=[FlowStep(
                step_id=1,
                action=component.id,
                func_id=component.func_num,
                params=dict(command.get("parameters", {})),
                description=str(command.get("description", "")),
            )],
        )
        return self._start(entry, kind="command", source_id=command_id, session=session, body=body)

    def start_flow(self, token: str, flow_id: str, body: Any) -> tuple[int, dict[str, Any]]:
        session, error = self._identity.require_session(token)
        if error is not None:
            return error
        entry = FlowRegistry(self._data_dir / "flows.json").get(flow_id)
        if entry is None:
            return _not_found("flow", flow_id)
        return self._start(entry, kind="flow", source_id=flow_id, session=session, body=body)

    def get(self, token: str, execution_id: str) -> tuple[int, dict[str, Any]]:
        session, error = self._identity.require_session(token)
        if error is not None:
            return error
        data = self._registry.get(execution_id)
        if data is None or data.get("actor") != _actor(session):
            return _not_found("execution", execution_id)
        return 200, {"ok": True, "data": data}

    def list(self, token: str) -> tuple[int, dict[str, Any]]:
        session, error = self._identity.require_session(token)
        if error is not None:
            return error
        items = [item for item in self._registry.list() if item.get("actor") == _actor(session)]
        return 200, {"ok": True, "data": {"items": items, "total": len(items)}}

    def control(self, token: str, execution_id: str, body: Any) -> tuple[int, dict[str, Any]]:
        session, error = self._identity.require_session(token)
        if error is not None:
            return error
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
            return 400, {"error": {"code": "invalid_execution_action", "message": "Unsupported execution action."}}
        existing = self._registry.get(execution_id)
        if existing is None or existing.get("actor") != _actor(session):
            return _not_found("execution", execution_id)
        try:
            data = getattr(self._registry, method)(execution_id)
        except ValueError as exc:
            return 409, {"error": {"code": "execution_control_conflict", "message": str(exc)}}
        return 200, {"ok": True, "data": data}

    def _start(
        self,
        entry: FlowEntry,
        *,
        kind: str,
        source_id: str,
        session: dict[str, Any],
        body: Any,
    ) -> tuple[int, dict[str, Any]]:
        settings = _execution_settings(body)
        if type(settings[0]) is int:
            return settings
        execute_real, confirmation_code, work_area_clear, estop_ready = settings

        def worker(on_step, before_step) -> dict[str, Any]:
            dry_run = self._platform.run_flow_entry(entry, execute_real=False)
            if not dry_run.get("ok"):
                return dry_run
            return self._platform.run_flow_entry(
                entry,
                execute_real=execute_real,
                confirmation_code=confirmation_code,
                confirm_work_area_clear=work_area_clear,
                confirm_estop_ready=estop_ready,
                on_step=on_step,
                before_step=before_step,
            )

        execution_id = self._registry.start(
            len(entry.steps), worker, kind=kind, source_id=source_id, actor=_actor(session)
        )
        return 202, {"ok": True, "data": {"execution_id": execution_id, "state": "queued"}}

    def _published_command(self, command_id: str) -> dict[str, Any] | None:
        path = self._data_dir / "commands.json"
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        entity = payload.get("commands", {}).get(command_id) if isinstance(payload, dict) else None
        if not isinstance(entity, dict):
            return None
        version = entity.get("published_version")
        command = entity.get("versions", {}).get(str(version))
        return dict(command) if isinstance(command, dict) else None


def _execution_settings(
    body: Any,
) -> tuple[bool, str, bool, bool] | tuple[int, dict[str, Any]]:
    if body is None:
        body = {}
    if not isinstance(body, dict):
        return 400, {"error": {"code": "invalid_request", "message": "request body must be an object"}}
    execute_real = bool(body.get("execute_real"))
    confirmation_code = str(body.get("confirmation_code") or "")
    work_area_clear = bool(body.get("confirm_work_area_clear"))
    estop_ready = bool(body.get("confirm_estop_ready"))
    if execute_real and (not confirmation_code or not work_area_clear or not estop_ready):
        return 400, {
            "error": {"code": "confirmation_required", "message": "Real execution requires confirmation proof and both safety confirmations."}
        }
    return execute_real, confirmation_code, work_area_clear, estop_ready


def _actor(session: dict[str, Any]) -> str:
    return f"user:{session['user_id']}"


def _not_found(kind: str, identifier: str) -> tuple[int, dict[str, Any]]:
    return 404, {"error": {"code": f"{kind}_not_found", "message": f"{kind} '{identifier}' not found"}}
