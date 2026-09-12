"""The unique production composition root for the robot server process."""

from __future__ import annotations

import secrets
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from robot_platform import (
    ExecutionHistory,
    LibraryExecutionRegistry,
    PendingPlanStore,
    RobotPlatform,
    SessionGateStore,
    configure_robot_runtime,
    ensure_audit_chain,
    get_robot_data_dir,
)
from robot_platform.adapters import (
    FileCommandLibraryManagementAdapter,
    FileFlowManagementAdapter,
    FileRobotKnowledgeAdapter,
    FileLibraryTransferAdapter,
    FilePositionMaintenanceAdapter,
    FileRobotFlowAdapter,
    FileRobotPositionLibraryAdapter,
)
from robot_platform.application import (
    EmergencyStopApplicationService,
    InMemoryLibraryConfirmationStore,
    RobotDiagnosticsApplicationService,
    RobotDryRunApplicationService,
    RobotFlowApplicationService,
    RobotFlowExecutionApplicationService,
    RobotFlowManagementApplicationService,
    RobotIOApplicationService,
    RobotKnowledgeApplicationService,
    RobotLibraryApplicationService,
    RobotLibraryCatalogApplicationService,
    RobotLibraryExecutionApplicationService,
    RobotLibraryManagementApplicationService,
    RobotLibraryTransferApplicationService,
    RobotMotionApplicationService,
    RobotAutomaticMotionApplicationService,
    RobotAutomaticFlowApplicationService,
    RobotPositionApplicationService,
    RobotPositionMaintenanceApplicationService,
    RobotStatusApplicationService,
)
from robot_platform.application.confirmed_execution import ConfirmedPlanExecutionEngine
from robot_platform.backends.emergency_stop import ProductEmergencyStopAdapter
from robot_platform.backends.factory import RobotBackendConfig
from robot_platform.backends.product_wiring import create_product_backend_manager
from robot_platform.backends.wiring import run_composed_operator_command
from robot_platform.execution import ExecutionPermitStore, FlowApprovalStore
from robot_platform.tools.robot_tools import RobotToolFacade
from robot_platform.feature_policy import ProductFeaturePolicy
from robot_server.apps_api import LocalAppsService
from robot_server.audit_api import RobotAuditService
from robot_server.automations_api import LocalAutomationService
from robot_server.command_management import RobotCommandManagementService
from robot_server.container import RuntimeContainer
from robot_server.execution_recovery import ExecutionRecoveryService
from robot_server.emergency_stop_audit import EmergencyStopAuditOutbox
from robot_server.execution_api import RobotExecutionService
from robot_server.flow_management import RobotFlowManagementService
from robot_server.flow_event_audit import JsonlFlowEventSink
from robot_server.identity_api import RobotIdentityService
from robot_server.library_api import RobotLibraryService
from robot_server.library_transfer import RobotLibraryTransferService
from robot_server.media_api import LocalMediaService
from robot_server.position_maintenance import RobotPositionMaintenanceService
from robot_server.product_profile import ProductProfileService, load_product_profile
from robot_server.request_context import current_session_key
from robot_server.robot_api import RobotOperationService
from robot_server.runtime import create_agent_runtime
from robot_server.cron_policy import RobotIdentityCronMutationPolicy
from robot_platform.library.auth import get_user_session_store
from robot_server.settings_api import LocalSettingsService
from robot_server.tool_audit import JsonlToolAudit
from robot_server.tool_operation_store import JsonToolOperationStore
from robot_server.ui_state_api import LocalUiStateService

if TYPE_CHECKING:
    from robot_server.app import RobotServerConfig


def build_product_platform(data_dir: Path) -> tuple[RobotPlatform, list[str]]:
    """Build the Profile-selected Backend and its compatibility facade."""
    profile = load_product_profile(data_dir)
    backend_config = replace(
        RobotBackendConfig.from_env(),
        mode=profile["backend_mode"],
        allowed_io_output_channels=tuple(profile["allowed_io_output_channels"]),
    )
    backend = create_product_backend_manager(backend_config)
    feature_policy = ProductFeaturePolicy.from_enabled_tools(profile["enabled_tools"])
    try:
        platform = RobotPlatform(
            facade=RobotToolFacade(backend=backend, feature_policy=feature_policy),
            operator_runner=lambda **kwargs: run_composed_operator_command(
                manager=backend, **kwargs,
            ),
            backend_config=backend_config,
            allowed_io_output_channels=profile["allowed_io_output_channels"],
            feature_policy=feature_policy,
        )
    except BaseException:
        close = getattr(backend, "close", None)
        if callable(close):
            close()
        raise
    return platform, list(profile["enabled_tools"])


