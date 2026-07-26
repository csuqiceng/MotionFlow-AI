"""Engineer command-authoring API built on the platform versioned registry."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from robot_platform import (
    ComponentCatalog, ConflictError, VersionedCommandRegistry,
    initialize_robot_libraries, normalize_id,
)
from robot_platform.library.mutation_service import RobotLibraryMutationService
from robot_server.identity_api import RobotIdentityService


class RobotCommandManagementService:
    """Direct engineer CRUD over the operator-visible command library.

    Immutable snapshots remain an internal audit mechanism, but engineers no
    longer have to manage draft/publish lifecycle states.
    """

    def __init__(self, data_dir: Path, identity: RobotIdentityService) -> None:
        self._data_dir = data_dir
        self._identity = identity

    def list(self, token: str) -> tuple[int, dict[str, Any]]:
        session, error = self._identity.require_engineer_session(token)
        if error is not None:
            return error
        return 200, {"ok": True, "data": {"entities": self._registry().list_summaries()}}

    def get(self, token: str, command_id: str) -> tuple[int, dict[str, Any]]:
        _session, error = self._identity.require_engineer_session(token)
        if error is not None:
            return error
        entity = self._registry().get_entity(command_id)
        if entity is None:
            return _not_found(command_id)
        return 200, {"ok": True, "data": entity}

    def create(self, token: str, body: Any) -> tuple[int, dict[str, Any]]:
        session, error = self._identity.require_engineer_session(token)
        if error is not None:
            return error
        if not isinstance(body, dict):
            return _invalid("request body must be an object")
        name = str(body.get("name", "")).strip()
        component_id = str(body.get("component_id", "")).strip()
        parameters = body.get("parameters", {})
        aliases = body.get("aliases", [])
        if not name or not component_id:
            return _invalid("name and component_id are required")
        if not isinstance(parameters, dict) or not isinstance(aliases, list):
            return _invalid("parameters must be an object and aliases must be a list")
        command_id = normalize_id(name)
        component = ComponentCatalog().get(component_id)
        if component is None:
            return 400, {"error": {"code": "invalid_component", "message": "Unknown component."}}
        message = _validate_parameters(component, parameters)
        if message:
            return 400, {"error": {"code": "invalid_parameters", "message": message}}
        try:
            result = RobotLibraryMutationService(self._data_dir).create_command(body, actor=_actor(session))
        except ValueError as exc:
            return 409, {"error": {"code": "command_exists", "message": str(exc)}}
        return 201, {"ok": True, "data": result["command"]}

    def save(self, token: str, command_id: str, body: Any) -> tuple[int, dict[str, Any]]:
        """Apply an engineer edit immediately to the operator-visible command."""
        session, error = self._identity.require_engineer_session(token)
        if error is not None:
            return error
        if not isinstance(body, dict):
            return _invalid("request body must be an object")
        name = str(body.get("name", "")).strip()
        component_id = str(body.get("component_id", "")).strip()
        parameters = body.get("parameters", {})
        aliases = body.get("aliases", [])
        if not name or not component_id:
            return _invalid("name and component_id are required")
        if not isinstance(parameters, dict) or not isinstance(aliases, list):
            return _invalid("parameters must be an object and aliases must be a list")
        component = ComponentCatalog().get(component_id)
        if component is None:
            return 400, {"error": {"code": "invalid_component", "message": "Unknown component."}}
        message = _validate_parameters(component, parameters)
        if message:
            return 400, {"error": {"code": "invalid_parameters", "message": message}}
        registry = self._registry()
        entity = registry.get_entity(command_id)
        if entity is None:
            return _not_found(command_id)
        try:
            if entity.get("draft") is None:
                entity = registry.start_draft(command_id, actor=_actor_name(session))
            revision = int(entity["draft"]["revision"])
            registry.update_draft(
                command_id,
                expected_revision=revision,
                name=name,
                aliases=[str(alias) for alias in aliases],
                description=str(body.get("description", "")),
                component_id=component_id,
                parameters=dict(parameters),
                actor=_actor(session),
            )
            entity = registry.publish(
                command_id,
                component_risk_level=component.risk_level,
                actor=_actor_name(session),
            )
        except (ConflictError, ValueError) as exc:
            _discard_draft(registry, command_id, _actor_name(session))
            return 409, {"error": {"code": "save_conflict", "message": str(exc)}}
        return 200, {"ok": True, "data": entity}

    def delete(self, token: str, command_id: str) -> tuple[int, dict[str, Any]]:
        session, error = self._identity.require_engineer_session(token)
        if error is not None:
            return error
        try:
            self._registry().delete(command_id, actor=_actor_name(session))
        except ValueError as exc:
            return _not_found(command_id)
        return 200, {"ok": True, "data": {"deleted": command_id}}

    def update_draft(self, token: str, command_id: str, body: Any) -> tuple[int, dict[str, Any]]:
        session, error = self._identity.require_engineer_session(token)
        if error is not None:
            return error
        if not isinstance(body, dict):
            return _invalid("request body must be an object")
        parameters = body.get("parameters", {})
        aliases = body.get("aliases", [])
        if not isinstance(parameters, dict) or not isinstance(aliases, list):
            return _invalid("parameters must be an object and aliases must be a list")
        try:
            expected_revision = int(body.get("expected_revision"))
            entity = self._registry().update_draft(
                command_id,
                expected_revision=expected_revision,
                name=str(body.get("name", "")),
                aliases=[str(alias) for alias in aliases],
                description=str(body.get("description", "")),
                component_id=str(body.get("component_id", "")),
                parameters=dict(parameters),
                actor=_actor(session),
            )
        except ConflictError as exc:
            return 409, {
                "ok": False,
                "data": {"current_revision": exc.current_revision},
                "error": {"code": "draft_conflict", "message": "Draft revision mismatch; reload."},
            }
        except (TypeError, ValueError) as exc:
            return 400, {"error": {"code": "invalid_draft", "message": str(exc)}}
        return 200, {"ok": True, "data": entity}

    def start_draft(self, token: str, command_id: str) -> tuple[int, dict[str, Any]]:
        session, error = self._identity.require_engineer_session(token)
        if error is not None:
            return error
        registry = self._registry()
        if registry.get_entity(command_id) is None:
            return _not_found(command_id)
        try:
            entity = registry.start_draft(command_id, actor=_actor_name(session))
        except ValueError as exc:
            return 409, {"error": {"code": "draft_conflict", "message": str(exc)}}
        return 201, {"ok": True, "data": entity}

    def publish(self, token: str, command_id: str) -> tuple[int, dict[str, Any]]:
        session, error = self._identity.require_engineer_session(token)
        if error is not None:
            return error
        registry = self._registry()
        entity = registry.get_entity(command_id)
        if entity is None:
            return _not_found(command_id)
        if entity.get("draft") is None and entity.get("published_version") is not None:
            # Direct-save creation already publishes the command.  Keep the
            # retained workbench endpoint idempotent so an older client that
            # follows create -> publish does not turn a successful save into
            # a 404 or create a second immutable version.
            return 200, {"ok": True, "data": entity}
        if entity.get("draft") is None:
            return 404, {"error": {"code": "no_draft", "message": f"No active draft for '{command_id}'."}}
        draft = entity["draft"]
        component = ComponentCatalog().get(str(draft.get("component_id", "")))
        if component is None:
            return 400, {"error": {"code": "invalid_component", "message": "Unknown component."}}
        message = _validate_parameters(component, draft.get("parameters", {}))
        if message:
            return 400, {"error": {"code": "invalid_parameters", "message": message}}
        try:
            published = registry.publish(
                command_id,
                component_risk_level=component.risk_level,
                actor=_actor_name(session),
            )
        except ValueError as exc:
            return 409, {"error": {"code": "namespace_conflict", "message": str(exc)}}
        return 200, {"ok": True, "data": published}

    def archive(self, token: str, command_id: str) -> tuple[int, dict[str, Any]]:
        session, error = self._identity.require_engineer_session(token)
        if error is not None:
            return error
        try:
            self._registry().archive(command_id, actor=_actor_name(session))
        except ConflictError as exc:
            return 409, {"error": {"code": "archive_blocked", "message": str(exc)}}
        except ValueError as exc:
            return 404, {"error": {"code": "command_not_found", "message": str(exc)}}
        return 200, {"ok": True, "data": {"archived": command_id}}

    def duplicate(self, token: str, command_id: str, body: Any) -> tuple[int, dict[str, Any]]:
        session, error = self._identity.require_engineer_session(token)
        if error is not None:
            return error
        if not isinstance(body, dict) or not str(body.get("name", "")).strip():
            return _invalid("name is required")
        registry = self._registry()
        source = registry.get_entity(command_id)
        if source is None:
            return _not_found(command_id)
        base = source.get("draft")
        if base is None and source.get("published_version") is not None:
            base = source.get("versions", {}).get(str(source["published_version"]))
        if not isinstance(base, dict):
            return 409, {"error": {"code": "duplicate_blocked", "message": "Source command has no copyable version."}}
        name = str(body["name"]).strip()
        target_id = normalize_id(name)
        if registry.get_entity(target_id) is not None:
            return 409, {"error": {"code": "command_exists", "message": f"Command '{target_id}' already exists."}}
        entity = registry.create_entity(
            target_id, str(base.get("component_id", "")), name,
            dict(base.get("parameters", {})), aliases=list(base.get("aliases", [])),
            description=str(base.get("description", "")), actor=_actor(session),
        )
        return 201, {"ok": True, "data": entity}

    def bulk_archive(self, token: str, body: Any) -> tuple[int, dict[str, Any]]:
        session, error = self._identity.require_engineer_session(token)
        if error is not None:
            return error
        ids = body.get("ids") if isinstance(body, dict) else None
        if not isinstance(ids, list):
            return _invalid("ids must be a list")
        ordered_ids = list(dict.fromkeys(str(item).strip() for item in ids if str(item).strip()))
        if not ordered_ids:
            return _invalid("ids must not be empty")
        registry = self._registry()
        archived: list[str] = []
        failed: list[dict[str, str]] = []
        for command_id in ordered_ids:
            try:
                registry.archive(command_id, actor=_actor(session))
                archived.append(command_id)
            except ConflictError:
                failed.append({"id": command_id, "code": "archive_blocked"})
            except ValueError:
                failed.append({"id": command_id, "code": "command_not_found"})
        return 200, {"ok": True, "data": {"archived": archived, "failed": failed}}

    def _registry(self) -> VersionedCommandRegistry:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        commands_path = self._data_dir / "commands.json"
        audit_path = self._data_dir / "audit.jsonl"
        initialize_robot_libraries(commands_path=commands_path, audit_path=audit_path)
        return VersionedCommandRegistry(commands_path, audit_path=audit_path)


def _actor(session: dict[str, Any]) -> str:
    return f"user:{session['user_id']}"


def _actor_name(session: dict[str, Any]) -> str:
    return f"user:{session['user_id']}"


def _validate_parameters(component: Any, parameters: Any) -> str:
    if not isinstance(parameters, dict):
        return "Parameters must be an object."
    fields = {field.name: field for field in component.parameters}
    for name in parameters:
        if name not in fields:
            return f"Unknown parameter '{name}' for component '{component.id}'."
    expected = {"int": int, "float": (int, float), "str": str, "bool": bool}
    for field in component.parameters:
        if field.name not in parameters:
            if field.required:
                return f"Missing required parameter '{field.name}'."
            continue
        value = parameters[field.name]
        types = expected.get(field.type)
        if types is not None:
            if field.type in {"int", "float"} and isinstance(value, bool):
                return f"Parameter '{field.name}' must be {field.type}, not bool."
            if not isinstance(value, types):
                return f"Parameter '{field.name}' must be {field.type}."
        if field.type in {"int", "float"}:
            if field.minimum is not None and value < field.minimum:
                return f"Parameter '{field.name}' must be >= {field.minimum}."
            if field.maximum is not None and value > field.maximum:
                return f"Parameter '{field.name}' must be <= {field.maximum}."
    return ""


def _invalid(message: str) -> tuple[int, dict[str, Any]]:
    return 400, {"error": {"code": "invalid_request", "message": message}}


def _discard_draft(registry: VersionedCommandRegistry, command_id: str, actor: str) -> None:
    """Best-effort cleanup after a direct save could not become live."""
    try:
        registry.discard_draft(command_id, actor=actor)
    except ValueError:
        pass


def _not_found(command_id: str) -> tuple[int, dict[str, Any]]:
    return 404, {"error": {"code": "command_not_found", "message": f"Command '{command_id}' not found."}}
