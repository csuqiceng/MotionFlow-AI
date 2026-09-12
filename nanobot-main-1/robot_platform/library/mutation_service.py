"""The sole version-safe mutation boundary for robot library resources."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from robot_platform.flow.versioned_registry import VersionedFlowRegistry
from robot_platform.library.catalog import ComponentCatalog
from robot_platform.library.migration import initialize_robot_libraries
from robot_platform.library.models import normalize_id
from robot_platform.library.transaction import library_transaction
from robot_platform.library.versioned_registry import VersionedCommandRegistry
from robot_platform.positions.naming import generated_position_aliases
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
        with library_transaction(
            self.data_dir,
            rollback_files=("positions.json", "commands.json"),
        ):
            return self._create_position(payload, actor=actor)

    def _create_position(self, payload: dict[str, Any], *, actor: str) -> dict[str, Any]:
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
        command = self._upsert_position_command(entry, actor=actor)
        return {"resource_type": "position", "position": entry.to_dict(), "command": command, "actor": actor}

    def update_position(self, payload: dict[str, Any], *, actor: str) -> dict[str, Any]:
        with library_transaction(
            self.data_dir,
            rollback_files=("positions.json", "commands.json"),
        ):
            return self._update_position(payload, actor=actor)

    def _update_position(self, payload: dict[str, Any], *, actor: str) -> dict[str, Any]:
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
        command = self._upsert_position_command(entry, actor=actor)
        return {"resource_type": "position", "position": entry.to_dict(), "command": command, "actor": actor}

    def delete_position(self, payload: dict[str, Any], *, actor: str) -> dict[str, Any]:
        with library_transaction(
            self.data_dir, rollback_files=("positions.json",),
        ):
            return self._delete_position(payload, actor=actor)

    def _delete_position(self, payload: dict[str, Any], *, actor: str) -> dict[str, Any]:
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
        with library_transaction(
            self.data_dir, rollback_files=("commands.json",),
        ):
            return self._create_command(payload, actor=actor)

    def _create_command(self, payload: dict[str, Any], *, actor: str) -> dict[str, Any]:
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

    def _upsert_position_command(
        self,
        position: NamedPosition,
        *,
        actor: str,
        overwrite_existing: bool = True,
    ) -> dict[str, Any]:
        """Expose each saved location as an executable Func108 library command."""
        path = self.data_dir / "commands.json"
        audit_path = self.data_dir / "audit.jsonl"
        initialize_robot_libraries(commands_path=path, audit_path=audit_path)
        registry = VersionedCommandRegistry(path, audit_path=audit_path)
        command_id = normalize_id(position.name)
        parameters = {
            **{f"target_{axis}": float(position.pose[index]) for index, axis in enumerate(AXIS_NAMES)},
            "spd_pct": float(position.spd),
            "acc_pct": float(position.spd),
            "dec_pct": float(position.spd),
            "move_type": int(position.move_type),
            "stop_cmd": 0,
        }
        entity = registry.get_entity(command_id)
        if entity is None:
            registry.create_entity(
                command_id,
                "linear_move",
                position.name,
                parameters,
                aliases=generated_position_aliases(position.name),
                description=f"移动到已保存位置“{position.name}”。",
                actor=actor,
            )
        else:
            published = entity.get("versions", {}).get(str(entity.get("published_version")), {})
            if published.get("component_id") not in {None, "linear_move"}:
                raise ValueError(f"Position '{position.name}' conflicts with a non-motion command")
            # Packaged command definitions are the source of truth for their
            # full motion parameters (for example acceleration and deceleration).
            # A position import must only fill a missing command, never rewrite
            # an existing project command from the smaller position schema.
            if not overwrite_existing:
                aliases = list(published.get("aliases", []))
                generated = generated_position_aliases(position.name)
                if all(alias in aliases for alias in generated):
                    return entity
                if entity.get("draft") is None:
                    entity = registry.start_draft(command_id, actor=actor)
                draft = entity["draft"]
                registry.update_draft(
                    command_id,
                    expected_revision=int(draft["revision"]),
                    name=str(published.get("name", position.name)),
                    aliases=[*aliases, *[alias for alias in generated if alias not in aliases]],
                    description=str(published.get("description", "")),
                    component_id="linear_move",
                    parameters=dict(published.get("parameters", parameters)),
                    actor=actor,
                )
                return registry.publish(command_id, component_risk_level="high", actor=actor)
            if entity.get("draft") is None:
                entity = registry.start_draft(command_id, actor=actor)
            draft = entity["draft"]
            registry.update_draft(
                command_id,
                expected_revision=int(draft["revision"]),
                name=position.name,
                aliases=generated_position_aliases(position.name),
                description=f"移动到已保存位置“{position.name}”。",
                component_id="linear_move",
                parameters=parameters,
                actor=actor,
            )
        return registry.publish(command_id, component_risk_level="high", actor=actor)

    def create_flow(self, payload: dict[str, Any], *, actor: str) -> dict[str, Any]:
        with library_transaction(
            self.data_dir, rollback_files=("flows.json",),
        ):
            return self._create_flow(payload, actor=actor)

    def _create_flow(self, payload: dict[str, Any], *, actor: str) -> dict[str, Any]:
        name = str(payload.get("name", "")).strip()
        steps = payload.get("steps")
        if not name or not isinstance(steps, list):
            raise ValueError("flow name and steps are required")
        flow_id = "_".join(name.casefold().split())
        registry = VersionedFlowRegistry(self.data_dir / "flows.json", audit_path=self.data_dir / "audit.jsonl")
        if registry.get_entity(flow_id) is not None:
            raise ValueError(f"Flow '{name}' already exists")
        registry.create_entity(
            flow_id, name, steps,
            step_delay_ms=payload.get("step_delay_ms", 1000),
            rehearsal_spd=payload.get("rehearsal_spd", 20),
            description=str(payload.get("description", "")),
            node_graph=deepcopy(payload.get("node_graph")),
            actor=actor,
        )
        errors = registry.validate_draft(flow_id)
        if errors:
            registry.archive(flow_id, actor=actor)
            raise ValueError("; ".join(errors))
        entity = registry.publish(flow_id, actor=actor)
        return {"resource_type": "flow", "flow": entity}


def ensure_published_position_commands(data_dir: str | Path) -> None:
    """Repair/migrate saved locations into visible command-library entries.

    This is idempotent and intentionally runs at the library read boundary so
    installations made before this feature also receive their existing named
    positions without asking the operator to save them again.
    """
    service = RobotLibraryMutationService(data_dir)
    with library_transaction(
        service.data_dir, rollback_files=("commands.json",),
    ):
        registry = PositionRegistry(service.data_dir / "positions.json")
        for position in registry.list_all():
            service._upsert_position_command(
                position,
                actor="system:position-library-sync",
                overwrite_existing=False,
            )


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
