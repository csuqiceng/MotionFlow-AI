"""Filesystem adapter for position and published-library Application ports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from robot_platform.flow.versioned_registry import VersionedFlowRegistry
from robot_platform.library.catalog import ComponentCatalog
from robot_platform.library.migration import initialize_robot_libraries
from robot_platform.library.mutation_service import (
    RobotLibraryMutationService,
    ensure_published_position_commands,
)
from robot_platform.library.published import PublishedRobotLibrary
from robot_platform.library.transaction import synchronized_library_method
from robot_platform.positions.defaults import ensure_default_positions
from robot_platform.positions.registry import PositionRegistry


class FileRobotPositionLibraryAdapter:
    """One data-directory-scoped adapter; no host or transport dependencies."""

    def __init__(
        self, data_dir: str | Path, *, positions_path: str | Path | None = None,
    ) -> None:
        self._data_dir = Path(data_dir)
        self._positions_path = Path(positions_path or self._data_dir / "positions.json")

    @property
    def _commands_path(self) -> Path:
        return self._data_dir / "commands.json"

    @property
    def _flows_path(self) -> Path:
        return self._data_dir / "flows.json"

    @property
    def _audit_path(self) -> Path:
        return self._data_dir / "audit.jsonl"

    @synchronized_library_method
    def positions(self) -> list[dict[str, Any]]:
        return [item.to_dict() for item in PositionRegistry(self._positions_path).list_all()]

    @synchronized_library_method
    def position_commands(self) -> list[dict[str, Any]]:
        return PublishedRobotLibrary(self._data_dir).position_commands()

    @synchronized_library_method
    def flows(self) -> list[dict[str, Any]]:
        return PublishedRobotLibrary(self._data_dir).flows()

    @synchronized_library_method
    def find(self, name: str) -> tuple[str, dict[str, Any]] | None:
        key = str(name or "").strip().casefold()
        if not key:
            return None
        position = PositionRegistry(self._positions_path).get(name)
        if position is not None:
            return "position", position.to_dict()
        for command in self.position_commands():
            values = [command.get("name", ""), *command.get("aliases", [])]
            if any(str(value).casefold() == key for value in values):
                return "position_command", command
        for flow in self.flows():
            if (
                str(flow.get("name", "")).casefold() == key
                or str(flow.get("flow_id", "")).casefold() == key
            ):
                return "flow", flow
        return None

    @synchronized_library_method
    def resolve(self, name: str) -> dict[str, float] | None:
        pose = PositionRegistry(self._positions_path).resolve(name)
        if pose is not None:
            return pose
        found = self.find(name)
        if found is not None and found[0] == "position_command":
            return dict(found[1]["pose"])
        return None

    def list_components(self) -> list[dict[str, Any]]:
        return [component.to_dict() for component in ComponentCatalog().list_all()]

    def get_component(self, component_id: str) -> dict[str, Any] | None:
        component = ComponentCatalog().get(component_id)
        return component.to_dict() if component is not None else None

    @synchronized_library_method
    def list_commands(self) -> list[dict[str, Any]]:
        self._prepare_commands()
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

    @synchronized_library_method
    def get_command(self, command_id: str) -> dict[str, Any] | None:
        return next(
            (item for item in self.list_commands() if item.get("id") == command_id),
            None,
        )

    @synchronized_library_method
    def list_flows(self) -> list[dict[str, Any]]:
        self._prepare_flows()
        return PublishedRobotLibrary(self._data_dir).flows()

    @synchronized_library_method
    def get_flow(self, flow_id: str) -> dict[str, Any] | None:
        return next(
            (item for item in self.list_flows() if item.get("flow_id") == flow_id),
            None,
        )

    @synchronized_library_method
    def create(
        self, resource_type: str, payload: dict[str, Any], *, actor: str,
    ) -> dict[str, Any]:
        return RobotLibraryMutationService(self._data_dir).create(
            resource_type, payload, actor=actor,
        )

    @synchronized_library_method
    def update_position(
        self, payload: dict[str, Any], *, actor: str,
    ) -> dict[str, Any]:
        return RobotLibraryMutationService(self._data_dir).update_position(
            payload, actor=actor,
        )

    @synchronized_library_method
    def delete_position(
        self, payload: dict[str, Any], *, actor: str,
    ) -> dict[str, Any]:
        return RobotLibraryMutationService(self._data_dir).delete_position(
            payload, actor=actor,
        )

    def _prepare_commands(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        if self._positions_path == self._data_dir / "positions.json":
            ensure_default_positions(self._positions_path)
        initialize_robot_libraries(
            commands_path=self._commands_path, audit_path=self._audit_path,
        )
        if self._positions_path == self._data_dir / "positions.json":
            ensure_published_position_commands(self._data_dir)

    def _prepare_flows(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        VersionedFlowRegistry(self._flows_path, audit_path=self._audit_path)
