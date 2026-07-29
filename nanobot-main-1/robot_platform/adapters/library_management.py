"""Filesystem adapter for engineer command-library management."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from robot_platform.application.library_management import (
    RobotLibraryManagementError,
    RobotLibraryManagementResponse,
)
from robot_platform.library.catalog import ComponentCatalog
from robot_platform.library.migration import initialize_robot_libraries
from robot_platform.library.models import normalize_id
from robot_platform.library.mutation_service import RobotLibraryMutationService
from robot_platform.library.transaction import library_transaction
from robot_platform.library.versioned_registry import (
    ConflictError,
    VersionedCommandRegistry,
)


class FileCommandLibraryManagementAdapter:
    def __init__(self, data_dir: str | Path) -> None:
        self._data_dir = Path(data_dir)

    def execute(
        self,
        action: str,
        resource_id: str,
        body: dict[str, Any] | None,
        *,
        actor: str,
    ) -> RobotLibraryManagementResponse:
        handlers = {
            "list": lambda: self._list(),
            "get": lambda: self._get(resource_id),
            "create": lambda: self._create(body, actor),
            "save": lambda: self._save(resource_id, body, actor),
            "delete": lambda: self._delete(resource_id, actor),
            "update_draft": lambda: self._update_draft(resource_id, body, actor),
            "start_draft": lambda: self._start_draft(resource_id, actor),
            "publish": lambda: self._publish(resource_id, actor),
            "archive": lambda: self._archive(resource_id, actor),
            "duplicate": lambda: self._duplicate(resource_id, body, actor),
            "bulk_archive": lambda: self._bulk_archive(body, actor),
        }
        with library_transaction(self._data_dir):
            handler = handlers.get(action)
            return handler() if handler is not None else _error(
                "invalid_request", "Management action is invalid.",
            )

    def _list(self) -> RobotLibraryManagementResponse:
        return _ok({"entities": self._registry().list_summaries()})

    def _get(self, command_id: str) -> RobotLibraryManagementResponse:
        entity = self._registry().get_entity(command_id)
        return _ok(entity) if entity is not None else _not_found(command_id)

    def _create(
        self, body: dict[str, Any] | None, actor: str,
    ) -> RobotLibraryManagementResponse:
        validation = self._validate_body(body)
        if isinstance(validation, RobotLibraryManagementResponse):
            return validation
        component, payload = validation
        try:
            result = RobotLibraryMutationService(self._data_dir).create_command(
                payload, actor=actor,
            )
        except ValueError:
            return _error("command_exists", "Command already exists.")
        return _ok(result["command"], created=True)

    def _save(
        self, command_id: str, body: dict[str, Any] | None, actor: str,
    ) -> RobotLibraryManagementResponse:
        validation = self._validate_body(body)
        if isinstance(validation, RobotLibraryManagementResponse):
            return validation
        component, payload = validation
        registry = self._registry()
        entity = registry.get_entity(command_id)
        if entity is None:
            return _not_found(command_id)
        try:
            if entity.get("draft") is None:
                entity = registry.start_draft(command_id, actor=actor)
            revision = int(entity["draft"]["revision"])
            registry.update_draft(
                command_id,
                expected_revision=revision,
                name=str(payload["name"]).strip(),
                aliases=[str(alias) for alias in payload.get("aliases", [])],
                description=str(payload.get("description", "")),
                component_id=str(payload["component_id"]).strip(),
                parameters=dict(payload.get("parameters", {})),
                actor=actor,
            )
            entity = registry.publish(
                command_id,
                component_risk_level=component.risk_level,
                actor=actor,
            )
        except (ConflictError, ValueError):
            _discard_draft(registry, command_id, actor)
            return _error("save_conflict", "Command save conflicted.")
        return _ok(entity)

    def _delete(self, command_id: str, actor: str) -> RobotLibraryManagementResponse:
        try:
            self._registry().delete(command_id, actor=actor)
        except ValueError:
            return _not_found(command_id)
        return _ok({"deleted": command_id})

    def _update_draft(
        self, command_id: str, body: dict[str, Any] | None, actor: str,
    ) -> RobotLibraryManagementResponse:
        if not isinstance(body, dict):
            return _error("invalid_request", "request body must be an object")
        parameters = body.get("parameters", {})
        aliases = body.get("aliases", [])
        if not isinstance(parameters, dict) or not isinstance(aliases, list):
            return _error(
                "invalid_request", "parameters must be an object and aliases a list",
            )
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
                actor=actor,
            )
        except ConflictError as exc:
            return _error(
                "draft_conflict",
                "Draft revision mismatch; reload.",
                details={"current_revision": exc.current_revision},
            )
        except (TypeError, ValueError):
            return _error("invalid_draft", "Command draft is invalid.")
        return _ok(entity)

    def _start_draft(
        self, command_id: str, actor: str,
    ) -> RobotLibraryManagementResponse:
        registry = self._registry()
        if registry.get_entity(command_id) is None:
            return _not_found(command_id)
        try:
            entity = registry.start_draft(command_id, actor=actor)
        except ValueError:
            return _error("draft_conflict", "Command draft already exists.")
        return _ok(entity, created=True)

    def _publish(
        self, command_id: str, actor: str,
    ) -> RobotLibraryManagementResponse:
        registry = self._registry()
        entity = registry.get_entity(command_id)
        if entity is None:
            return _not_found(command_id)
        if entity.get("draft") is None and entity.get("published_version") is not None:
            return _ok(entity)
        if entity.get("draft") is None:
            return _error("no_draft", "Command has no active draft.")
        draft = entity["draft"]
        component = ComponentCatalog().get(str(draft.get("component_id", "")))
        if component is None:
            return _error("invalid_component", "Unknown component.")
        message = _validate_parameters(component, draft.get("parameters", {}))
        if message:
            return _error("invalid_parameters", message)
        try:
            published = registry.publish(
                command_id,
                component_risk_level=component.risk_level,
                actor=actor,
            )
        except ValueError:
            return _error("namespace_conflict", "Command namespace conflicts.")
        return _ok(published)

    def _archive(
        self, command_id: str, actor: str,
    ) -> RobotLibraryManagementResponse:
        try:
            self._registry().archive(command_id, actor=actor)
        except ConflictError:
            return _error("archive_blocked", "Published command cannot be archived.")
        except ValueError:
            return _not_found(command_id)
        return _ok({"archived": command_id})

    def _duplicate(
        self, command_id: str, body: dict[str, Any] | None, actor: str,
    ) -> RobotLibraryManagementResponse:
        if not isinstance(body, dict) or not str(body.get("name", "")).strip():
            return _error("invalid_request", "name is required")
        registry = self._registry()
        source = registry.get_entity(command_id)
        if source is None:
            return _not_found(command_id)
        base = source.get("draft")
        if base is None and source.get("published_version") is not None:
            base = source.get("versions", {}).get(str(source["published_version"]))
        if not isinstance(base, dict):
            return _error("duplicate_blocked", "Source command is not copyable.")
        name = str(body["name"]).strip()
        target_id = normalize_id(name)
        if registry.get_entity(target_id) is not None:
            return _error("command_exists", "Target command already exists.")
        entity = registry.create_entity(
            target_id,
            str(base.get("component_id", "")),
            name,
            dict(base.get("parameters", {})),
            aliases=list(base.get("aliases", [])),
            description=str(base.get("description", "")),
            actor=actor,
        )
        return _ok(entity, created=True)

    def _bulk_archive(
        self, body: dict[str, Any] | None, actor: str,
    ) -> RobotLibraryManagementResponse:
        ids = body.get("ids") if isinstance(body, dict) else None
        if not isinstance(ids, list):
            return _error("invalid_request", "ids must be a list")
        ordered = list(dict.fromkeys(
            str(item).strip() for item in ids if str(item).strip()
        ))
        if not ordered:
            return _error("invalid_request", "ids must not be empty")
        registry = self._registry()
        archived: list[str] = []
        failed: list[dict[str, str]] = []
        for command_id in ordered:
            try:
                registry.archive(command_id, actor=actor)
                archived.append(command_id)
            except ConflictError:
                failed.append({"id": command_id, "code": "archive_blocked"})
            except ValueError:
                failed.append({"id": command_id, "code": "command_not_found"})
        return _ok({"archived": archived, "failed": failed})

    def _validate_body(
        self, body: dict[str, Any] | None,
    ) -> tuple[Any, dict[str, Any]] | RobotLibraryManagementResponse:
        if not isinstance(body, dict):
            return _error("invalid_request", "request body must be an object")
        name = str(body.get("name", "")).strip()
        component_id = str(body.get("component_id", "")).strip()
        parameters = body.get("parameters", {})
        aliases = body.get("aliases", [])
        if not name or not component_id:
            return _error("invalid_request", "name and component_id are required")
        if not isinstance(parameters, dict) or not isinstance(aliases, list):
            return _error(
                "invalid_request", "parameters must be an object and aliases a list",
            )
        component = ComponentCatalog().get(component_id)
        if component is None:
            return _error("invalid_component", "Unknown component.")
        message = _validate_parameters(component, parameters)
        if message:
            return _error("invalid_parameters", message)
        return component, body

    def _registry(self) -> VersionedCommandRegistry:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        path = self._data_dir / "commands.json"
        audit = self._data_dir / "audit.jsonl"
        initialize_robot_libraries(commands_path=path, audit_path=audit)
        return VersionedCommandRegistry(path, audit_path=audit)


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


def _ok(
    payload: dict[str, Any], *, created: bool = False,
) -> RobotLibraryManagementResponse:
    return RobotLibraryManagementResponse(payload=payload, created=created)


def _error(
    code: str, message: str, *, details: dict[str, Any] | None = None,
) -> RobotLibraryManagementResponse:
    return RobotLibraryManagementResponse(
        error=RobotLibraryManagementError(code, message, details),
    )


def _not_found(command_id: str) -> RobotLibraryManagementResponse:
    return _error("command_not_found", f"Command '{command_id}' not found.")


def _discard_draft(
    registry: VersionedCommandRegistry, command_id: str, actor: str,
) -> None:
    try:
        registry.discard_draft(command_id, actor=actor)
    except ValueError:
        pass
