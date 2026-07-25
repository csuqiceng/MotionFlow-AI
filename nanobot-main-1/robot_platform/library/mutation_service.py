"""The sole version-safe mutation boundary for robot library resources."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from robot_platform.flow.versioned_registry import VersionedFlowRegistry
from robot_platform.library.catalog import ComponentCatalog
from robot_platform.library.migration import initialize_robot_libraries
from robot_platform.library.models import normalize_id
from robot_platform.library.versioned_registry import VersionedCommandRegistry
from robot_platform.positions.registry import AXIS_NAMES, NamedPosition, PositionRegistry


class RobotLibraryMutationService:
    """Create library entries without ever using legacy registry writers."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def create(self, resource_type: str, payload: dict[str, Any], *, actor: str) -> dict[str, Any]:
        if resource_type == "position":
            return self.create_position(payload, actor=actor)
        if resource_type == "command":
            return self.create_command(payload, actor=actor)
        if resource_type == "flow":
            return self.create_flow(payload, actor=actor)
        raise ValueError("resource_type must be position, command, or flow")

    def create_position(self, payload: dict[str, Any], *, actor: str) -> dict[str, Any]:
        name = str(payload.get("name", "")).strip()
        pose_data = payload.get("pose")
        if not name or not isinstance(pose_data, dict):
            raise ValueError("position name and pose are required")
        try:
            pose = [float(pose_data[axis]) for axis in AXIS_NAMES]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("pose must contain numeric x/y/z/rx/ry/rz") from exc
        registry = PositionRegistry(self.data_dir / "positions.json")
        if registry.get(name) is not None:
            raise ValueError(f"Position '{name}' already exists")
        entry = registry.register(NamedPosition(name=name, pose=pose, spd=float(payload.get("spd", 50.0)), move_type=int(payload.get("move_type", 0))))
        return {"resource_type": "position", "position": entry.to_dict(), "actor": actor}

    def update_position(self, payload: dict[str, Any], *, actor: str) -> dict[str, Any]:
        name = str(payload.get("name", "")).strip()
        pose_data = payload.get("pose")
        if not name or not isinstance(pose_data, dict):
            raise ValueError("position name and pose are required")
        try:
            pose = [float(pose_data[axis]) for axis in AXIS_NAMES]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("pose must contain numeric x/y/z/rx/ry/rz") from exc
        registry = PositionRegistry(self.data_dir / "positions.json")
        existing = registry.get(name)
        if existing is None:
            raise ValueError(f"Position '{name}' does not exist")
        entry = registry.register(
            NamedPosition(
                name=existing.name,
                pose=pose,
                spd=float(payload.get("spd", existing.spd)),
                move_type=int(payload.get("move_type", existing.move_type)),
            )
        )
        return {"resource_type": "position", "position": entry.to_dict(), "actor": actor}

    def delete_position(self, payload: dict[str, Any], *, actor: str) -> dict[str, Any]:
        name = str(payload.get("name", "")).strip()
        if not name:
            raise ValueError("position name is required")
        registry = PositionRegistry(self.data_dir / "positions.json")
        existing = registry.get(name)
        if existing is None:
            raise ValueError(f"Position '{name}' does not exist")
        registry.remove(existing.name)
        return {"resource_type": "position", "deleted": {"name": existing.name}, "actor": actor}

    def create_command(self, payload: dict[str, Any], *, actor: str) -> dict[str, Any]:
        name = str(payload.get("name", "")).strip()
        component_id = str(payload.get("component_id", "")).strip()
        parameters = payload.get("parameters")
        if not name or not component_id or not isinstance(parameters, dict):
            raise ValueError("command name, component_id, and parameters are required")
        component = ComponentCatalog().get(component_id)
        if component is None:
            raise ValueError(f"Unknown component '{component_id}'")
        _validate_parameters(component, parameters)
        path = self.data_dir / "commands.json"
        initialize_robot_libraries(commands_path=path, audit_path=self.data_dir / "audit.jsonl")
        registry = VersionedCommandRegistry(path, audit_path=self.data_dir / "audit.jsonl")
        command_id = normalize_id(name)
        if registry.get_entity(command_id) is not None:
            raise ValueError(f"Command '{name}' already exists")
        registry.create_entity(command_id, component_id, name, dict(parameters), aliases=[str(item) for item in payload.get("aliases", [])], description=str(payload.get("description", "")), actor=actor)
        entity = registry.publish(command_id, component_risk_level=component.risk_level, actor=actor)
        return {"resource_type": "command", "command": entity}

    def create_flow(self, payload: dict[str, Any], *, actor: str) -> dict[str, Any]:
        name = str(payload.get("name", "")).strip()
        steps = payload.get("steps")
        if not name or not isinstance(steps, list):
            raise ValueError("flow name and steps are required")
        flow_id = "_".join(name.casefold().split())
        registry = VersionedFlowRegistry(self.data_dir / "flows.json", audit_path=self.data_dir / "audit.jsonl")
        if registry.get_entity(flow_id) is not None:
            raise ValueError(f"Flow '{name}' already exists")
        registry.create_entity(flow_id, name, steps, step_delay_ms=payload.get("step_delay_ms", 1000), rehearsal_spd=payload.get("rehearsal_spd", 20), description=str(payload.get("description", "")), actor=actor)
        errors = registry.validate_draft(flow_id)
        if errors:
            registry.archive(flow_id, actor=actor)
            raise ValueError("; ".join(errors))
        entity = registry.publish(flow_id, actor=actor)
        return {"resource_type": "flow", "flow": entity}


def _validate_parameters(component: Any, parameters: dict[str, Any]) -> None:
    fields = {field.name: field for field in component.parameters}
    unknown = set(parameters) - set(fields)
    if unknown:
        raise ValueError(f"Unknown parameter '{sorted(unknown)[0]}'")
    types = {"int": int, "float": (int, float), "str": str, "bool": bool}
    for field in component.parameters:
        if field.name not in parameters:
            if field.required:
                raise ValueError(f"Missing required parameter '{field.name}'")
            continue
        value = parameters[field.name]
        expected = types.get(field.type)
        if expected is not None and (not isinstance(value, expected) or isinstance(value, bool) and field.type in {"int", "float"}):
            raise ValueError(f"Parameter '{field.name}' must be {field.type}")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if field.minimum is not None and value < field.minimum:
                raise ValueError(f"Parameter '{field.name}' must be >= {field.minimum}")
            if field.maximum is not None and value > field.maximum:
                raise ValueError(f"Parameter '{field.name}' must be <= {field.maximum}")
