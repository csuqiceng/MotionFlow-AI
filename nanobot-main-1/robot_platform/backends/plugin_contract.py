"""Static plugin contract for vendor-specific robot backends."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from robot_platform.backends.registry import BackendRegistry


@runtime_checkable
class RobotBackendPlugin(Protocol):
    """Register known backend modes at a product composition boundary."""

    plugin_id: str
    plugin_version: str
    backend_modes: tuple[str, ...]

    def register(self, registry: "BackendRegistry") -> None:
        ...
