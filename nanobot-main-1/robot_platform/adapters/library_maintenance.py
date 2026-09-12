"""Filesystem adapters for library transfer and position cleanup."""

from __future__ import annotations

import json
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any

from robot_platform.flow.versioned_registry import VersionedFlowRegistry
from robot_platform.library.catalog import ComponentCatalog
from robot_platform.library.migration import _audit_append, initialize_robot_libraries
from robot_platform.library.transaction import library_transaction
from robot_platform.library.transfer import apply_transfer_payload, build_transfer_payload
from robot_platform.library.versioned_registry import VersionedCommandRegistry
from robot_platform.positions.cleanup import (
    backup_and_apply,
    build_cleanup_plan,
    classify_temporary,
)


class FilePositionMaintenanceAdapter:
    def __init__(self, data_dir: str | Path) -> None:
        self._data_dir = Path(data_dir)

    def preview(self, *, actor: str) -> dict[str, Any]:
        with library_transaction(self._data_dir):
            plan, preserved = self._plan()
            data = {
                "candidate_count": len(plan["remove"]),
                "candidate_names": plan["remove"],
                "preserved_referenced_count": len(preserved),
                "preserved_referenced_names": preserved,
            }
            self._audit(actor, "position_cleanup_preview", {
                "candidates": data["candidate_count"],
                "preserved": data["preserved_referenced_count"],
            })
            return data

    def apply(self, *, actor: str) -> dict[str, Any]:
        with library_transaction(self._data_dir):
            plan, preserved = self._plan()
            result = backup_and_apply(self._positions_path, plan)
            data = {
                "removed_count": len(result["removed"]),
                "removed_names": result["removed"],
                "preserved_referenced_count": len(preserved),
                "preserved_referenced_names": preserved,
                "backup_id": (
                    Path(result["backup_path"]).name
                    if result["backup_path"] else None
                ),
            }
            self._audit(actor, "position_cleanup_apply", {
                "removed": data["removed_count"],
                "preserved": data["preserved_referenced_count"],
            })
            return data

    @property
    def _positions_path(self) -> Path:
        return self._data_dir / "positions.json"

    def _plan(self) -> tuple[dict[str, list[str]], list[str]]:
        payload = json.loads(self._positions_path.read_text(encoding="utf-8"))
        positions = payload.get("positions") if isinstance(payload, dict) else None
        if not isinstance(positions, list):
            raise ValueError("position registry must contain a positions list")
        actual_names = {
            entry["name"].strip().casefold(): entry["name"]
            for entry in positions
            if isinstance(entry, dict)
            and isinstance(entry.get("name"), str)
            and entry["name"].strip()
        }
        referenced: set[str] = set()
        for version in _published_versions(
            self._data_dir / "commands.json", "commands",
        ):
            referenced.update(_strings_in(version))
        for version in _published_versions(self._data_dir / "flows.json", "flows"):
            referenced.update(_strings_in(version))
        referenced_names = {
            actual_names[value.strip().casefold()]
            for value in referenced
            if value.strip().casefold() in actual_names
        }
        plan = build_cleanup_plan(payload, referenced_names)
        preserved = sorted(
            name for name in referenced_names if classify_temporary(name)
        )
        return plan, preserved

    def _audit(self, actor: str, action: str, counts: dict[str, int]) -> None:
        try:
            _audit_append(self._data_dir / "audit.jsonl", {
                "action": action,
                "actor": actor,
                "status": "success",
                "counts": counts,
                "audit_id": secrets.token_urlsafe(16),
                "timestamp": datetime.now().isoformat(),
            })
        except OSError:
            pass


class FileLibraryTransferAdapter:
    def __init__(self, data_dir: str | Path) -> None:
        self._data_dir = Path(data_dir)

    def export(self) -> dict[str, Any]:
        with library_transaction(self._data_dir):
            return build_transfer_payload(
                commands=self._command_registry().list_entities(),
                flows=self._flow_registry().list_entities(),
            )

    def import_payload(
        self, payload: dict[str, Any], *, strategy: str, actor: str,
    ) -> dict[str, Any]:
        with library_transaction(
            self._data_dir,
            rollback_files=("commands.json", "flows.json"),
        ):
            components = {component.id for component in ComponentCatalog().list_all()}
            return apply_transfer_payload(
                payload,
                command_registry=self._command_registry(),
                flow_registry=self._flow_registry(),
                component_ids=components,
                strategy=strategy,
                actor=actor,
            )

    def _command_registry(self) -> VersionedCommandRegistry:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        commands = self._data_dir / "commands.json"
        audit = self._data_dir / "audit.jsonl"
        initialize_robot_libraries(commands_path=commands, audit_path=audit)
        return VersionedCommandRegistry(commands, audit_path=audit)

    def _flow_registry(self) -> VersionedFlowRegistry:
        return VersionedFlowRegistry(
            self._data_dir / "flows.json",
            audit_path=self._data_dir / "audit.jsonl",
        )


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
