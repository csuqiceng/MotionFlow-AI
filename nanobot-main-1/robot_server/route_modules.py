"""Feature-owned HTTP route catalogs for the aiohttp interface adapter."""

from __future__ import annotations

from aiohttp import web

RouteSpec = tuple[str, str, str]

WEBUI_ROUTES: tuple[RouteSpec, ...] = (
    ("GET", "/health", "_health"), ("GET", "/api/bootstrap", "_bootstrap"),
    ("GET", "/webui/bootstrap", "_webui_bootstrap"), ("GET", "/webui", "_webui_socket"),
    ("GET", "/api/auth/login", "_webui_login"), ("GET", "/api/auth/logout", "_webui_logout"),
    ("GET", "/api/login/preflight", "_webui_login_preflight"),
    ("GET", "/api/media/{signature}/{payload}", "_media"),
    ("GET", "/api/sessions", "_ui_sessions"),
    ("GET", "/api/sessions/{key}/webui-thread", "_ui_session_thread"),
    ("GET", "/api/sessions/{key}/file-preview", "_ui_file_preview"),
    ("POST", "/api/sessions/{key}/delete", "_ui_delete_session"),
    ("GET", "/api/webui/sidebar-state", "_ui_sidebar_state"),
    ("POST", "/api/webui/sidebar-state", "_ui_update_sidebar_state"),
    ("GET", "/api/webui/sidebar-state/update", "_ui_update_sidebar_state"),
    ("GET", "/api/webui/skills", "_ui_skills"),
    ("GET", "/api/webui/skills/{name}", "_ui_skill_detail"),
    ("GET", "/api/workspaces", "_ui_workspaces"), ("GET", "/api/commands", "_ui_commands"),
    ("GET", "/api/sessions/{key}/automations", "_session_automations"),
    ("GET", "/api/webui/automations", "_automations"),
    ("GET", "/api/webui/automations/enable", "_automation_enable"),
    ("GET", "/api/webui/automations/disable", "_automation_disable"),
    ("GET", "/api/webui/automations/delete", "_automation_delete"),
    ("GET", "/api/webui/automations/run", "_automation_run"),
    ("GET", "/api/webui/automations/update", "_automation_update"),
    ("GET", "/api/settings", "_settings"), ("GET", "/api/settings/usage", "_settings_usage"),
    ("GET", "/api/settings/version-check", "_settings_version_check"),
    ("GET", "/api/settings/web-search/update", "_settings_web_search_update"),
    ("GET", "/api/settings/network-safety/update", "_settings_network_safety_update"),
    ("GET", "/api/settings/image-generation/update", "_settings_image_generation_update"),
    ("GET", "/api/settings/transcription/update", "_settings_transcription_update"),
    ("GET", "/api/settings/cli-apps", "_cli_apps"),
    ("GET", "/api/settings/cli-apps/install", "_cli_apps_install"),
    ("GET", "/api/settings/cli-apps/update", "_cli_apps_update"),
    ("GET", "/api/settings/cli-apps/uninstall", "_cli_apps_uninstall"),
    ("GET", "/api/settings/cli-apps/test", "_cli_apps_test"),
    ("GET", "/api/settings/mcp-presets", "_mcp_presets"),
    ("GET", "/api/settings/mcp-presets/enable", "_mcp_enable"),
    ("GET", "/api/settings/mcp-presets/remove", "_mcp_remove"),
    ("GET", "/api/settings/mcp-presets/test", "_mcp_test"),
    ("GET", "/api/settings/mcp-presets/custom", "_mcp_custom"),
    ("GET", "/api/settings/mcp-presets/import", "_mcp_import"),
    ("GET", "/api/settings/mcp-presets/tools", "_mcp_tools"),
)

PRODUCT_ROUTES: tuple[RouteSpec, ...] = (
    ("GET", "/api/robot/status", "_robot_status"),
    ("POST", "/api/robot/plans", "_robot_plan"),
    ("POST", "/api/robot/plans/{plan_id}/confirm", "_robot_confirm"),
    ("POST", "/api/robot/plans/{plan_id}/execute", "_robot_execute"),
    ("POST", "/api/robot/flow-pending-plan", "_robot_flow_plan"),
    ("POST", "/api/robot/flow-confirm", "_robot_flow_confirm"),
    ("POST", "/api/robot/flow-execute", "_robot_flow_execute"),
    ("POST", "/api/robot/emergency-stop", "_robot_emergency_stop"),
    ("POST", "/api/robot/flows/run", "_robot_run_flow"),
    ("POST", "/api/identity/login", "_identity_login"),
    ("POST", "/api/identity/logout", "_identity_logout"),
    ("GET", "/api/identity/me", "_identity_me"),
    ("GET", "/api/identity/users", "_identity_users"),
    ("POST", "/api/identity/users", "_identity_create_user"),
    ("PATCH", "/api/identity/users/{user_id}", "_identity_update_user"),
    ("DELETE", "/api/identity/users/{user_id}", "_identity_delete_user"),
    ("POST", "/api/identity/users/{user_id}/password", "_identity_reset_password"),
    ("POST", "/api/identity/me/password", "_identity_change_own_password"),
    ("GET", "/ws/agent", "_agent_websocket"),
)

