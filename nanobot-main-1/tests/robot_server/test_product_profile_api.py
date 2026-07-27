"""Engineer-only robot and Tool profile; never an AI configuration surface."""

from __future__ import annotations

import importlib.util

from robot_platform import UserRegistry, hash_password, initialize_user_identity
from robot_server.identity_api import RobotIdentityService
from robot_server.product_profile import ProductProfileService


def test_product_profile_module_exists() -> None:
    assert importlib.util.find_spec("robot_server.product_profile") is not None


def _engineer_token(data_dir) -> tuple[RobotIdentityService, str]:
    initialize_user_identity(users_path=data_dir / "users.json", audit_path=data_dir / "audit.jsonl")
    registry = UserRegistry(data_dir / "users.json", audit_path=data_dir / "audit.jsonl")
    admin = registry.get_by_username("admin")
    assert admin is not None
    registry.bootstrap_set_password(admin["user_id"], hash_password("test-password", iterations=100_000))
    identity = RobotIdentityService(data_dir)
    status, payload = identity.login(
        {"username": "admin", "password": "test-password", "role": "engineer"},
        client_key="test",
    )
    assert status == 200
    return identity, payload["data"]["user_token"]


def test_product_profile_is_engineer_only_and_contains_no_ai_configuration(tmp_path) -> None:
    identity, engineer_token = _engineer_token(tmp_path)
    service = ProductProfileService(tmp_path, identity)

    status, payload = service.get("not-a-session")
    assert status == 401
    assert payload["error"]["code"] == "unauthorized"

    status, payload = service.get(engineer_token)
    assert status == 200
    profile = payload["data"]
    assert profile["backend_mode"] == "zmotion_readonly"
    assert set(profile) == {
        "protocol_version",
        "backend_mode",
        "available_backend_modes",
        "capabilities",
        "tools",
    }
    assert "provider" not in str(profile).lower()
    assert "model" not in str(profile).lower()


def test_engineer_can_persist_enabled_tools_but_cannot_select_unknown_tool(tmp_path) -> None:
    identity, engineer_token = _engineer_token(tmp_path)
    service = ProductProfileService(tmp_path, identity)

    status, payload = service.update(
        engineer_token,
        {"backend_mode": "simulation", "enabled_tools": ["robot_knowledge"]},
    )
    assert status == 200
    assert {item["tool_id"] for item in payload["data"]["tools"] if item["enabled"]} == {"robot_knowledge"}
    assert (tmp_path / "product_profile.json").is_file()

    status, payload = service.update(
        engineer_token,
        {"backend_mode": "simulation", "enabled_tools": ["not-a-tool"]},
    )
    assert status == 400
    assert payload["error"]["code"] == "invalid_profile"
