"""Stable dependency-injection keys shared by server feature adapters."""

from __future__ import annotations

from typing import Any

from aiohttp import web

ROBOT_PLATFORM_KEY: web.AppKey[Any] = web.AppKey("robot_platform", object)
ROBOT_STATUS_SERVICE_KEY: web.AppKey[Any] = web.AppKey("robot_status_service", object)
ROBOT_DIAGNOSTICS_SERVICE_KEY: web.AppKey[Any] = web.AppKey("robot_diagnostics_service", object)
ROBOT_EMERGENCY_STOP_SERVICE_KEY: web.AppKey[Any] = web.AppKey("robot_emergency_stop_service", object)
ROBOT_SERVER_CONFIG_KEY: web.AppKey[Any] = web.AppKey("robot_server_config", object)
ROBOT_OPERATION_SERVICE_KEY: web.AppKey[Any] = web.AppKey("robot_operation_service", object)
ROBOT_LIBRARY_SERVICE_KEY: web.AppKey[Any] = web.AppKey("robot_library_service", object)
ROBOT_IDENTITY_SERVICE_KEY: web.AppKey[Any] = web.AppKey("robot_identity_service", object)
ROBOT_COMMAND_MANAGEMENT_KEY: web.AppKey[Any] = web.AppKey("robot_command_management", object)
ROBOT_FLOW_MANAGEMENT_KEY: web.AppKey[Any] = web.AppKey("robot_flow_management", object)
ROBOT_AUDIT_SERVICE_KEY: web.AppKey[Any] = web.AppKey("robot_audit_service", object)
ROBOT_LIBRARY_TRANSFER_KEY: web.AppKey[Any] = web.AppKey("robot_library_transfer", object)
ROBOT_POSITION_MAINTENANCE_KEY: web.AppKey[Any] = web.AppKey("robot_position_maintenance", object)
ROBOT_EXECUTION_SERVICE_KEY: web.AppKey[Any] = web.AppKey("robot_execution_service", object)
PRODUCT_PROFILE_SERVICE_KEY: web.AppKey[Any] = web.AppKey("product_profile_service", object)
LOCAL_UI_STATE_SERVICE_KEY: web.AppKey[Any] = web.AppKey("local_ui_state_service", object)
LOCAL_SETTINGS_SERVICE_KEY: web.AppKey[Any] = web.AppKey("local_settings_service", object)
LOCAL_AUTOMATION_SERVICE_KEY: web.AppKey[Any] = web.AppKey("local_automation_service", object)
LOCAL_APPS_SERVICE_KEY: web.AppKey[Any] = web.AppKey("local_apps_service", object)
LOCAL_MEDIA_SERVICE_KEY: web.AppKey[Any] = web.AppKey("local_media_service", object)
AGENT_RUNTIME_KEY: web.AppKey[Any] = web.AppKey("agent_runtime", object)
PRODUCT_FEATURE_POLICY_KEY: web.AppKey[Any] = web.AppKey("product_feature_policy", object)
