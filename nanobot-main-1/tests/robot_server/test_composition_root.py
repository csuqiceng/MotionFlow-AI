"""Composition-root ownership and compatibility-shim tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

import robot_server.app as app_module
import robot_server.bootstrap as bootstrap_module
from robot_platform.application import (
    AuthenticatedPrincipal,
    RobotDiagnosticsResponse,
    RobotIOResponse,
    RobotMotionResponse,
    RobotStatusResponse,
)
from robot_server.app import (
    AGENT_RUNTIME_KEY,
    LOCAL_APPS_SERVICE_KEY,
    LOCAL_AUTOMATION_SERVICE_KEY,
    LOCAL_MEDIA_SERVICE_KEY,
    LOCAL_SETTINGS_SERVICE_KEY,
    LOCAL_UI_STATE_SERVICE_KEY,
    PRODUCT_PROFILE_SERVICE_KEY,
    ROBOT_AUDIT_SERVICE_KEY,
    ROBOT_COMMAND_MANAGEMENT_KEY,
    ROBOT_DIAGNOSTICS_SERVICE_KEY,
    ROBOT_EMERGENCY_STOP_SERVICE_KEY,
    ROBOT_EXECUTION_SERVICE_KEY,
    ROBOT_FLOW_MANAGEMENT_KEY,
    ROBOT_IDENTITY_SERVICE_KEY,
    ROBOT_LIBRARY_SERVICE_KEY,
    ROBOT_LIBRARY_TRANSFER_KEY,
    ROBOT_OPERATION_SERVICE_KEY,
    ROBOT_PLATFORM_KEY,
    ROBOT_POSITION_MAINTENANCE_KEY,
    ROBOT_STATUS_SERVICE_KEY,
    RobotServerConfig,
    create_robot_server_app,
)
from robot_server.bootstrap import (
    compose_product_runtime_container,
    compose_runtime_container,
)
from robot_server.container import RuntimeContainer

CONTAINER_TO_APP_KEY = {
    "platform": ROBOT_PLATFORM_KEY,
    "status_service": ROBOT_STATUS_SERVICE_KEY,
    "diagnostics_service": ROBOT_DIAGNOSTICS_SERVICE_KEY,
    "emergency_stop_service": ROBOT_EMERGENCY_STOP_SERVICE_KEY,
    "operation_service": ROBOT_OPERATION_SERVICE_KEY,
    "library_service": ROBOT_LIBRARY_SERVICE_KEY,
    "identity_service": ROBOT_IDENTITY_SERVICE_KEY,
    "command_management": ROBOT_COMMAND_MANAGEMENT_KEY,
    "flow_management": ROBOT_FLOW_MANAGEMENT_KEY,
    "audit_service": ROBOT_AUDIT_SERVICE_KEY,
    "library_transfer": ROBOT_LIBRARY_TRANSFER_KEY,
    "position_maintenance": ROBOT_POSITION_MAINTENANCE_KEY,
    "execution_service": ROBOT_EXECUTION_SERVICE_KEY,
    "product_profile": PRODUCT_PROFILE_SERVICE_KEY,
    "agent_runtime": AGENT_RUNTIME_KEY,
    "ui_state": LOCAL_UI_STATE_SERVICE_KEY,
    "settings": LOCAL_SETTINGS_SERVICE_KEY,
    "automations": LOCAL_AUTOMATION_SERVICE_KEY,
    "apps": LOCAL_APPS_SERVICE_KEY,
    "media": LOCAL_MEDIA_SERVICE_KEY,
}


def _container(tmp_path, *, agent_runtime=None, cleanup_callbacks=()) -> RuntimeContainer:
    dependencies = {name: MagicMock(name=name) for name in CONTAINER_TO_APP_KEY}
    dependencies["agent_runtime"] = agent_runtime
    return RuntimeContainer(
        config=RobotServerConfig(robot_data_dir=tmp_path),
        runtime_data_dir=tmp_path,
        pending_plans=MagicMock(name="pending-plans"),
        session_gates=MagicMock(name="session-gates"),
        execution_permits=MagicMock(name="execution-permits"),
        dry_run_service=MagicMock(name="dry-run-service"),
        motion_service=MagicMock(name="motion-service"),
        _cleanup_callbacks=tuple(cleanup_callbacks),
        **dependencies,
    )


def test_app_publishes_only_the_injected_container_dependencies(
    monkeypatch, tmp_path,
) -> None:
    container = _container(tmp_path)
    compose = MagicMock(side_effect=AssertionError("injected app must not compose"))
    monkeypatch.setattr(app_module, "compose_runtime_container", compose)

    app = create_robot_server_app(container=container)

    compose.assert_not_called()
    for attribute, key in CONTAINER_TO_APP_KEY.items():
        assert app[key] is getattr(container, attribute)


@pytest.mark.asyncio
async def test_http_status_uses_injected_application_service(tmp_path) -> None:
    container = _container(tmp_path)
    container.platform.get_status.side_effect = AssertionError(
        "HTTP bypassed Application"
    )
    container.status_service.query.return_value = RobotStatusResponse(
        payload={"ok": True, "data": {"mode": "simulation"}},
    )
    async with TestClient(TestServer(create_robot_server_app(container=container))) as client:
        response = await client.get("/api/robot/status")
        payload = await response.json()

    assert response.status == 200
    assert payload == {"ok": True, "data": {"mode": "simulation"}}
    container.status_service.query.assert_called_once_with()
    container.platform.get_status.assert_not_called()


@pytest.mark.asyncio
async def test_http_status_fails_closed_for_invalid_application_result(tmp_path) -> None:
    container = _container(tmp_path)
    container.status_service.query.return_value = SimpleNamespace(
        ok=False, payload=None, error=None,
    )
    async with TestClient(TestServer(create_robot_server_app(container=container))) as client:
        response = await client.get("/api/robot/status")
        payload = await response.json()

    assert response.status == 503
    assert payload == {"error": "robot status unavailable"}


@pytest.mark.asyncio
async def test_http_diagnostics_uses_injected_application_service(tmp_path) -> None:
    container = _container(tmp_path)
    principal = AuthenticatedPrincipal(
        actor_id="engineer-1", role="engineer", session_id="session-1",
        auth_source="test",
    )
    container.identity_service.require_principal.return_value = (principal, None)
    container.diagnostics_service.query.return_value = RobotDiagnosticsResponse(
        payload={"ok": True, "data": {"connection": {"mode": "idle"}}},
    )
    container.platform.get_status.side_effect = AssertionError(
        "diagnostics bypassed Application"
    )
    container.status_service.query.side_effect = AssertionError(
        "HTTP rebuilt diagnostics from status"
    )
    async with TestClient(TestServer(create_robot_server_app(container=container))) as client:
        response = await client.get("/api/management/diagnostics")
        payload = await response.json()

    assert response.status == 200
    assert payload["data"]["connection"]["mode"] == "idle"
    query = container.diagnostics_service.query.call_args.args[0]
    assert query.principal is principal
    container.platform.get_status.assert_not_called()
    container.status_service.query.assert_not_called()


def test_legacy_arguments_delegate_to_bootstrap_exactly_once(
    monkeypatch, tmp_path,
) -> None:
    container = _container(tmp_path)
    platform = MagicMock(name="legacy-platform")
    compose = MagicMock(return_value=container)
    monkeypatch.setattr(app_module, "compose_runtime_container", compose)

    create_robot_server_app(config=container.config, platform=platform)

    compose.assert_called_once_with(container.config, platform=platform)


def test_container_and_legacy_arguments_are_mutually_exclusive(tmp_path) -> None:
    container = _container(tmp_path)
    with pytest.raises(ValueError, match="cannot be combined"):
        create_robot_server_app(container=container, config=container.config)


def test_bootstrap_releases_permit_lock_when_later_construction_fails(
    monkeypatch, tmp_path,
) -> None:
    permit_store = MagicMock(name="permit-store")
    monkeypatch.setattr(
        bootstrap_module, "ExecutionPermitStore", MagicMock(return_value=permit_store),
    )
    monkeypatch.setattr(
        bootstrap_module, "RobotIdentityService",
        MagicMock(side_effect=RuntimeError("construction failed")),
    )

    with pytest.raises(RuntimeError, match="construction failed"):
        compose_runtime_container(
            RobotServerConfig(robot_data_dir=tmp_path), platform=MagicMock(),
        )

    permit_store.close.assert_called_once_with()


def test_product_composition_closes_owned_backend_when_agent_build_fails(
    monkeypatch, tmp_path,
) -> None:
    platform = MagicMock(name="owned-platform")
    monkeypatch.setattr(
        bootstrap_module, "build_product_platform",
        MagicMock(return_value=(platform, ["robot_arm"])),
    )
    monkeypatch.setattr(
        bootstrap_module, "create_agent_runtime",
        MagicMock(side_effect=RuntimeError("agent build failed")),
    )

    with pytest.raises(RuntimeError, match="agent build failed"):
        compose_product_runtime_container(RobotServerConfig(robot_data_dir=tmp_path))

    platform.close.assert_called_once_with()


def test_product_container_owns_platform_cleanup(monkeypatch, tmp_path) -> None:
    platform = MagicMock(name="owned-platform")
    base = _container(tmp_path)
    monkeypatch.setattr(
        bootstrap_module, "build_product_platform",
        MagicMock(return_value=(platform, ["robot_arm"])),
    )
    create_agent = MagicMock(return_value=MagicMock())
    monkeypatch.setattr(
        bootstrap_module, "create_agent_runtime", create_agent,
    )
    compose_runtime = MagicMock(return_value=base)
    monkeypatch.setattr(
        bootstrap_module, "compose_runtime_container", compose_runtime,
    )

    container = compose_product_runtime_container(
        RobotServerConfig(robot_data_dir=tmp_path),
    )
    container.close()

    assert (
        create_agent.call_args.kwargs["status_application"]
        is compose_runtime.call_args.kwargs["status_application"]
    )
    assert (
        create_agent.call_args.kwargs["dry_run_application"]
        is compose_runtime.call_args.kwargs["dry_run_application"]
    )
    assert (
        create_agent.call_args.kwargs["position_application"]
        is compose_runtime.call_args.kwargs["position_application"]
    )
    assert (
        create_agent.call_args.kwargs["library_application"]
        is compose_runtime.call_args.kwargs["library_application"]
    )
    platform.close.assert_called_once_with()


def test_each_runtime_container_owns_isolated_plan_and_session_stores(tmp_path) -> None:
    first_platform = MagicMock(name="first-external-platform")
    second_platform = MagicMock(name="second-external-platform")
    first = compose_runtime_container(
        RobotServerConfig(robot_data_dir=tmp_path / "first"), platform=first_platform,
    )
    second = compose_runtime_container(
        RobotServerConfig(robot_data_dir=tmp_path / "second"), platform=second_platform,
    )
    try:
        assert first.pending_plans is not second.pending_plans
        assert first.session_gates is not second.session_gates
        assert first.execution_permits is not second.execution_permits
        assert first.operation_service.planning_application is first.dry_run_service
        assert second.operation_service.planning_application is second.dry_run_service
        assert (
            first.operation_service.emergency_stop_application
            is first.emergency_stop_service
        )
        assert (
            second.operation_service.emergency_stop_application
            is second.emergency_stop_service
        )
        assert first.emergency_stop_service is not second.emergency_stop_service
        assert first.operation_service.motion_application is first.motion_service
        assert second.operation_service.motion_application is second.motion_service
        assert first.motion_service is not second.motion_service
        assert first.operation_service.io_application is first.io_service
        assert second.operation_service.io_application is second.io_service
        assert first.io_service is not second.io_service
        assert first.motion_service._engine is first.io_service._engine
        assert second.motion_service._engine is second.io_service._engine
        assert first.motion_service._engine is not second.motion_service._engine
        assert first.position_service is not second.position_service
        assert first.library_mutation_service is not second.library_mutation_service
        assert first.library_catalog_service is not second.library_catalog_service
        assert first.library_management_service is not second.library_management_service
        assert first.library_transfer_service is not second.library_transfer_service
        assert first.position_maintenance_service is not second.position_maintenance_service
        assert first.library_service._application is first.library_catalog_service
        assert second.library_service._application is second.library_catalog_service
        assert first.command_management._application is first.library_management_service
        assert first.library_transfer._application is first.library_transfer_service
        assert first.position_maintenance._application is first.position_maintenance_service
        plan = first.pending_plans.create(
            command="delay", parameters={"seconds": 0.1}, dry_run_result={"ok": True},
        )
        first.session_gates.set_pending_plan("session", plan.plan_id)
        assert second.pending_plans.get(plan.plan_id) is None
        assert second.session_gates.get("session").pending_plan_id is None
    finally:
        first.close()
        second.close()
    first_platform.close.assert_not_called()
    second_platform.close.assert_not_called()


def test_motion_execute_routes_only_through_injected_application(tmp_path) -> None:
    platform = MagicMock(name="compatibility-platform")
    container = compose_runtime_container(
        RobotServerConfig(robot_data_dir=tmp_path), platform=platform,
    )
    motion = MagicMock()
    motion.execute.return_value = RobotMotionResponse(
        payload={"ok": True, "state": "motion-complete"},
    )
    container.operation_service.motion_application = motion
    plan = container.pending_plans.create(
        command="linear_move", parameters={"target_pose": {"x": 1}},
        dry_run_result={"ok": True},
    )
    principal = AuthenticatedPrincipal("operator", "operator", "session", "test")
    try:
        status, result = container.operation_service.execute(
            plan.plan_id, {"confirm_code": "server-receipt"}, principal=principal,
        )
    finally:
        container.close()

    assert status == 200
    assert result["ok"] is True
    motion.execute.assert_called_once()
    platform.execute_confirmed_plan.assert_not_called()


def test_io_execute_routes_only_through_injected_application(tmp_path) -> None:
    platform = MagicMock(name="compatibility-platform")
    container = compose_runtime_container(
        RobotServerConfig(robot_data_dir=tmp_path), platform=platform,
    )
    io_application = MagicMock()
    io_application.execute.return_value = RobotIOResponse(
        payload={"ok": True, "state": "io_complete"},
    )
    container.operation_service.io_application = io_application
    plan = container.pending_plans.create(
        command="io",
        parameters={
            "io_number": 7, "enabled": True, "allowed_io_channels": [7],
        },
        dry_run_result={"ok": True},
    )
    principal = AuthenticatedPrincipal("operator", "operator", "session", "test")
    try:
        status, result = container.operation_service.execute(
            plan.plan_id,
            {
                "confirm_code": "server-receipt",
                "io_number": 999,
                "enabled": False,
            },
            principal=principal,
        )
    finally:
        container.close()

    assert status == 200
    assert result["ok"] is True
    request = io_application.execute.call_args.args[0]
    assert request.plan_id == plan.plan_id
    assert request.confirmation_receipt == "server-receipt"
    assert not hasattr(request, "io_number")
    platform.execute_confirmed_plan.assert_not_called()


def test_http_planning_cannot_self_authorize_io_channel(tmp_path) -> None:
    platform = MagicMock(name="trusted-io-platform")
    platform.allowed_io_output_channels = (3, 8)
    platform.execution_context.return_value = {"controller_id": "controller"}
    platform.plan_motion.return_value = {"ok": True, "state": "planned"}
    container = compose_runtime_container(
        RobotServerConfig(robot_data_dir=tmp_path), platform=platform,
    )
    principal = AuthenticatedPrincipal("operator", "operator", "session", "test")
    try:
        denied_status, denied = container.operation_service.plan(
            {
                "command": "io",
                "parameters": {
                    "io_number": 999,
                    "enabled": True,
                    "allowed_io_channels": [999],
                },
            },
            principal=principal,
        )
        accepted_status, accepted = container.operation_service.plan(
            {
                "command": "io",
                "parameters": {"io_number": 3, "enabled": True},
            },
            principal=principal,
        )
    finally:
        container.close()

    assert denied_status == 400
    assert "server-owned" in denied["error"]["message"]
    assert accepted_status == 201
    stored = container.pending_plans.get(accepted["plan_id"])
    assert stored.parameters == {
        "io_number": 3,
        "enabled": True,
        "allowed_io_channels": [3, 8],
    }
    platform.plan_motion.assert_called_once_with("io", stored.parameters)


def test_compatibility_composition_owns_its_internally_created_platform(
    monkeypatch, tmp_path,
) -> None:
    close = MagicMock(name="internal-platform-close")
    monkeypatch.setattr(bootstrap_module.RobotPlatform, "close", close)

    container = compose_runtime_container(RobotServerConfig(robot_data_dir=tmp_path))
    container.close()

    close.assert_called_once_with()


def test_internal_platform_is_closed_when_later_runtime_construction_fails(
    monkeypatch, tmp_path,
) -> None:
    close = MagicMock(name="internal-platform-close")
    monkeypatch.setattr(bootstrap_module.RobotPlatform, "close", close)
    monkeypatch.setattr(
        bootstrap_module, "RobotIdentityService",
        MagicMock(side_effect=RuntimeError("service build failed")),
    )

    with pytest.raises(RuntimeError, match="service build failed"):
        compose_runtime_container(RobotServerConfig(robot_data_dir=tmp_path))

    close.assert_called_once_with()


def test_container_cleanup_is_reverse_order_and_best_effort(tmp_path) -> None:
    events: list[str] = []

    def succeeds() -> None:
        events.append("success")

    def fails() -> None:
        events.append("failure")
        raise RuntimeError("cleanup failed")

    container = _container(tmp_path, cleanup_callbacks=(succeeds, fails))
    with pytest.raises(RuntimeError, match="cleanup failed"):
        container.close()

    assert events == ["failure", "success"]


@pytest.mark.asyncio
async def test_agent_stops_before_container_resources_are_closed(tmp_path) -> None:
    events: list[str] = []

    class Agent:
        async def start(self) -> None:
            events.append("agent-start")

        async def stop(self) -> None:
            events.append("agent-stop")

    container = _container(
        tmp_path,
        agent_runtime=Agent(),
        cleanup_callbacks=(lambda: events.append("container-close"),),
    )
    async with TestClient(TestServer(create_robot_server_app(container=container))):
        assert events == ["agent-start"]

    assert events == ["agent-start", "agent-stop", "container-close"]


@pytest.mark.asyncio
async def test_agent_stop_failure_still_closes_container_resources(tmp_path) -> None:
    events: list[str] = []

    class FailingAgent:
        async def start(self) -> None:
            events.append("agent-start")

        async def stop(self) -> None:
            events.append("agent-stop")
            raise RuntimeError("agent stop failed")

    container = _container(
        tmp_path,
        agent_runtime=FailingAgent(),
        cleanup_callbacks=(lambda: events.append("container-close"),),
    )
    with pytest.raises(RuntimeError, match="agent stop failed"):
        async with TestClient(TestServer(create_robot_server_app(container=container))):
            pass

    assert events == ["agent-start", "agent-stop", "container-close"]


@pytest.mark.asyncio
async def test_agent_start_failure_closes_container_resources(tmp_path) -> None:
    events: list[str] = []

    class FailingStartAgent:
        async def start(self) -> None:
            events.append("agent-start")
            raise RuntimeError("agent start failed")

        async def stop(self) -> None:
            events.append("agent-stop")

    container = _container(
        tmp_path,
        agent_runtime=FailingStartAgent(),
        cleanup_callbacks=(lambda: events.append("container-close"),),
    )
    client = TestClient(TestServer(create_robot_server_app(container=container)))
    try:
        with pytest.raises(RuntimeError, match="agent start failed"):
            await client.start_server()
    finally:
        await client.close()

    assert events == ["agent-start", "container-close"]
