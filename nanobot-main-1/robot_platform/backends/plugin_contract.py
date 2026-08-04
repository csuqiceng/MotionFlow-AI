"""Static plugin contract for vendor-specific robot backends."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from robot_platform.backends.registry import BackendRegistry


@dataclass(frozen=True)
class BackendManifest:
    plugin_id: str
    plugin_version: str
    backend_modes: tuple[str, ...]
    protocol_version: int = 1
    required_ports: tuple[str, ...] = ("lifecycle", "diagnostics")
    configuration_schema: dict[str, Any] = field(default_factory=dict)
    core_compatibility: str = ">=1,<2"
    dependencies: tuple[str, ...] = ()
    health_contract_version: int = 1
    migration_version: int = 1

    @classmethod
    def from_plugin(cls, plugin: Any) -> "BackendManifest":
        manifest = cls(
            plugin_id=str(plugin.plugin_id).strip(),
            plugin_version=str(plugin.plugin_version).strip(),
            backend_modes=tuple(str(mode).strip() for mode in plugin.backend_modes),
            protocol_version=int(getattr(plugin, "protocol_version", 2)),
            required_ports=tuple(
                str(port).strip()
                for port in getattr(
                    plugin, "required_ports", ("lifecycle", "diagnostics"),
                )
            ),
            configuration_schema=deepcopy(getattr(plugin, "configuration_schema", {})),
            core_compatibility=str(getattr(plugin, "core_compatibility", ">=1,<2")).strip(),
            dependencies=tuple(str(item).strip() for item in getattr(plugin, "dependencies", ())),
            health_contract_version=int(getattr(plugin, "health_contract_version", 1)),
            migration_version=int(getattr(plugin, "migration_version", 1)),
        )
        if not manifest.plugin_id or not manifest.plugin_version or not manifest.backend_modes:
            raise ValueError("Backend manifest requires ID, version, and modes")
        if any(not mode for mode in manifest.backend_modes):
            raise ValueError("Backend manifest modes cannot be empty")
        allowed_ports = {
            "lifecycle", "diagnostics", "motion", "system_control", "io", "operation",
        }
        if (
            not manifest.required_ports
            or any(port not in allowed_ports for port in manifest.required_ports)
            or len(set(manifest.required_ports)) != len(manifest.required_ports)
        ):
            raise ValueError("Backend manifest required ports are invalid")
        if not isinstance(manifest.configuration_schema, dict):
            raise ValueError("Backend manifest configuration schema must be an object")
        if not manifest.core_compatibility or any(not item for item in manifest.dependencies):
            raise ValueError("Backend manifest compatibility/dependencies are invalid")
        if manifest.health_contract_version < 1 or manifest.migration_version < 1:
            raise ValueError("Backend manifest contract versions must be positive")
        return manifest

    def to_public_dict(self, *, protocol_version: int | None = None) -> dict[str, object]:
        version = self.protocol_version if protocol_version is None else int(protocol_version)
        if version not in {1, 2}:
            raise ValueError("Backend manifest public protocol must be 1 or 2")
        result: dict[str, object] = {
            "protocol_version": version,
            "plugin_id": self.plugin_id,
            "plugin_version": self.plugin_version,
            "backend_modes": list(self.backend_modes),
        }
        if version == 2:
            result.update({
                "required_ports": list(self.required_ports),
                "configuration_schema": deepcopy(self.configuration_schema),
                "core_compatibility": self.core_compatibility,
                "dependencies": list(self.dependencies),
                "health_contract_version": self.health_contract_version,
                "migration_version": self.migration_version,
            })
        return result


@runtime_checkable
class RobotBackendPlugin(Protocol):
    """Register known backend modes at a product composition boundary."""

    plugin_id: str
    plugin_version: str
    backend_modes: tuple[str, ...]
    required_ports: tuple[str, ...]

    def register(self, registry: "BackendRegistry") -> None:
        ...
