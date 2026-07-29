"""Read-only component, command and flow catalog use cases."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class RobotLibraryCatalogError:
    code: str
    message: str


@dataclass(frozen=True)
class RobotLibraryCatalogResponse:
    payload: dict[str, Any] | None = None
    error: RobotLibraryCatalogError | None = None

    def __post_init__(self) -> None:
        if (self.payload is None) == (self.error is None):
            raise ValueError("RobotLibraryCatalogResponse requires payload or error")

    @property
    def ok(self) -> bool:
        return self.error is None


class RobotLibraryCatalogPort(Protocol):
    def list_components(self) -> list[dict[str, Any]]: ...
    def get_component(self, component_id: str) -> dict[str, Any] | None: ...
    def list_commands(self) -> list[dict[str, Any]]: ...
    def get_command(self, command_id: str) -> dict[str, Any] | None: ...
    def list_flows(self) -> list[dict[str, Any]]: ...
    def get_flow(self, flow_id: str) -> dict[str, Any] | None: ...


class RobotLibraryCatalogApplicationPort(Protocol):
    def list_components(self) -> RobotLibraryCatalogResponse: ...
    def get_component(self, component_id: str) -> RobotLibraryCatalogResponse: ...
    def list_commands(
        self, *, component_id: str = "", risk_level: str = "", query: str = "",
    ) -> RobotLibraryCatalogResponse: ...
    def get_command(self, command_id: str) -> RobotLibraryCatalogResponse: ...
    def list_flows(self) -> RobotLibraryCatalogResponse: ...
    def get_flow(self, flow_id: str) -> RobotLibraryCatalogResponse: ...


class RobotLibraryCatalogApplicationService:
    _RISK_LEVELS = frozenset({"low", "medium", "high", "critical"})

    def __init__(self, catalog: RobotLibraryCatalogPort) -> None:
        self._catalog = catalog

    def list_components(self) -> RobotLibraryCatalogResponse:
        return self._list(self._catalog.list_components)

    def get_component(self, component_id: str) -> RobotLibraryCatalogResponse:
        return self._get(
            self._catalog.get_component, component_id, "component_not_found",
        )

    def list_commands(
        self, *, component_id: str = "", risk_level: str = "", query: str = "",
    ) -> RobotLibraryCatalogResponse:
        if risk_level and risk_level not in self._RISK_LEVELS:
            return _failure("invalid_request", f"invalid risk_level: {risk_level}")
        if not all(isinstance(value, str) for value in (component_id, risk_level, query)):
            return _failure("invalid_request", "Catalog filters must be strings.")
        try:
            items = self._catalog.list_commands()
            if component_id:
                items = [item for item in items if item.get("component_id") == component_id]
            if risk_level:
                items = [item for item in items if item.get("risk_level") == risk_level]
            if query:
                term = query.casefold()
                items = [
                    item for item in items
                    if term in str(item.get("name", "")).casefold()
                    or any(
                        term in str(alias).casefold()
                        for alias in item.get("aliases", [])
                    )
                ]
            public = deepcopy(items)
        except Exception:
            return _failure("library_state_unavailable", "Library state is unavailable.")
        return RobotLibraryCatalogResponse(payload={"items": public, "total": len(public)})

    def get_command(self, command_id: str) -> RobotLibraryCatalogResponse:
        return self._get(self._catalog.get_command, command_id, "command_not_found")

    def list_flows(self) -> RobotLibraryCatalogResponse:
        return self._list(self._catalog.list_flows)

    def get_flow(self, flow_id: str) -> RobotLibraryCatalogResponse:
        return self._get(self._catalog.get_flow, flow_id, "flow_not_found")

    def _list(self, reader: Any) -> RobotLibraryCatalogResponse:
        try:
            items = deepcopy(reader())
            if not isinstance(items, list):
                raise TypeError("catalog list is invalid")
        except Exception:
            return _failure("library_state_unavailable", "Library state is unavailable.")
        return RobotLibraryCatalogResponse(payload={"items": items, "total": len(items)})

    def _get(
        self, reader: Any, identifier: str, not_found_code: str,
    ) -> RobotLibraryCatalogResponse:
        if not isinstance(identifier, str) or not identifier.strip():
            return _failure("invalid_request", "Catalog identifier is required.")
        try:
            item = reader(identifier)
            if item is None:
                return _failure(not_found_code, "Library resource was not found.")
            public = deepcopy(item)
            if not isinstance(public, dict):
                raise TypeError("catalog item is invalid")
        except Exception:
            return _failure("library_state_unavailable", "Library state is unavailable.")
        return RobotLibraryCatalogResponse(payload=public)


def _failure(code: str, message: str) -> RobotLibraryCatalogResponse:
    return RobotLibraryCatalogResponse(error=RobotLibraryCatalogError(code, message))
