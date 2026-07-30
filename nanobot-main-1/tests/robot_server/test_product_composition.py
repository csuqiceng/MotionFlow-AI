from __future__ import annotations

from unittest.mock import MagicMock, patch

from robot_platform.backends.factory import RobotBackendConfig
from robot_platform.backends.product_wiring import create_product_robot_backend
from robot_server.product_profile import _BACKEND_CAPABILITIES


def test_product_composition_migrates_saved_profile_to_real_backend_and_all_tools(tmp_path) -> None:
    from robot_server.bootstrap import build_product_platform

    (tmp_path / "product_profile.json").write_text(
        '{"backend_mode":"simulation","enabled_tools":["robot_knowledge"],'
        '"allowed_io_output_channels":[8,3]}',
        encoding="utf-8",
    )
    backend = MagicMock()

    with patch(
        "robot_server.bootstrap.create_product_backend_manager",
        return_value=backend,
    ) as create_backend:
        platform, enabled_tools = build_product_platform(tmp_path)

    assert create_backend.call_args.args[0].mode == "zmotion_readonly"
    assert platform._backend_config.mode == "zmotion_readonly"
    assert enabled_tools == [
        "robot_arm", "robot_flow", "robot_knowledge", "robot_position",
        "robot_library", "cron",
    ]
    assert platform.allowed_io_output_channels == (3, 8)
    assert platform.backend_config.allowed_io_output_channels == (3, 8)
    migrated = (tmp_path / "product_profile.json").read_text(encoding="utf-8")
    assert '"backend_mode": "zmotion_readonly"' in migrated
    assert '"robot_library"' in migrated


def test_profile_capability_catalog_matches_backend_contracts() -> None:
    for mode, declared in _BACKEND_CAPABILITIES.items():
        backend = create_product_robot_backend(
            RobotBackendConfig(mode=mode), client_factory=MagicMock(),
        )
        assert declared.to_public_dict() == backend.capabilities.to_public_dict()
