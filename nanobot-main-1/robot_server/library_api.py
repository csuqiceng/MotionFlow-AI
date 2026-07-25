"""Read-only robot-library API independent of the retired WebUI routes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from robot_platform import ComponentCatalog, initialize_robot_libraries
from robot_platform.library.published import PublishedRobotLibrary


_RISK_LEVELS = frozenset({"low", "medium", "high", "critical"})


class RobotLibraryService:
    """Project only published library records for operator-facing clients."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir

    @property
    def _commands_path(self) -> Path:
        return self._data_dir / "commands.json"

    @property
    def _flows_path(self) -> Path:
        return self._data_dir / "flows.json"

    @property
    def _audit_path(self) -> Path:
        return self._data_dir / "audit.jsonl"

    def list_components(self) -> tuple[int, dict[str, Any]]:
        items = [component.to_dict() for component in ComponentCatalog().list_all()]
        return 200, {"ok": True, "data": {"items": items, "total": len(items)}}

    def get_component(self, component_id: str) -> tuple[int, dict[str, Any]]:
        component = ComponentCatalog().get(component_id)
        if component is None:
            return _not_found("component", component_id)
        return 200, {"ok": True, "data": component.to_dict()}

    def list_commands(
        self, *, component_id: str = "", risk_level: str = "", query: str = ""
    ) -> tuple[int, dict[str, Any]]:
        if risk_level and risk_level not in _RISK_LEVELS:
            return _invalid(f"invalid risk_level: {risk_level}")
        items = self._published_commands()
        if component_id:
            items = [item for item in items if item.get("component_id") == component_id]
        if risk_level:
            items = [item for item in items if item.get("risk_level") == risk_level]
        if query:
            term = query.casefold()
            items = [
                item
                for item in items
                if term in str(item.get("name", "")).casefold()
                or any(term in str(alias).casefold() for alias in item.get("aliases", []))
            ]
        return 200, {"ok": True, "data": {"items": items, "total": len(items)}}

    def get_command(self, command_id: str) -> tuple[int, dict[str, Any]]:
        command = next(
            (item for item in self._published_commands() if item.get("id") == command_id), None
        )
        if command is None:
            return _not_found("command", command_id)
        return 200, {"ok": True, "data": command}

    def list_flows(self) -> tuple[int, dict[str, Any]]:
        items = PublishedRobotLibrary(self._data_dir).flows()
        return 200, {"ok": True, "data": {"items": items, "total": len(items)}}

    def get_flow(self, flow_id: str) -> tuple[int, dict[str, Any]]:
        flow = next(
            (item for item in PublishedRobotLibrary(self._data_dir).flows() if item.get("flow_id") == flow_id),
            None,
        )
        if flow is None:
            return _not_found("flow", flow_id)
        return 200, {"ok": True, "data": flow}

    def _published_commands(self) -> list[dict[str, Any]]:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        initialize_robot_libraries(
            commands_path=self._commands_path,
            audit_path=self._audit_path,
        )
        payload = json.loads(self._commands_path.read_text(encoding="utf-8"))
        if payload.get("schema_version") == "2.0":
            commands = payload.get("commands", {})
            if not isinstance(commands, dict):
                return []
            result: list[dict[str, Any]] = []
            for entity in commands.values():
                if not isinstance(entity, dict):
                    continue
                version = entity.get("published_version")
                published = entity.get("versions", {}).get(str(version))
                if isinstance(published, dict):
                    result.append(dict(published))
            return result
        commands = payload.get("commands", [])
        return [dict(item) for item in commands if isinstance(item, dict)]


def _invalid(message: str) -> tuple[int, dict[str, Any]]:
    return 400, {"error": {"code": "invalid_request", "message": message}}


def _not_found(kind: str, identifier: str) -> tuple[int, dict[str, Any]]:
    return 404, {
        "error": {"code": f"{kind}_not_found", "message": f"{kind} '{identifier}' not found"}
    }
