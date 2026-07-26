from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_product_composition_uses_saved_backend_mode_and_tools(tmp_path) -> None:
    from robot_server.cli import build_product_platform

    (tmp_path / "product_profile.json").write_text(
        '{"backend_mode":"zmotion_readonly","enabled_tools":["robot_knowledge"]}',
        encoding="utf-8",
    )
    backend = MagicMock()

    with patch("robot_server.cli.create_product_robot_backend", return_value=backend) as create_backend:
        platform, enabled_tools = build_product_platform(tmp_path)

    assert create_backend.call_args.args[0].mode == "zmotion_readonly"
    assert platform._backend_config.mode == "zmotion_readonly"
    assert enabled_tools == ["robot_knowledge"]
