"""Read-only projection of the robot library's current published resources."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from robot_platform.positions.registry import AXIS_NAMES, PositionRegistry


class PublishedRobotLibrary:
    """Expose positions, published motion commands, and published flows together.

    This is deliberately read-only.  Every writer must go through the
    version-aware management service so an AI tool cannot downgrade a v2
    registry to a legacy JSON schema.
    """

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)

    def positions(self) -> list[dict[str, Any]]:
        return [item.to_dict() for item in PositionRegistry(self.data_dir / "positions.json").list_all()]

    def position_commands(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for entity in self._published_entities("commands.json", "commands"):
            if entity.get("component_id") != "linear_move":
                continue
            pose = _pose_from_parameters(entity.get("parameters"))
            if pose is None:
                continue
            rows.append({
                "id": str(entity.get("id", "")),
                "name": str(entity.get("name", "")),
                "aliases": list(entity.get("aliases", [])),
                "command_id": str(entity.get("id", "")),
                "func_id": 108,
                "pose": pose,
                "parameters": dict(entity.get("parameters", {})),
            })
        return sorted(rows, key=lambda row: row["name"])

    def flows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for entity in self._published_entities("flows.json", "flows"):
            rows.append({
                "flow_id": str(entity.get("flow_id", "")),
                "name": str(entity.get("name", "")),
                "description": str(entity.get("description", "")),
                "steps": list(entity.get("steps", [])),
            })
        return sorted(rows, key=lambda row: row["name"])

    def find(self, name: str) -> tuple[str, dict[str, Any]] | None:
        key = str(name or "").strip().casefold()
        if not key:
            return None
        for position in self.positions():
            if str(position.get("name", "")).casefold() == key:
                return "position", position
        for command in self.position_commands():
            values = [command.get("name", ""), *command.get("aliases", [])]
            if any(str(value).casefold() == key for value in values):
                return "position_command", command
        for flow in self.flows():
            if str(flow.get("name", "")).casefold() == key or str(flow.get("flow_id", "")).casefold() == key:
                return "flow", flow
        return None

    def _published_entities(self, filename: str, collection: str) -> list[dict[str, Any]]:
        path = self.data_dir / filename
        if not path.is_file():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        entities = payload.get(collection, {}) if isinstance(payload, dict) else {}
        if not isinstance(entities, dict):
            return []
        rows: list[dict[str, Any]] = []
        for logical_id, record in entities.items():
            if not isinstance(record, dict):
                continue
            published_version = record.get("published_version")
            version = record.get("versions", {}).get(str(published_version))
            if not isinstance(version, dict):
                continue
            row = dict(version)
            row.setdefault("id" if collection == "commands" else "flow_id", logical_id)
            rows.append(row)
        return rows


def _pose_from_parameters(parameters: Any) -> dict[str, float] | None:
    if not isinstance(parameters, dict):
        return None
    prefixes = {axis: f"target_{axis}" for axis in AXIS_NAMES}
    if not all(field in parameters for field in prefixes.values()):
        return None
    try:
        return {axis: float(parameters[field]) for axis, field in prefixes.items()}
    except (TypeError, ValueError):
        return None
