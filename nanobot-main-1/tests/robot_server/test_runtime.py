from pathlib import Path
from unittest.mock import MagicMock, patch

from ai_runtime.provider_config import AiProviderConfig
from robot_server.runtime import _local_reminder_content, create_agent_runtime
from ai_runtime.providers.scripted_provider import ScriptedAgentEngine


def test_legacy_local_channel_reminder_is_unwrapped_before_delivery() -> None:
    assert _local_reminder_content(
        'Send a message to the user in channel robot-server (chat_id: chat-1): "五分钟到了"'
    ) == "五分钟到了"
    assert _local_reminder_content("检查机械臂状态") == "检查机械臂状态"


def test_runtime_factory_builds_loop_without_channel_manager(tmp_path: Path) -> None:
    engine = MagicMock()
    platform = MagicMock(name="shared-platform")
    status_application = MagicMock(name="status-application")
    dry_run_application = MagicMock(name="dry-run-application")

    provider_config = AiProviderConfig(
        engine_id="nanobot",
        provider="openai",
        model="gpt-test",
        credential_ref="os-vault:robot-ai",
    )

    with patch("robot_server.runtime.load_ai_runtime_config", return_value=provider_config) as load_provider, \
         patch("robot_server.runtime.create_nanobot_engine", return_value=engine) as factory:
        runtime = create_agent_runtime(
            tmp_path / "config.json",
            platform=platform,
            status_application=status_application,
            dry_run_application=dry_run_application,
        )

    load_provider.assert_called_once_with(tmp_path / "config.json")
    assert runtime is engine
    assert factory.call_args.kwargs["platform"] is platform
    assert factory.call_args.kwargs["status_application"] is status_application
    assert factory.call_args.kwargs["dry_run_application"] is dry_run_application


def test_runtime_factory_uses_saved_profile_tools_after_restart(tmp_path: Path) -> None:
    engine = MagicMock()
    provider_config = AiProviderConfig(
        engine_id="nanobot",
        provider="openai",
        model="gpt-test",
        credential_ref="os-vault:robot-ai",
    )
    (tmp_path / "product_profile.json").write_text(
        '{"backend_mode":"simulation","enabled_tools":["robot_knowledge"]}',
        encoding="utf-8",
    )

    with patch("robot_server.runtime.get_robot_data_dir", return_value=tmp_path), \
         patch("robot_server.runtime.load_ai_runtime_config", return_value=provider_config), \
         patch("robot_server.runtime.create_nanobot_engine", return_value=engine) as factory:
        create_agent_runtime(tmp_path / "config.json")

    assert factory.call_args.kwargs["enabled_tools"] == ["robot_knowledge"]


def test_runtime_can_select_second_provider_without_nanobot_composition(tmp_path) -> None:
    provider_config = AiProviderConfig(
        engine_id="scripted",
        provider="none",
        model="scripted",
        credential_ref="none",
    )
    with patch(
        "robot_server.runtime.load_ai_runtime_config", return_value=provider_config,
    ), patch("robot_server.runtime.create_nanobot_engine") as nanobot_factory:
        engine = create_agent_runtime(tmp_path / "config.json")

    assert isinstance(engine, ScriptedAgentEngine)
    nanobot_factory.assert_not_called()
