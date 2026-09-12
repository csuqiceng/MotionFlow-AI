"""Filesystem adapter for engineer Flow authoring."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from robot_platform.application.flow_management import (
    RobotFlowManagementError,
    RobotFlowManagementResponse,
)
from robot_platform.flow.versioned_registry import VersionedFlowRegistry
from robot_platform.library.mutation_service import RobotLibraryMutationService
from robot_platform.library.transaction import synchronized_library_method
from robot_platform.library.versioned_registry import ConflictError


class FileFlowManagementAdapter:
    def __init__(self, data_dir: str | Path) -> None:
        self._data_dir = Path(data_dir)

    @synchronized_library_method
    def execute(
        self,
        action: str,
        flow_id: str,
        body: dict[str, Any] | None,
        *,
        actor: str,
    ) -> RobotFlowManagementResponse:
        handlers: dict[str, Callable[[], RobotFlowManagementResponse]] = {
            "list": lambda: _ok({"entities": self._registry().list_entities()}),
            "get": lambda: self._get(flow_id),
            "create": lambda: self._create(body, actor),
            "save": lambda: self._save(flow_id, body, actor),
            "delete": lambda: self._delete(flow_id, actor),
            "start_draft": lambda: self._start_draft(flow_id, actor),
            "update_draft": lambda: self._update_draft(flow_id, body, actor),
            "validate_draft": lambda: self._validate_draft(flow_id),
            "publish": lambda: self._publish(flow_id, actor),
            "archive": lambda: self._archive(flow_id, actor),
            "duplicate": lambda: self._duplicate(flow_id, body, actor),
            "bulk_archive": lambda: self._bulk_archive(body, actor),
        }
        handler = handlers.get(action)
        return handler() if handler is not None else _error(
            "invalid_request", "Flow management action is invalid.",
        )

    def _get(self, flow_id: str) -> RobotFlowManagementResponse:
        entity = self._registry().get_entity(flow_id)
        return _ok(entity) if entity is not None else _not_found(flow_id)

    def _create(
        self, body: dict[str, Any] | None, actor: str,
    ) -> RobotFlowManagementResponse:
        error = _valid_body(body)
        if error is not None:
            return error
        assert body is not None
        try:
            result = RobotLibraryMutationService(self._data_dir).create_flow(
                body, actor=actor,
            )
        except ValueError:
            return _error("invalid_flow", "Flow is invalid.")
        return _ok(result["flow"], created=True)

    def _save(
        self, flow_id: str, body: dict[str, Any] | None, actor: str,
    ) -> RobotFlowManagementResponse:
        error = _valid_body(body)
        if error is not None:
            return error
        assert body is not None
        registry = self._registry()
        entity = registry.get_entity(flow_id)
        if entity is None:
            return _not_found(flow_id)
        try:
            if entity.get("draft") is None:
                entity = registry.start_draft(flow_id, actor=actor)
            draft = entity["draft"]
            registry.update_draft(
                flow_id,
                expected_revision=int(draft["revision"]),
                name=str(body["name"]).strip(),
                steps=deepcopy(body["steps"]),
                step_delay_ms=body.get("step_delay_ms", 1000),
                rehearsal_spd=body.get("rehearsal_spd", 20),
                description=str(body.get("description", "")),
                node_graph=deepcopy(body.get("node_graph", draft.get("node_graph"))),
                actor=actor,
            )
            errors = registry.validate_draft(flow_id)
            if errors:
                _discard_draft(registry, flow_id, actor)
                return _error("invalid_flow", "; ".join(errors))
            return _ok(registry.publish(flow_id, actor=actor))
        except (ConflictError, ValueError):
            _discard_draft(registry, flow_id, actor)
            return _error("save_conflict", "Flow save conflicted.")

    def _delete(self, flow_id: str, actor: str) -> RobotFlowManagementResponse:
        try:
            self._registry().delete(flow_id, actor=actor)
        except ValueError:
            return _not_found(flow_id)
        return _ok({"deleted": flow_id})

    def _start_draft(
        self, flow_id: str, actor: str,
    ) -> RobotFlowManagementResponse:
        registry = self._registry()
        if registry.get_entity(flow_id) is None:
            return _not_found(flow_id)
        try:
            return _ok(registry.start_draft(flow_id, actor=actor), created=True)
        except ValueError:
            return _error("draft_conflict", "Flow draft already exists.")

    def _update_draft(
        self, flow_id: str, body: dict[str, Any] | None, actor: str,
    ) -> RobotFlowManagementResponse:
        if not isinstance(body, dict) or not isinstance(body.get("steps", []), list):
            return _error("invalid_draft", "Flow draft is invalid.")
        try:
            registry = self._registry()
            current = registry.get_entity(flow_id)
            current_draft = current.get("draft") if isinstance(current, dict) else None
            entity = registry.update_draft(
                flow_id,
                expected_revision=int(body.get("expected_revision")),
                name=str(body.get("name", "")),
                steps=deepcopy(body.get("steps", [])),
                step_delay_ms=body.get("step_delay_ms", 1000),
                rehearsal_spd=body.get("rehearsal_spd", 20),
                description=str(body.get("description", "")),
                node_graph=deepcopy(body.get(
                    "node_graph",
                    current_draft.get("node_graph")
                    if isinstance(current_draft, dict) else None,
                )),
                actor=actor,
            )
        except ConflictError as exc:
            return _error(
                "draft_conflict", "Draft revision mismatch; reload.",
                details={"current_revision": exc.current_revision},
            )
        except (TypeError, ValueError):
            return _error("invalid_draft", "Flow draft is invalid.")
        return _ok(entity)

    def _validate_draft(self, flow_id: str) -> RobotFlowManagementResponse:
        registry = self._registry()
        entity = registry.get_entity(flow_id)
        if entity is None:
            return _not_found(flow_id)
        if entity.get("draft") is None and entity.get("published_version") is not None:
            return _ok({"errors": []})
        try:
            errors = registry.validate_draft(flow_id)
        except ValueError:
            return _error("no_draft", "Flow has no active draft.")
        return _ok({"errors": errors})

    def _publish(self, flow_id: str, actor: str) -> RobotFlowManagementResponse:
        registry = self._registry()
        entity = registry.get_entity(flow_id)
        if entity is None:
            return _not_found(flow_id)
        if entity.get("draft") is None and entity.get("published_version") is not None:
            return _ok(entity)
        try:
            return _ok(registry.publish(flow_id, actor=actor))
        except ValueError:
            return _error("invalid_flow", "Flow is invalid.")

    def _archive(self, flow_id: str, actor: str) -> RobotFlowManagementResponse:
        try:
            self._registry().archive(flow_id, actor=actor)
        except ConflictError:
            return _error("archive_blocked", "Published Flow cannot be archived.")
        except ValueError:
            return _not_found(flow_id)
        return _ok({"archived": flow_id})

    def _duplicate(
        self, flow_id: str, body: dict[str, Any] | None, actor: str,
    ) -> RobotFlowManagementResponse:
        if not isinstance(body, dict) or not str(body.get("name", "")).strip():
            return _error("invalid_request", "name is required")
        registry = self._registry()
        source = registry.get_entity(flow_id)
        if source is None:
            return _not_found(flow_id)
        base = source.get("draft")
        if base is None and source.get("published_version") is not None:
            base = source.get("versions", {}).get(str(source["published_version"]))
        if not isinstance(base, dict):
            return _error("duplicate_blocked", "Flow is not copyable.")
        name = str(body["name"]).strip()
        target_id = "_".join(name.casefold().split())
        if registry.get_entity(target_id) is not None:
            return _error("flow_exists", "Target Flow already exists.")
        return _ok(registry.create_entity(
            target_id,
            name,
            deepcopy(base.get("steps", [])),
            step_delay_ms=base.get("step_delay_ms", 1000),
            rehearsal_spd=base.get("rehearsal_spd", 20),
            description=str(base.get("description", "")),
            node_graph=deepcopy(base.get("node_graph")),
            actor=actor,
        ), created=True)

    def _bulk_archive(
        self, body: dict[str, Any] | None, actor: str,
    ) -> RobotFlowManagementResponse:
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
        for flow_id in ordered:
            try:
                registry.archive(flow_id, actor=actor)
                archived.append(flow_id)
            except ConflictError:
                failed.append({"id": flow_id, "code": "archive_blocked"})
            except ValueError:
                failed.append({"id": flow_id, "code": "flow_not_found"})
        return _ok({"archived": archived, "failed": failed})

    def _registry(self) -> VersionedFlowRegistry:
        return VersionedFlowRegistry(
            self._data_dir / "flows.json",
            audit_path=self._data_dir / "audit.jsonl",
        )


def _valid_body(body: Any) -> RobotFlowManagementResponse | None:
    if not isinstance(body, dict):
        return _error("invalid_request", "Flow body must be an object.")
    if not str(body.get("name", "")).strip() or not isinstance(body.get("steps"), list):
        return _error("invalid_request", "name and steps are required.")
    return None


def _discard_draft(
    registry: VersionedFlowRegistry, flow_id: str, actor: str,
) -> None:
    try:
        registry.discard_draft(flow_id, actor=actor)
    except ValueError:
        pass


def _ok(
    payload: dict[str, Any], *, created: bool = False,
) -> RobotFlowManagementResponse:
    return RobotFlowManagementResponse(payload=deepcopy(payload), created=created)


def _error(
    code: str, message: str, *, details: dict[str, Any] | None = None,
) -> RobotFlowManagementResponse:
    return RobotFlowManagementResponse(error=RobotFlowManagementError(
        code, message, details,
    ))


def _not_found(flow_id: str) -> RobotFlowManagementResponse:
    return _error("flow_not_found", f"Flow '{flow_id}' was not found.")
