from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest

from robot_platform.application import (
    AuthenticatedPrincipal,
    InMemoryLibraryConfirmationStore,
    RobotLibraryApplicationService,
    RobotLibraryConfirmCommand,
    RobotLibraryError,
    RobotLibraryManagementApplicationService,
    RobotLibraryManagementCommand,
    RobotLibraryManagementResponse,
    RobotLibraryPreviewCommand,
    RobotLibraryResponse,
    RobotLibraryTransferApplicationService,
    RobotPositionApplicationService,
    RobotPositionMaintenanceApplicationService,
    RobotPositionQuery,
)


def _principal(
    actor: str = "operator-1", role: str = "operator", session: str = "session-1",
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(actor, role, session, "test")


def _catalog() -> MagicMock:
    catalog = MagicMock()
    catalog.positions.return_value = [{
        "name": "A", "pose": [1, 2, 3, 4, 5, 6], "spd": 5,
        "path": "C:/secret/positions.json",
    }]
    catalog.position_commands.return_value = [{
        "id": "command-a", "command_id": "command-a", "name": "位置A",
        "aliases": ["A"], "pose": {"x": 1, "y": 2, "z": 3, "rx": 4, "ry": 5, "rz": 6},
        "controller_host": "secret-host",
    }]
    catalog.flows.return_value = [{
        "flow_id": "flow-a", "name": "流程A", "description": "safe",
        "steps": [{"secret": "controller-password"}],
    }]
    catalog.find.side_effect = lambda name: (
        ("position", catalog.positions.return_value[0]) if name.casefold() == "a"
        else ("flow", catalog.flows.return_value[0]) if name == "流程A"
        else None
    )
    catalog.resolve.side_effect = lambda name: (
        {"x": 1, "y": 2, "z": 3, "rx": 4, "ry": 5, "rz": 6}
        if name.casefold() == "a" else None
    )
    return catalog


def test_position_role_is_rejected_before_catalog_read() -> None:
    catalog = _catalog()
    service = RobotPositionApplicationService(catalog)

    result = service.query(RobotPositionQuery(
        _principal(role="viewer"), "list",
    ))

    assert result.error.code == "position_forbidden"
    catalog.positions.assert_not_called()


def test_position_list_builds_public_dto_without_store_or_flow_step_details() -> None:
    service = RobotPositionApplicationService(_catalog())

    result = service.query(RobotPositionQuery(_principal(), "list"))

    assert result.ok
    assert result.payload["count"] == 3
    assert result.payload["positions"][0] == {
        "name": "A", "pose": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0], "spd": 5.0,
    }
    assert result.payload["flows"][0]["step_count"] == 1
    rendered = repr(result)
    assert "C:/secret" not in rendered
    assert "secret-host" not in rendered
    assert "controller-password" not in rendered


def test_position_resolve_and_flow_rejection_are_application_owned() -> None:
    service = RobotPositionApplicationService(_catalog())

    resolved = service.query(RobotPositionQuery(_principal(), "resolve", "A"))
    flow = service.query(RobotPositionQuery(_principal(), "resolve", "流程A"))

    assert resolved.payload["pose"]["x"] == 1.0
    assert flow.error.code == "position_not_single_pose"


def _library_service(mutations=None):
    return RobotLibraryApplicationService(
        mutations or MagicMock(), InMemoryLibraryConfirmationStore(),
    )


def _preview(service, *, principal=None, operation="create", resource_type="position", payload=None):
    return service.preview(RobotLibraryPreviewCommand(
        principal or _principal(), operation, resource_type,
        payload or {
            "name": "A",
            "pose": {"x": 1, "y": 2, "z": 3, "rx": 4, "ry": 5, "rz": 6},
        },
    ))


def test_library_preview_freezes_payload_and_mutates_only_after_exact_confirmation() -> None:
    mutations = MagicMock()
    mutations.create.return_value = {
        "resource_type": "position", "position": {"name": "A"},
    }
    service = _library_service(mutations)
    source = {
        "name": "A",
        "pose": {"x": 1, "y": 2, "z": 3, "rx": 4, "ry": 5, "rz": 6},
    }
    preview = _preview(service, payload=source)
    source["pose"]["x"] = 999

    confirmed = service.confirm(RobotLibraryConfirmCommand(
        _principal(), preview.payload["confirmation_token"],
    ))

    assert preview.confirmation_issued and not preview.mutation_applied
    assert confirmed.mutation_applied
    mutations.create.assert_called_once()
    assert mutations.create.call_args.args[1]["pose"]["x"] == 1


def test_wrong_principal_cannot_consume_another_confirmation() -> None:
    mutations = MagicMock()
    mutations.create.return_value = {"resource_type": "position"}
    service = _library_service(mutations)
    preview = _preview(service)
    token = preview.payload["confirmation_token"]

    denied = service.confirm(RobotLibraryConfirmCommand(
        _principal(actor="operator-2"), token,
    ))
    accepted = service.confirm(RobotLibraryConfirmCommand(_principal(), token))

    assert denied.error.code == "library_confirmation_forbidden"
    assert accepted.ok
    mutations.create.assert_called_once()


