"""Portable import/export for the versioned robot library."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from robot_platform import (
    ComponentCatalog, VersionedCommandRegistry, VersionedFlowRegistry,
    apply_transfer_payload, build_transfer_payload, initialize_robot_libraries,
)
from robot_server.identity_api import RobotIdentityService


class RobotLibraryTransferService:
    def __init__(self, data_dir: Path, identity: RobotIdentityService) -> None:
        self._data_dir = data_dir
        self._identity = identity

    def export(self, token: str) -> tuple[int, dict[str, Any]]:
        _session, error = self._identity.require_engineer_session(token)
        if error is not None:
            return error
        return 200, {
            "ok": True,
            "data": build_transfer_payload(
                commands=self._command_registry().list_entities(),
                flows=self._flow_registry().list_entities(),
            ),
        }

    def import_payload(self, token: str, body: Any) -> tuple[int, dict[str, Any]]:
        _session, error = self._identity.require_engineer_session(token)
        if error is not None:
            return error
        if not isinstance(body, dict) or not isinstance(body.get("payload"), dict):
            return 400, {"error": {"code": "invalid_request", "message": "payload must be an object."}}
        components = {component.id for component in ComponentCatalog().list_all()}
        result = apply_transfer_payload(
            body["payload"],
            command_registry=self._command_registry(),
            flow_registry=self._flow_registry(),
            component_ids=components,
            strategy=str(body.get("strategy", "skip")),
        )
        if result["errors"]:
            return 400, {
                "ok": False,
                "data": result,
                "error": {"code": "invalid_transfer", "message": result["errors"][0]},
            }
        return 200, {"ok": True, "data": result}

    def _command_registry(self) -> VersionedCommandRegistry:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        commands_path = self._data_dir / "commands.json"
        audit_path = self._data_dir / "audit.jsonl"
        initialize_robot_libraries(commands_path=commands_path, audit_path=audit_path)
        return VersionedCommandRegistry(commands_path, audit_path=audit_path)

    def _flow_registry(self) -> VersionedFlowRegistry:
        return VersionedFlowRegistry(
            self._data_dir / "flows.json", audit_path=self._data_dir / "audit.jsonl"
        )