def build_simulation_platform(data_dir: Path) -> RobotPlatform:
    """Compose the controller-free graph used by generic server embedding/tests."""
    profile = load_product_profile(data_dir)
    backend_config = replace(
        RobotBackendConfig.from_env(),
        mode="simulation",
        allowed_io_output_channels=tuple(profile["allowed_io_output_channels"]),
    )
    backend = create_product_backend_manager(backend_config)
    feature_policy = ProductFeaturePolicy.from_enabled_tools(profile["enabled_tools"])
    return RobotPlatform(
        facade=RobotToolFacade(backend=backend, feature_policy=feature_policy),
        operator_runner=lambda **kwargs: run_composed_operator_command(
            manager=backend, **kwargs,
        ),
        backend_config=backend_config,
        allowed_io_output_channels=profile["allowed_io_output_channels"],
        feature_policy=feature_policy,
    )


def compose_product_runtime_container(
    config: RobotServerConfig,
) -> RuntimeContainer:
    """Compose the CLI/desktop product runtime, including its Agent adapter."""
    runtime_data_dir = config.robot_data_dir or get_robot_data_dir()
    ensure_audit_chain(runtime_data_dir / "audit.jsonl")
    configure_robot_runtime(data_dir=runtime_data_dir)
    platform, enabled_tools = build_product_platform(runtime_data_dir)
    status_service = RobotStatusApplicationService(platform)
    pending_plans = PendingPlanStore()
    session_gates = SessionGateStore()
    execution_context = platform.execution_context()
    controller_id = config.controller_id or str(
        execution_context.get("controller_id") or "unresolved-controller"
    )
    deployment_instance_id = config.deployment_instance_id or secrets.token_urlsafe(16)
    try:
        execution_permits = ExecutionPermitStore(
            storage_path=runtime_data_dir / "execution_permits.json"
        )
    except BaseException:
        platform.close()
        raise
    dry_run_service = RobotDryRunApplicationService(
        platform, pending_plans, session_gates,
        product_profile_version=config.product_profile_version,
        capability_version=config.capability_version,
        core_version=config.core_version,
        allowed_io_output_channels=platform.allowed_io_output_channels,
    )
    knowledge_service = RobotKnowledgeApplicationService(
        FileRobotKnowledgeAdapter(runtime_data_dir / "knowledge.json"),
    )
    position_library_adapter = FileRobotPositionLibraryAdapter(runtime_data_dir)
    position_service = RobotPositionApplicationService(position_library_adapter)
    library_mutation_service = RobotLibraryApplicationService(
        position_library_adapter, InMemoryLibraryConfirmationStore(),
    )
    library_catalog_service = RobotLibraryCatalogApplicationService(
        position_library_adapter,
    )
    library_management_service = RobotLibraryManagementApplicationService(
        FileCommandLibraryManagementAdapter(runtime_data_dir),
    )
    flow_service = RobotFlowApplicationService(
        FileRobotFlowAdapter(runtime_data_dir), dry_run_service,
    )
    automatic_motion_service = RobotAutomaticMotionApplicationService(
        dry_run_service,
        pending_plans,
        session_gates,
        execution_permits,
        RobotMotionApplicationService(engine=ConfirmedPlanExecutionEngine(
            platform,
            pending_plans,
            session_gates,
            execution_permits,
            robot_id=config.robot_id,
            controller_id=controller_id,
            product_profile_version=config.product_profile_version,
            capability_version=config.capability_version,
            deployment_instance_id=deployment_instance_id,
            core_version=config.core_version,
        )),
        robot_id=config.robot_id,
        controller_id=controller_id,
        product_profile_version=config.product_profile_version,
        capability_version=config.capability_version,
        deployment_instance_id=deployment_instance_id,
        core_version=config.core_version,
    )
    feature_policy = ProductFeaturePolicy.from_enabled_tools(enabled_tools)
    knowledge_service = feature_policy.protect("robot_knowledge", knowledge_service)
    position_service = feature_policy.protect("robot_position", position_service)
    library_mutation_service = feature_policy.protect(
        "robot_library", library_mutation_service,
    )
    flow_service = feature_policy.protect("robot_flow", flow_service)
    flow_execution_service = RobotFlowExecutionApplicationService(
        platform,
        pending_plans,
        session_gates,
        execution_permits,
        dry_run_service,
        flow_service,
        robot_id=config.robot_id,
        controller_id=controller_id,
        product_profile_version=config.product_profile_version,
        capability_version=config.capability_version,
        deployment_instance_id=deployment_instance_id,
        core_version=config.core_version,
        event_sink=JsonlFlowEventSink(runtime_data_dir / "flow_events.jsonl"),
        approval_store=FlowApprovalStore(),
    )
    automatic_flow_service = RobotAutomaticFlowApplicationService(
        flow_execution_service,
    )
    tool_operation_store = JsonToolOperationStore(
        runtime_data_dir / "tool_operations.json",
    )
    try:
        agent_runtime = create_agent_runtime(
            config.deployment_config_path,
            enabled_tools=enabled_tools,
            platform=platform,
            status_application=status_service,
            dry_run_application=dry_run_service,
            automatic_motion_application=automatic_motion_service,
            automatic_flow_application=automatic_flow_service,
            knowledge_application=knowledge_service,
            position_application=position_service,
            library_application=library_mutation_service,
            flow_application=flow_service,
            cron_mutation_policy=RobotIdentityCronMutationPolicy(
                get_user_session_store(),
            ),
            tool_audit=JsonlToolAudit(runtime_data_dir / "audit.jsonl"),
            tool_operation_store=tool_operation_store,
        )
        resolved_config = replace(
            config,
            robot_data_dir=runtime_data_dir,
            agent_runtime=agent_runtime,
            controller_id=controller_id,
            deployment_instance_id=deployment_instance_id,
        )
        container = compose_runtime_container(
            resolved_config,
            platform=platform,
            status_application=status_service,
            pending_plans=pending_plans,
            session_gates=session_gates,
            dry_run_application=dry_run_service,
            execution_permits=execution_permits,
            knowledge_application=knowledge_service,
            position_application=position_service,
            library_application=library_mutation_service,
            library_catalog_application=library_catalog_service,
            library_management_application=library_management_service,
            flow_application=flow_service,
            flow_execution_application=flow_execution_service,
            automatic_flow_application=automatic_flow_service,
            tool_operation_store=tool_operation_store,
        )
    except BaseException:
        execution_permits.close()
        platform.close()
        raise
    return replace(
        container,
        _cleanup_callbacks=(platform.close,) + container._cleanup_callbacks,
    )


