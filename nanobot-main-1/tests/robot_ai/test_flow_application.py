from __future__ import annotations

from unittest.mock import MagicMock

from robot_platform.application import (
    AuthenticatedPrincipal,
    RobotDryRunResponse,
    RobotFlowApplicationService,
    RobotFlowManagementApplicationService,
    RobotFlowManagementCommand,
    RobotFlowManagementResponse,
    RobotFlowQuery,
    RobotFlowResponse,
    RobotLibraryCatalogResponse,
    RobotLibraryExecutionApplicationService,
    RobotLibraryExecutionCommand,
)
from robot_platform.flow import FlowEntry, FlowStep


def _principal(role: str = "operator") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal("user-1", role, "session-1", "test")


def _entry() -> FlowEntry:
    return FlowEntry(
        name="Pick",
        flow_id="pick",
        description="safe",
        steps=[FlowStep(1, "delay", 110, {"seconds": 1}, description="wait")],
        confirmed=True,
        version=2,
    )


def test_flow_role_is_rejected_before_catalog_access() -> None:
    catalog = MagicMock()
    service = RobotFlowApplicationService(catalog, MagicMock())

    response = service.query(RobotFlowQuery(_principal("viewer"), "list"))

    assert response.error.code == "flow_forbidden"
    catalog.list_entries.assert_not_called()


def test_flow_list_and_get_construct_public_dto() -> None:
    catalog = MagicMock()
    catalog.list_entries.return_value = [_entry()]
    catalog.resolve.return_value = ("found", _entry())
    service = RobotFlowApplicationService(catalog, MagicMock())

    listed = service.query(RobotFlowQuery(_principal(), "list"))
    got = service.query(RobotFlowQuery(_principal(), "get", "Pick"))

    assert listed.payload["count"] == 1
    assert listed.payload["flows"][0]["steps"][0] == {
        "step_id": 1,
        "action": "delay",
        "func_id": 110,
        "params": {"seconds": 1},
        "position_name": None,
        "spd_pct": 50,
        "description": "wait",
    }
    assert got.payload["flow"]["flow_id"] == "pick"


def test_flow_alias_failure_does_not_call_dry_run() -> None:
    catalog = MagicMock()
    catalog.resolve.return_value = ("alias_not_found", None)
    dry_run = MagicMock()
    service = RobotFlowApplicationService(catalog, dry_run)

    response = service.query(RobotFlowQuery(
        _principal(), "preview", alias="missing",
    ))

    assert response.error.code == "flow_alias_not_found"
    dry_run.preview_flow_entry.assert_not_called()


def test_flow_preview_resolves_once_and_uses_dry_run_application() -> None:
    entry = _entry()
    catalog = MagicMock()
    catalog.resolve.return_value = ("found", entry)
    dry_run = MagicMock()
    dry_run.preview_flow_entry.return_value = RobotDryRunResponse(payload={
        "ok": True, "state": "flow_completed", "data": {"total_steps": 1},
    })
    service = RobotFlowApplicationService(catalog, dry_run)
    resolved = MagicMock()
    on_step = MagicMock()

    response = service.query(
        RobotFlowQuery(_principal(), "preview", "Pick"),
        on_resolved=resolved,
        on_step=on_step,
    )

    assert response.ok
    assert response.payload["result"]["state"] == "flow_completed"
    catalog.resolve.assert_called_once_with("Pick", alias="")
    dry_run.preview_flow_entry.assert_called_once()
    assert dry_run.preview_flow_entry.call_args.kwargs["on_step"] is on_step
    resolved.assert_called_once()


def test_flow_management_rejects_operator_before_adapter() -> None:
    adapter = MagicMock()
    service = RobotFlowManagementApplicationService(adapter)

    response = service.execute(RobotFlowManagementCommand(
        _principal("operator"), "list",
    ))

    assert response.error.code == "flow_forbidden"
    adapter.execute.assert_not_called()


def test_flow_management_passes_server_principal_as_actor() -> None:
    adapter = MagicMock()
    adapter.execute.return_value = RobotFlowManagementResponse(payload={
        "entities": [],
    })
    service = RobotFlowManagementApplicationService(adapter)

    response = service.execute(RobotFlowManagementCommand(
        _principal("engineer"), "list", body={"actor": "forged"},
    ))

    assert response.ok
    assert adapter.execute.call_args.kwargs["actor"] == "test:user-1"


def test_library_execution_rejects_role_before_registry_or_catalog() -> None:
    registry = MagicMock()
    catalog = MagicMock()
    service = RobotLibraryExecutionApplicationService(
        registry, catalog, MagicMock(), MagicMock(),
    )

    response = service.execute(RobotLibraryExecutionCommand(
        _principal("viewer"), "start_flow", source_id="pick",
    ))

    assert response.error.code == "execution_forbidden"
    registry.start.assert_not_called()
    catalog.get_command.assert_not_called()


def test_library_flow_execution_uses_flow_and_dry_run_ports() -> None:
    registry = MagicMock()
    registry.start.return_value = "execution-1"
    flows = MagicMock()
    flows.query.return_value = RobotFlowResponse(payload={
        "flow": _entry().to_dict(),
    })
    dry_run = MagicMock()
    dry_run.preview_flow_entry.return_value = RobotDryRunResponse(payload={
        "ok": True, "state": "flow_completed", "data": {"total_steps": 1},
    })
    service = RobotLibraryExecutionApplicationService(
        registry, MagicMock(), flows, dry_run,
    )

    response = service.execute(RobotLibraryExecutionCommand(
        _principal(), "start_flow", source_id="pick", body={},
    ))

    assert response.accepted
    assert response.payload == {"execution_id": "execution-1", "state": "queued"}
    worker = registry.start.call_args.args[1]
    result = worker(MagicMock(), MagicMock())
    assert result["state"] == "flow_completed"
    dry_run.preview_flow_entry.assert_called_once()


def test_library_command_real_execution_is_rejected_before_registry_start() -> None:
    registry = MagicMock()
    catalog = MagicMock()
    catalog.get_command.return_value = RobotLibraryCatalogResponse(payload={
        "name": "wait", "component_id": "delay", "parameters": {"seconds": 1},
    })
    catalog.get_component.return_value = RobotLibraryCatalogResponse(payload={
        "id": "delay", "func_num": 110,
    })
    service = RobotLibraryExecutionApplicationService(
        registry, catalog, MagicMock(), MagicMock(),
    )

    response = service.execute(RobotLibraryExecutionCommand(
        _principal(), "start_command", source_id="wait",
        body={"execute_real": True},
    ))

    assert response.error.code == "staged_execution_required"
    registry.start.assert_not_called()
