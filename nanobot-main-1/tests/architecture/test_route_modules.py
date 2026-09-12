from __future__ import annotations

from pathlib import Path

from robot_server.route_modules import (
    MANAGEMENT_ROUTES,
    PRODUCT_ROUTES,
    WEBUI_ROUTES,
)
from robot_server.management_command_routes import HANDLERS as COMMAND_HANDLERS
from robot_server.management_flow_routes import HANDLERS as FLOW_HANDLERS
from robot_server.management_library_routes import HANDLERS as LIBRARY_HANDLERS
from robot_server.product_identity_routes import HANDLERS as IDENTITY_HANDLERS
from robot_server.product_robot_routes import HANDLERS as ROBOT_HANDLERS
from robot_server.webui_core_routes import HANDLERS as WEBUI_HANDLERS
from robot_server.webui_settings_routes import HANDLERS as SETTINGS_HANDLERS

ROOT = Path(__file__).resolve().parents[2]


def test_feature_route_catalog_is_unique_and_all_handlers_exist() -> None:
    specs = (*WEBUI_ROUTES, *PRODUCT_ROUTES, *MANAGEMENT_ROUTES)
    keys = [(method, path) for method, path, _handler in specs]
    assert len(keys) == len(set(keys))

    handlers = {
        **WEBUI_HANDLERS, **SETTINGS_HANDLERS, **ROBOT_HANDLERS,
        **IDENTITY_HANDLERS, **COMMAND_HANDLERS, **FLOW_HANDLERS,
        **LIBRARY_HANDLERS,
    }
    assert not [handler for _method, _path, handler in specs if handler not in handlers]


def test_app_registers_feature_catalog_instead_of_individual_api_routes() -> None:
    source = (ROOT / "robot_server" / "app.py").read_text(encoding="utf-8")
    assert "register_feature_routes(app)" in source
    assert 'app.router.add_get("/api/' not in source
    assert 'app.router.add_post("/api/' not in source
