"""HTTP compatibility facade for the read-only library Application API."""

from __future__ import annotations

from typing import Any

from robot_platform.application import (
    RobotLibraryCatalogApplicationPort,
    RobotLibraryCatalogResponse,
)


class RobotLibraryService:
    def __init__(self, application: RobotLibraryCatalogApplicationPort) -> None:
        self._application = application

    def list_components(self) -> tuple[int, dict[str, Any]]:
        return _result(self._application.list_components())

    def get_component(self, component_id: str) -> tuple[int, dict[str, Any]]:
        return _result(self._application.get_component(component_id))

    def list_commands(
        self, *, component_id: str = "", risk_level: str = "", query: str = "",
    ) -> tuple[int, dict[str, Any]]:
        return _result(self._application.list_commands(
            component_id=component_id, risk_level=risk_level, query=query,
        ))

    def get_command(self, command_id: str) -> tuple[int, dict[str, Any]]:
        return _result(self._application.get_command(command_id))

    def list_flows(self) -> tuple[int, dict[str, Any]]:
        return _result(self._application.list_flows())

    def get_flow(self, flow_id: str) -> tuple[int, dict[str, Any]]:
        return _result(self._application.get_flow(flow_id))


def _result(response: RobotLibraryCatalogResponse) -> tuple[int, dict[str, Any]]:
    if response.ok and isinstance(response.payload, dict):
        return 200, {"ok": True, "data": response.payload}
    error = response.error
    code = getattr(error, "code", "library_state_unavailable")
    message = getattr(error, "message", "Library state is unavailable.")
    status = 404 if code.endswith("_not_found") else 400 if code == "invalid_request" else 503
    return status, {"error": {"code": code, "message": message}}
