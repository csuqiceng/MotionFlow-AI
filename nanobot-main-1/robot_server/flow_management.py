"""Engineer flow-authoring API independent of the retired WebUI workbench."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from robot_platform import ConflictError, VersionedFlowRegistry
from robot_platform.library.mutation_service import RobotLibraryMutationService
from robot_server.identity_api import RobotIdentityService


class RobotFlowManagementService:
    """Direct engineer CRUD over the operator-visible flow library."""
    def __init__(self, data_dir: Path, identity: RobotIdentityService) -> None:
        self._data_dir = data_dir
        self._identity = identity

    def list(self, token: str) -> tuple[int, dict[str, Any]]:
        _session, error = self._identity.require_engineer_session(token)
        if error is not None:
            return error
        return 200, {"ok": True, "data": {"entities": self._registry().list_entities()}}

    def get(self, token: str, flow_id: str) -> tuple[int, dict[str, Any]]:
        _session, error = self._identity.require_engineer_session(token)
        if error is not None:
            return error
        entity = self._registry().get_entity(flow_id)
        return (200, {"ok": True, "data": entity}) if entity else _not_found(flow_id)

    def create(self, token: str, body: Any) -> tuple[int, dict[str, Any]]:
        session, error = self._identity.require_engineer_session(token)
        if error is not None:
            return error
        if not isinstance(body, dict):
            return _invalid("flow body must be an object")
        name = str(body.get("name", "")).strip()
        steps = body.get("steps")
        if not name or not isinstance(steps, list):
            return _invalid("name and steps are required")
        try:
            result = RobotLibraryMutationService(self._data_dir).create_flow(body, actor=_actor(session))
        except ValueError as exc:
            return 400, {"error": {"code": "invalid_flow", "message": str(exc)}}
        return 201, {"ok": True, "data": result["flow"]}

    def save(self, token: str, flow_id: str, body: Any) -> tuple[int, dict[str, Any]]:
        """Apply an engineer edit immediately to the operator-visible flow."""
        session, error = self._identity.require_engineer_session(token)
        if error is not None:
            return error
        if not isinstance(body, dict):
            return _invalid("flow body must be an object")
        name = str(body.get("name", "")).strip()
        steps = body.get("steps")
        if not name or not isinstance(steps, list):
            return _invalid("name and steps are required")
        registry = self._registry()
        entity = registry.get_entity(flow_id)
        if entity is None:
            return _not_found(flow_id)
        try:
            if entity.get("draft") is None:
                entity = registry.start_draft(flow_id, actor=_actor(session))
            revision = int(entity["draft"]["revision"])
            registry.update_draft(
                flow_id,
                expected_revision=revision,
                name=name,
                steps=steps,
                step_delay_ms=body.get("step_delay_ms", 1000),
                rehearsal_spd=body.get("rehearsal_spd", 20),
                description=str(body.get("description", "")),
                actor=_actor(session),
            )
            errors = registry.validate_draft(flow_id)
            if errors:
                _discard_draft(registry, flow_id, _actor(session))
                return 400, {"error": {"code": "invalid_flow", "message": "; ".join(errors)}}
            entity = registry.publish(flow_id, actor=_actor(session))
        except (ConflictError, ValueError) as exc:
            _discard_draft(registry, flow_id, _actor(session))
            return 409, {"error": {"code": "save_conflict", "message": str(exc)}}
        return 200, {"ok": True, "data": entity}

    def delete(self, token: str, flow_id: str) -> tuple[int, dict[str, Any]]:
        session, error = self._identity.require_engineer_session(token)
        if error is not None:
            return error
        try:
            self._registry().delete(flow_id, actor=_actor(session))
        except ValueError:
            return _not_found(flow_id)
        return 200, {"ok": True, "data": {"deleted": flow_id}}

    def start_draft(self, token: str, flow_id: str) -> tuple[int, dict[str, Any]]:
        session, error = self._identity.require_engineer_session(token)
        if error is not None:
            return error
        registry = self._registry()
        if registry.get_entity(flow_id) is None:
            return _not_found(flow_id)
        try:
            entity = registry.start_draft(flow_id, actor=_actor(session))
        except ValueError as exc:
            return 409, {"error": {"code": "draft_conflict", "message": str(exc)}}
        return 201, {"ok": True, "data": entity}

    def update_draft(self, token: str, flow_id: str, body: Any) -> tuple[int, dict[str, Any]]:
        session, error = self._identity.require_engineer_session(token)
        if error is not None:
            return error
        if not isinstance(body, dict):
            return _invalid("flow body must be an object")
        steps = body.get("steps", [])
        if not isinstance(steps, list):
            return _invalid("steps must be a list")
        try:
            entity = self._registry().update_draft(
                flow_id,
                expected_revision=int(body.get("expected_revision")),
                name=str(body.get("name", "")),
                steps=steps,
                step_delay_ms=body.get("step_delay_ms", 1000),
                rehearsal_spd=body.get("rehearsal_spd", 20),
                description=str(body.get("description", "")),
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

    def validate_draft(self, token: str, flow_id: str) -> tuple[int, dict[str, Any]]:
        _session, error = self._identity.require_engineer_session(token)
        if error is not None:
            return error
        entity = self._registry().get_entity(flow_id)
        if entity is None:
            return _not_found(flow_id)
        if entity.get("draft") is None and entity.get("published_version") is not None:
            # Direct-save creation validates and publishes the flow in one
            # transaction.  Preserve the retained validate endpoint as an
            # idempotent confirmation for clients that still call it after
            # creation, without manufacturing a new draft.
            return 200, {"ok": True, "data": {"errors": []}}
        try:
            errors = self._registry().validate_draft(flow_id)
        except ValueError as exc:
            return 404, {"error": {"code": "no_draft", "message": str(exc)}}
        return 200, {"ok": not errors, "data": {"errors": errors}}

    def publish(self, token: str, flow_id: str) -> tuple[int, dict[str, Any]]:
        session, error = self._identity.require_engineer_session(token)
        if error is not None:
            return error
        registry = self._registry()
        entity = registry.get_entity(flow_id)
        if entity is None:
            return _not_found(flow_id)
        if entity.get("draft") is None and entity.get("published_version") is not None:
            # See validate_draft(): direct-save already committed the current
            # version, so publishing again is a successful no-op.
            return 200, {"ok": True, "data": entity}
        try:
            entity = registry.publish(flow_id, actor=_actor(session))
        except ValueError as exc:
            return 400, {"error": {"code": "invalid_flow", "message": str(exc)}}
        return 200, {"ok": True, "data": entity}

    def archive(self, token: str, flow_id: str) -> tuple[int, dict[str, Any]]:
        session, error = self._identity.require_engineer_session(token)
        if error is not None:
            return error
        try:
            self._registry().archive(flow_id, actor=_actor(session))
        except ConflictError as exc:
            return 409, {"error": {"code": "archive_blocked", "message": str(exc)}}
        except ValueError as exc:
            return 404, {"error": {"code": "flow_not_found", "message": str(exc)}}
        return 200, {"ok": True, "data": {"archived": flow_id}}

    def duplicate(self, token: str, flow_id: str, body: Any) -> tuple[int, dict[str, Any]]:
        session, error = self._identity.require_engineer_session(token)
        if error is not None:
            return error
        if not isinstance(body, dict) or not str(body.get("name", "")).strip():
            return _invalid("name is required")
        registry = self._registry()
        source = registry.get_entity(flow_id)
        if source is None:
            return _not_found(flow_id)
        base = source.get("draft")
        if base is None and source.get("published_version") is not None:
            base = source.get("versions", {}).get(str(source["published_version"]))
        if not isinstance(base, dict):
            return 409, {"error": {"code": "duplicate_blocked", "message": "Source flow has no copyable version."}}
        name = str(body["name"]).strip()
        target_id = "_".join(name.casefold().split())
        if registry.get_entity(target_id) is not None:
            return 409, {"error": {"code": "flow_exists", "message": f"Flow '{target_id}' already exists."}}
        entity = registry.create_entity(
            target_id, name, list(base.get("steps", [])),
            step_delay_ms=base.get("step_delay_ms", 1000),
            rehearsal_spd=base.get("rehearsal_spd", 20),
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
        for flow_id in ordered_ids:
            try:
                registry.archive(flow_id, actor=_actor(session))
                archived.append(flow_id)
            except ConflictError:
                failed.append({"id": flow_id, "code": "archive_blocked"})
            except ValueError:
                failed.append({"id": flow_id, "code": "flow_not_found"})
        return 200, {"ok": True, "data": {"archived": archived, "failed": failed}}

    def _registry(self) -> VersionedFlowRegistry:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        return VersionedFlowRegistry(
            self._data_dir / "flows.json", audit_path=self._data_dir / "audit.jsonl"
        )


def _actor(session: dict[str, Any]) -> str:
    return f"user:{session['user_id']}"


def _invalid(message: str) -> tuple[int, dict[str, Any]]:
    return 400, {"error": {"code": "invalid_request", "message": message}}


def _discard_draft(registry: VersionedFlowRegistry, flow_id: str, actor: str) -> None:
    """Best-effort cleanup after a direct save could not become live."""
    try:
        registry.discard_draft(flow_id, actor=actor)
    except ValueError:
        pass


def _not_found(flow_id: str) -> tuple[int, dict[str, Any]]:
    return 404, {"error": {"code": "flow_not_found", "message": f"Flow '{flow_id}' not found."}}
