"""Explicit backend registration without vendor discovery or package plugins."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from robot_platform.backends.contracts import RobotBackend

BackendFactory = Callable[..., RobotBackend]


class BackendRegistry:
    """Maps stable backend names to constructors at the composition boundary."""

    def __init__(self) -> None:
        self._factories: dict[str, BackendFactory] = {}

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

    def create(self, mode: str, config: Any, **options: Any) -> RobotBackend:
        normalized = self._normalize(mode)
        factory = self._factories.get(normalized)
        if factory is None:
            raise ValueError(f"Unknown robot backend mode: {mode}")
        return factory(config, **options)
