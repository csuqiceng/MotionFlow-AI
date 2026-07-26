"""Explicit backend registration without vendor discovery or package plugins."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from robot_platform.backends.contracts import RobotBackend
from robot_platform.backends.plugin_contract import RobotBackendPlugin

BackendFactory = Callable[..., RobotBackend]


class BackendRegistry:
    """Maps stable backend names to constructors at the composition boundary."""

    def __init__(self) -> None:
        self._factories: dict[str, BackendFactory] = {}
        self._plugins: dict[str, RobotBackendPlugin] = {}

    @staticmethod
    def _normalize(name: str) -> str:
        return str(name or "").strip().lower()

    def register(
        self,
        name: str,
        factory: BackendFactory,
        *,
        aliases: Iterable[str] = (),
    ) -> None:
        names = (name, *aliases)
        normalized = tuple(self._normalize(candidate) for candidate in names)
        if not normalized[0] or any(not candidate for candidate in normalized):
            raise ValueError("Robot backend names cannot be empty")
        collision = next((candidate for candidate in normalized if candidate in self._factories), None)
        if collision is not None:
            raise ValueError(f"Robot backend mode already registered: {collision}")
        for candidate in normalized:
            self._factories[candidate] = factory

    @property
    def plugin_ids(self) -> tuple[str, ...]:
        """Stable plugin IDs in registration order."""
        return tuple(self._plugins)

    def register_plugin(self, plugin: RobotBackendPlugin) -> None:
        """Register one explicit plugin transactionally.

        Product wiring supplies plugin objects from a static allow-list.  The
        registry never imports a module path supplied by a profile or user.
        """
        plugin_id = self._normalize(getattr(plugin, "plugin_id", ""))
        plugin_version = str(getattr(plugin, "plugin_version", "")).strip()
        modes = tuple(self._normalize(mode) for mode in getattr(plugin, "backend_modes", ()))
        if not plugin_id or not plugin_version or not modes or any(not mode for mode in modes):
            raise ValueError("Robot backend plugin requires ID, version, and backend modes")
        if plugin_id in self._plugins:
            raise ValueError(f"Robot backend plugin already registered: {plugin_id}")

        factories_before = dict(self._factories)
        try:
            plugin.register(self)
            missing_modes = [mode for mode in modes if mode not in self._factories]
            if missing_modes:
                raise ValueError(
                    f"Robot backend plugin '{plugin_id}' did not register declared modes: {', '.join(missing_modes)}"
                )
        except Exception:
            self._factories = factories_before
            raise
        self._plugins[plugin_id] = plugin

    def create(self, mode: str, config: Any, **options: Any) -> RobotBackend:
        normalized = self._normalize(mode)
        factory = self._factories.get(normalized)
        if factory is None:
            raise ValueError(f"Unknown robot backend mode: {mode}")
        return factory(config, **options)