MANAGEMENT_ROUTES: tuple[RouteSpec, ...] = (
    ("GET", "/api/management/commands", "_management_commands"),
    ("POST", "/api/management/commands", "_management_create_command"),
    ("GET", "/api/management/commands/{command_id}", "_management_command"),
    ("PUT", "/api/management/commands/{command_id}", "_management_save_command"),
    ("DELETE", "/api/management/commands/{command_id}", "_management_delete_command"),
    ("PUT", "/api/management/commands/{command_id}/draft", "_management_update_draft"),
    ("POST", "/api/management/commands/{command_id}/draft", "_management_start_draft"),
    ("POST", "/api/management/commands/{command_id}/publish", "_management_publish"),
    ("POST", "/api/management/commands/{command_id}/archive", "_management_archive"),
    ("POST", "/api/management/commands/{command_id}/duplicate", "_management_duplicate_command"),
    ("POST", "/api/management/commands/bulk-archive", "_management_bulk_archive_commands"),
    ("GET", "/api/management/flows", "_management_flows"),
    ("POST", "/api/management/flows", "_management_create_flow"),
    ("GET", "/api/management/flows/{flow_id}", "_management_flow"),
    ("PUT", "/api/management/flows/{flow_id}", "_management_save_flow"),
    ("DELETE", "/api/management/flows/{flow_id}", "_management_delete_flow"),
    ("PUT", "/api/management/flows/{flow_id}/draft", "_management_update_flow_draft"),
    ("POST", "/api/management/flows/{flow_id}/draft", "_management_start_flow_draft"),
    ("POST", "/api/management/flows/{flow_id}/validate", "_management_validate_flow"),
    ("POST", "/api/management/flows/{flow_id}/publish", "_management_publish_flow"),
    ("POST", "/api/management/flows/{flow_id}/archive", "_management_archive_flow"),
    ("POST", "/api/management/flows/{flow_id}/duplicate", "_management_duplicate_flow"),
    ("POST", "/api/management/flows/bulk-archive", "_management_bulk_archive_flows"),
    ("GET", "/api/management/product-profile", "_management_product_profile"),
    ("PUT", "/api/management/product-profile", "_management_update_product_profile"),
    ("GET", "/api/management/diagnostics", "_management_diagnostics"),
    ("GET", "/api/management/audit", "_management_audit"),
    ("GET", "/api/management/tool-operations/unresolved", "_management_unresolved_tool_operations"),
    ("POST", "/api/management/tool-operations/reconcile", "_management_reconcile_tool_operation"),
    ("GET", "/api/management/library/export", "_management_export_library"),
    ("POST", "/api/management/library/import", "_management_import_library"),
    ("GET", "/api/management/positions/cleanup-preview", "_management_position_cleanup_preview"),
    ("POST", "/api/management/positions/cleanup", "_management_position_cleanup_apply"),
    ("POST", "/api/library/commands/{command_id}/executions", "_library_start_command_execution"),
    ("POST", "/api/library/flows/{flow_id}/executions", "_library_start_flow_execution"),
    ("GET", "/api/library/executions", "_library_list_executions"),
    ("GET", "/api/library/executions/{execution_id}", "_library_execution"),
    ("POST", "/api/library/executions/{execution_id}/control", "_library_control_execution"),
    ("GET", "/api/library/components", "_library_components"),
    ("GET", "/api/library/components/{component_id}", "_library_component"),
    ("GET", "/api/library/commands", "_library_commands"),
    ("GET", "/api/library/commands/{command_id}", "_library_command"),
    ("GET", "/api/library/flows", "_library_flows"),
    ("GET", "/api/library/flows/{flow_id}", "_library_flow"),
)


def register_feature_routes(app: web.Application) -> None:
    # Imported lazily so the composition module can finish defining its AppKeys
    # before feature adapters bind to those injected services.
    from robot_server.management_command_routes import HANDLERS as command_handlers
    from robot_server.management_flow_routes import HANDLERS as flow_handlers
    from robot_server.management_library_routes import HANDLERS as library_handlers
    from robot_server.product_identity_routes import HANDLERS as identity_handlers
    from robot_server.product_robot_routes import HANDLERS as robot_handlers
    from robot_server.webui_core_routes import HANDLERS as webui_handlers
    from robot_server.webui_settings_routes import HANDLERS as settings_handlers

    handlers = {
        **webui_handlers,
        **settings_handlers,
        **robot_handlers,
        **identity_handlers,
        **command_handlers,
        **flow_handlers,
        **library_handlers,
    }
    methods = {
        "GET": app.router.add_get,
        "POST": app.router.add_post,
        "PUT": app.router.add_put,
        "PATCH": app.router.add_patch,
        "DELETE": app.router.add_delete,
    }
    for method, path, handler_name in (*WEBUI_ROUTES, *PRODUCT_ROUTES, *MANAGEMENT_ROUTES):
        handler = handlers.get(handler_name)
        if not callable(handler):
            raise RuntimeError(f"Route handler is unavailable: {handler_name}")
        methods[method](path, handler)
