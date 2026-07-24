"""Engineer-only cleanup of unreferenced temporary named positions."""

from __future__ import annotations

import json
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any

from robot_platform import _audit_append, backup_and_apply, build_cleanup_plan, classify_temporary
from robot_server.identity_api import RobotIdentityService


class RobotPositionMaintenanceService:
    def __init__(self, data_dir: Path, identity: RobotIdentityService) -> None:
        self._data_dir = data_dir
        self._identity = identity

    def preview(self, token: str) -> tuple[int, dict[str, Any]]:
        session, error = self._identity.require_engineer_session(token)
        if error is not None:
            return error
        try:
            plan, preserved = self._plan()
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return _invalid_positions(exc)
        data = {
            "candidate_count": len(plan["remove"]),
            "candidate_names": plan["remove"],
            "preserved_referenced_count": len(preserved),
            "preserved_referenced_names": preserved,
        }
        self._audit(session, "position_cleanup_preview", candidates=data["candidate_count"], preserved=data["preserved_referenced_count"])
        return 200, {"ok": True, "data": data}

    def apply(self, token: str, body: Any) -> tuple[int, dict[str, Any]]:
        session, error = self._identity.require_engineer_session(token)
        if error is not None:
            return error
        if not isinstance(body, dict) or body.get("action") != "apply":
            return 400, {"error": {"code": "invalid_action", "message": "action must be 'apply'."}}
        try:
            plan, preserved = self._plan()
            result = backup_and_apply(self._positions_path, plan)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return _invalid_positions(exc)
        data = {
            "removed_count": len(result["removed"]),
            "removed_names": result["removed"],
            "preserved_referenced_count": len(preserved),
            "preserved_referenced_names": preserved,
            "backup_path": str(result["backup_path"]) if result["backup_path"] else None,
        }
        self._audit(session, "position_cleanup_apply", removed=data["removed_count"], preserved=data["preserved_referenced_count"])
        return 200, {"ok": True, "data": data}

    @property
    def _positions_path(self) -> Path:
        return self._data_dir / "positions.json"

    def _plan(self) -> tuple[dict[str, list[str]], list[str]]:
        payload = json.loads(self._positions_path.read_text(encoding="utf-8"))
        positions = payload.get("positions") if isinstance(payload, dict) else None
        if not isinstance(positions, list):
            raise ValueError("position registry must be a JSON mapping with a positions list")
        actual_names = {
            entry["name"].strip().casefold(): entry["name"]
            for entry in positions
            if isinstance(entry, dict) and isinstance(entry.get("name"), str) and entry["name"].strip()
        }
        referenced_strings: set[str] = set()
        for version in _published_versions(self._data_dir / "commands.json", "commands"):
            referenced_strings.update(_strings_in(version))
        for version in _published_versions(self._data_dir / "flows.json", "flows"):
            referenced_strings.update(_strings_in(version))
        referenced_names = {
            actual_names[value.strip().casefold()]
            for value in referenced_strings
            if value.strip().casefold() in actual_names
        }
        plan = build_cleanup_plan(payload, referenced_names)
        preserved = sorted(name for name in referenced_names if classify_temporary(name))
        return plan, preserved

    def _audit(self, session: dict[str, Any], action: str, **counts: int) -> None:
        entry = {
            "action": action,
            "actor": f"user:{session['user_id']}",
            "actor_user_id": session["user_id"],
            "actor_username": session["username"],
            "actor_role": session["role"],
            "status": "success",
            "counts": counts,
            "audit_id": secrets.token_urlsafe(16),
            "timestamp": datetime.now().isoformat(),
        }
        try:
            _audit_append(self._data_dir / "audit.jsonl", entry)
        except OSError:
            pass


def _published_versions(path: Path, collection: str) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    entities = payload.get(collection, {}) if isinstance(payload, dict) else {}
    if not isinstance(entities, dict):
        return []
    versions: list[dict[str, Any]] = []
    for entity in entities.values():
        if not isinstance(entity, dict):
            continue
        version = entity.get("published_version")
        candidate = entity.get("versions", {}).get(str(version))
        if isinstance(candidate, dict):
            versions.append(candidate)
    return versions


def _strings_in(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, dict):
        return set().union(*(_strings_in(item) for item in value.values())) if value else set()
    if isinstance(value, (list, tuple)):
        return set().union(*(_strings_in(item) for item in value)) if value else set()
    return set()


def _invalid_positions(exc: Exception) -> tuple[int, dict[str, Any]]:
    return 400, {"error": {"code": "invalid_positions", "message": str(exc)}}