def compose_runtime_container(
    config: RobotServerConfig,
    *,
    platform: RobotPlatform | None = None,
    status_application: RobotStatusApplicationService | None = None,
    pending_plans: PendingPlanStore | None = None,
    session_gates: SessionGateStore | None = None,
    dry_run_application: RobotDryRunApplicationService | None = None,
    execution_permits: ExecutionPermitStore | None = None,
    knowledge_application: RobotKnowledgeApplicationService | None = None,
    position_application: RobotPositionApplicationService | None = None,
    library_application: RobotLibraryApplicationService | None = None,
    library_catalog_application: RobotLibraryCatalogApplicationService | None = None,
    library_management_application: RobotLibraryManagementApplicationService | None = None,
    flow_application: RobotFlowApplicationService | None = None,
    flow_execution_application: RobotFlowExecutionApplicationService | None = None,
    automatic_flow_application: RobotAutomaticFlowApplicationService | None = None,
    tool_operation_store: JsonToolOperationStore | None = None,
) -> RuntimeContainer:
    """Build the single shared production object graph exactly once."""
    runtime_data_dir = config.robot_data_dir or get_robot_data_dir()
    ensure_audit_chain(runtime_data_dir / "audit.jsonl")
    configure_robot_runtime(
        data_dir=runtime_data_dir,
        session_key_provider=current_session_key,
    )
    runtime_tool_operation_store = tool_operation_store or JsonToolOperationStore(
        runtime_data_dir / "tool_operations.json",
    )
    owns_platform = platform is None
    if platform is None:
        robot_platform = build_simulation_platform(runtime_data_dir)
    else:
        robot_platform = platform
    candidate_policy = getattr(robot_platform, "feature_policy", None)
    feature_policy = (
        candidate_policy if isinstance(candidate_policy, ProductFeaturePolicy)
        else ProductFeaturePolicy.from_enabled_tools(
            load_product_profile(runtime_data_dir)["enabled_tools"],
        )
    )
    io_channels_candidate = getattr(
        robot_platform, "allowed_io_output_channels", (),
    )
    trusted_io_channels = (
        io_channels_candidate
        if isinstance(io_channels_candidate, (tuple, list, set, frozenset))
        else ()
    )
    status_service = status_application or RobotStatusApplicationService(robot_platform)
    diagnostics_service = RobotDiagnosticsApplicationService(status_service)
    execution_context = (
        robot_platform.execution_context()
        if callable(getattr(robot_platform, "execution_context", None))
        else {}
    )
    emergency_stop_service: EmergencyStopApplicationService | None = None
    try:
        execution_permits = execution_permits or ExecutionPermitStore(
            storage_path=runtime_data_dir / "execution_permits.json"
        )
        runtime_pending_plans = pending_plans or PendingPlanStore()
        runtime_session_gates = session_gates or SessionGateStore()
        knowledge_service = knowledge_application or RobotKnowledgeApplicationService(
            FileRobotKnowledgeAdapter(runtime_data_dir / "knowledge.json"),
        )
        dry_run_service = dry_run_application or RobotDryRunApplicationService(
            robot_platform, runtime_pending_plans, runtime_session_gates,
            product_profile_version=config.product_profile_version,
            capability_version=config.capability_version,
            core_version=config.core_version,
            allowed_io_output_channels=trusted_io_channels,
        )
        position_library_adapter = (
            FileRobotPositionLibraryAdapter(runtime_data_dir)
            if position_application is None
            or library_application is None
            or library_catalog_application is None
            else None
        )
        if position_library_adapter is None:
            assert position_application is not None
            assert library_application is not None
            assert library_catalog_application is not None
        position_service = position_application or RobotPositionApplicationService(
            position_library_adapter,
        )
        library_mutation_service = (
            library_application or RobotLibraryApplicationService(
                position_library_adapter, InMemoryLibraryConfirmationStore(),
            )
        )
        library_catalog_service = (
            library_catalog_application or RobotLibraryCatalogApplicationService(
                position_library_adapter,
            )
        )
        library_management_service = (
            library_management_application
            or RobotLibraryManagementApplicationService(
                FileCommandLibraryManagementAdapter(runtime_data_dir),
            )
        )
        library_transfer_service = RobotLibraryTransferApplicationService(
            FileLibraryTransferAdapter(runtime_data_dir),
        )
        position_maintenance_service = RobotPositionMaintenanceApplicationService(
            FilePositionMaintenanceAdapter(runtime_data_dir),
        )
        flow_service = flow_application or RobotFlowApplicationService(
            FileRobotFlowAdapter(runtime_data_dir), dry_run_service,
        )
        flow_management_service = RobotFlowManagementApplicationService(
            FileFlowManagementAdapter(runtime_data_dir),
        )
        identity = RobotIdentityService(runtime_data_dir)
        emergency_stop_service = EmergencyStopApplicationService(
            ProductEmergencyStopAdapter(config=(
                robot_platform.backend_config
                if isinstance(robot_platform, RobotPlatform)
                else RobotBackendConfig.from_env()
            )),
            audit_outbox=EmergencyStopAuditOutbox(
                runtime_data_dir / "emergency_stop_outbox.jsonl"
            ),
        )
        controller_id = (
            config.controller_id
            or str(execution_context.get("controller_id") or "unresolved-controller")
        )
        deployment_instance_id = (
            config.deployment_instance_id or secrets.token_urlsafe(16)
        )
        confirmed_execution_engine = ConfirmedPlanExecutionEngine(
            robot_platform,
            runtime_pending_plans,
            runtime_session_gates,
            execution_permits,
            robot_id=config.robot_id,
            controller_id=controller_id,
            product_profile_version=config.product_profile_version,
            capability_version=config.capability_version,
            deployment_instance_id=deployment_instance_id,
            core_version=config.core_version,
        )
        motion_service = RobotMotionApplicationService(
            engine=confirmed_execution_engine,
        )
        io_service = RobotIOApplicationService(
            engine=confirmed_execution_engine,
            allowed_io_output_channels=trusted_io_channels,
        )
        flow_execution_service = flow_execution_application or RobotFlowExecutionApplicationService(
            robot_platform,
            runtime_pending_plans,
            runtime_session_gates,
            execution_permits,
            dry_run_service,
            flow_service,
            robot_id=config.robot_id,
            controller_id=controller_id,
            product_profile_version=config.product_profile_version,
            capability_version=config.capability_version,
            deployment_instance_id=deployment_instance_id,
            core_version=config.core_version,
            event_sink=JsonlFlowEventSink(runtime_data_dir / "flow_events.jsonl"),
            approval_store=FlowApprovalStore(),
        )
        automatic_flow_service = automatic_flow_application or RobotAutomaticFlowApplicationService(
            flow_execution_service,
        )
        library_execution_service = RobotLibraryExecutionApplicationService(
            config.execution_registry or LibraryExecutionRegistry(
                history=ExecutionHistory(
                    runtime_data_dir / "library_executions.json",
                ),
            ),
            library_catalog_service,
            flow_service,
            dry_run_service,
            automatic_flow=automatic_flow_service,
        )
        operation = RobotOperationService(
            platform=robot_platform,
            pending_plans=runtime_pending_plans,
            session_gates=runtime_session_gates,
            planning_application=dry_run_service,
            execution_permits=execution_permits,
            robot_id=config.robot_id,
            controller_id=controller_id,
            product_profile_version=config.product_profile_version,
            capability_version=config.capability_version,
            deployment_instance_id=deployment_instance_id,
            core_version=config.core_version,
            emergency_stop_application=emergency_stop_service,
            motion_application=motion_service,
            io_application=io_service,
            flow_execution_application=flow_execution_service,
            execution_recovery=ExecutionRecoveryService(
                platform=robot_platform,
                permits=execution_permits,
                tool_operation_store=runtime_tool_operation_store,
                audit_path=runtime_data_dir / "audit.jsonl",
            ),
        )
        return RuntimeContainer(
            config=config,
            runtime_data_dir=runtime_data_dir,
            platform=robot_platform,
            pending_plans=runtime_pending_plans,
            session_gates=runtime_session_gates,
            execution_permits=execution_permits,
            status_service=status_service,
            diagnostics_service=diagnostics_service,
            dry_run_service=dry_run_service,
            emergency_stop_service=emergency_stop_service,
            motion_service=motion_service,
            io_service=io_service,
            knowledge_service=knowledge_service,
            position_service=position_service,
            library_mutation_service=library_mutation_service,
            library_catalog_service=library_catalog_service,
            library_management_service=library_management_service,
            library_transfer_service=library_transfer_service,
            position_maintenance_service=position_maintenance_service,
            flow_service=flow_service,
            flow_execution_service=flow_execution_service,
            flow_management_service=flow_management_service,
            library_execution_service=library_execution_service,
            operation_service=operation,
            library_service=feature_policy.protect(
                "robot_library", RobotLibraryService(library_catalog_service),
            ),
            identity_service=identity,
            command_management=feature_policy.protect(
                "robot_library", RobotCommandManagementService(
                    identity, library_management_service,
                ),
            ),
            flow_management=feature_policy.protect(
                "robot_flow", RobotFlowManagementService(
                    identity, flow_management_service,
                ),
            ),
            audit_service=RobotAuditService(
                runtime_data_dir, identity,
                tool_operation_store=runtime_tool_operation_store,
                platform=robot_platform,
            ),
            library_transfer=feature_policy.protect(
                "robot_library", RobotLibraryTransferService(
                    identity, library_transfer_service,
                ),
            ),
            position_maintenance=feature_policy.protect(
                "robot_position", RobotPositionMaintenanceService(
                    identity, position_maintenance_service,
                ),
            ),
            execution_service=feature_policy.protect(
                "robot_library", RobotExecutionService(
                    identity, library_execution_service,
                ),
            ),
            product_profile=ProductProfileService(runtime_data_dir, identity),
            agent_runtime=config.agent_runtime,
            ui_state=LocalUiStateService(
                runtime_data_dir, identity, config.agent_runtime,
            ),
            settings=LocalSettingsService(),
            automations=feature_policy.protect(
                "cron", LocalAutomationService(config.agent_runtime),
            ),
            apps=LocalAppsService(),
            media=LocalMediaService(),
            feature_policy=feature_policy,
            _cleanup_callbacks=(
                *((robot_platform.close,) if owns_platform else ()),
                execution_permits.close,
                emergency_stop_service.close,
            ),
        )
    except BaseException:
        if emergency_stop_service is not None:
            try:
                emergency_stop_service.close()
            except BaseException:
                pass
        if execution_permits is not None:
            try:
                execution_permits.close()
            except BaseException:
                pass
        if owns_platform:
            try:
                robot_platform.close()
            except BaseException:
                pass
        raise