def test_operator_cannot_preview_update_or_delete() -> None:
    confirmations = MagicMock()
    service = RobotLibraryApplicationService(MagicMock(), confirmations)

    response = _preview(service, operation="delete")

    assert response.error.code == "library_forbidden"
    confirmations.issue.assert_not_called()


def test_concurrent_library_confirmation_applies_mutation_once() -> None:
    mutations = MagicMock()
    mutations.create.return_value = {"resource_type": "position"}
    service = _library_service(mutations)
    preview = _preview(service)
    command = RobotLibraryConfirmCommand(
        _principal(), preview.payload["confirmation_token"],
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(service.confirm, (command, command)))

    assert sum(response.ok for response in responses) == 1
    assert {response.error.code for response in responses if not response.ok} == {
        "library_confirmation_expired",
    }
    mutations.create.assert_called_once()


def test_library_adapter_exception_is_sanitized_and_token_is_one_use() -> None:
    mutations = MagicMock()
    mutations.create.side_effect = RuntimeError("C:/secret/library.json")
    service = _library_service(mutations)
    preview = _preview(service)
    command = RobotLibraryConfirmCommand(
        _principal(), preview.payload["confirmation_token"],
    )

    first = service.confirm(command)
    second = service.confirm(command)

    assert first.error.code == "library_state_unavailable"
    assert "C:/secret" not in repr(first)
    assert second.error.code == "library_confirmation_expired"


def test_library_success_dto_ignores_untrusted_adapter_fields() -> None:
    mutations = MagicMock()
    mutations.create.return_value = {
        "resource_type": "position",
        "position": {"name": "A", "path": "C:/secret/positions.json"},
        "controller_host": "10.0.0.8",
        "secret": "controller-password",
    }
    service = _library_service(mutations)
    preview = _preview(service)

    response = service.confirm(RobotLibraryConfirmCommand(
        _principal(), preview.payload["confirmation_token"],
    ))

    assert response.payload == {
        "state": "library_saved",
        "operation": "create",
        "resource_type": "position",
        "name": "A",
        "position": {
            "name": "A",
            "pose": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        },
    }
    assert "C:/secret" not in repr(response)


def test_library_response_requires_exactly_one_result() -> None:
    with pytest.raises(ValueError):
        RobotLibraryResponse()
    with pytest.raises(ValueError):
        RobotLibraryResponse(
            payload={}, error=RobotLibraryError("code", "message"),
        )


def test_command_management_role_is_rejected_before_adapter() -> None:
    adapter = MagicMock()
    service = RobotLibraryManagementApplicationService(adapter)

    response = service.execute(RobotLibraryManagementCommand(
        _principal(role="operator"), "list",
    ))

    assert response.error.code == "library_forbidden"
    adapter.execute.assert_not_called()


def test_command_management_passes_trusted_actor_not_request_body_actor() -> None:
    adapter = MagicMock()
    adapter.execute.return_value = RobotLibraryManagementResponse(payload={"ok": True})
    service = RobotLibraryManagementApplicationService(adapter)

    response = service.execute(RobotLibraryManagementCommand(
        _principal(actor="engineer-1", role="engineer"),
        "create",
        body={"name": "x", "actor": "forged"},
    ))

    assert response.ok
    assert adapter.execute.call_args.kwargs["actor"] == "test:engineer-1"


def test_position_maintenance_role_is_rejected_before_adapter() -> None:
    adapter = MagicMock()
    service = RobotPositionMaintenanceApplicationService(adapter)

    response = service.execute(_principal(), "preview")

    assert response.error.code == "library_forbidden"
    adapter.preview.assert_not_called()


def test_position_maintenance_constructs_whitelisted_public_dto() -> None:
    adapter = MagicMock()
    adapter.apply.return_value = {
        "removed_count": 1,
        "removed_names": ["temporary"],
        "preserved_referenced_count": 0,
        "preserved_referenced_names": [],
        "backup_id": "positions.backup.json",
        "backup_path": "C:/secret/positions.backup.json",
        "controller_host": "10.0.0.8",
        "secret": "controller-password",
    }
    service = RobotPositionMaintenanceApplicationService(adapter)

    response = service.execute(_principal(role="engineer"), "apply")

    assert response.payload == {
        "removed_count": 1,
        "removed_names": ["temporary"],
        "preserved_referenced_count": 0,
        "preserved_referenced_names": [],
        "backup_id": "positions.backup.json",
    }
    assert "C:/secret" not in repr(response)


def test_library_transfer_accepts_public_strategy_and_passes_trusted_actor() -> None:
    adapter = MagicMock()
    adapter.import_payload.return_value = {
        "errors": [],
        "commands": {"imported": [], "skipped": []},
        "flows": {"imported": [], "skipped": []},
    }
    service = RobotLibraryTransferApplicationService(adapter)

    response = service.import_payload(
        _principal(actor="engineer-1", role="engineer"),
        {"schema_version": 1, "commands": [], "flows": []},
        strategy="overwrite-draft-only",
    )

    assert response.ok
    assert adapter.import_payload.call_args.kwargs == {
        "strategy": "overwrite-draft-only",
        "actor": "test:engineer-1",
    }
