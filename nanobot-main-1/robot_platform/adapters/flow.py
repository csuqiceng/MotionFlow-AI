"""Filesystem adapter for published Flow query and alias resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from robot_platform.flow.aliases import FlowAlias
from robot_platform.flow.registry import FlowRegistry
from robot_platform.library.transaction import synchronized_library_method


class FileRobotFlowAdapter:
    def __init__(
        self,
        data_dir: str | Path,
        *,
        flows_path: str | Path | None = None,
        aliases_path: str | Path | None = None,
    ) -> None:
        self._data_dir = Path(data_dir)
        self._flows_path = Path(flows_path or self._data_dir / "flows.json")
        self._aliases_path = Path(
            aliases_path or self._data_dir / "flow_aliases.json",
        )

    @synchronized_library_method
    def list_entries(self) -> list[Any]:
        return self._registry().list_all()

    @synchronized_library_method
    def resolve(self, name: str, *, alias: str = "") -> tuple[str, Any | None]:
        resolved_name = str(name).strip()
        if alias:
            resolved_name = FlowAlias(self._aliases_path).resolve(alias) or ""
            if not resolved_name:
                return "alias_not_found", None
        entry = self._registry().get(resolved_name)
        return ("found", entry) if entry is not None else ("flow_not_found", None)

    def _registry(self) -> FlowRegistry:
        return FlowRegistry(self._flows_path)
