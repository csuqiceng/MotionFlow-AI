from pathlib import Path
from unittest.mock import MagicMock, patch

from ai_runtime import AgentRuntime
from ai_runtime.provider_config import AiProviderConfig
from ai_runtime.robot_prompt import ROBOT_RUNTIME_PROMPT
from ai_runtime.tool_loader import RobotToolLoader
from robot_server.runtime import _local_reminder_content, create_agent_runtime


def test_legacy_local_channel_reminder_is_unwrapped_before_delivery() -> None:
    assert _local_reminder_content(
        'Send a message to the user in channel robot-server (chat_id: chat-1): "五分钟到了"'
    ) == "五分钟到了"
    assert _local_reminder_content("检查机械臂状态") == "检查机械臂状态"


def test_runtime_factory_builds_loop_without_channel_manager(tmp_path: Path) -> None:
    config = MagicMock()
    config.workspace_path = tmp_path
    loop = MagicMock()

    provider_config = AiProviderConfig(
        engine_id="nanobot",
        provider="openai",
        model="gpt-test",
        credential_ref="os-vault:robot-ai",
    )

    with patch("robot_server.runtime.load_ai_runtime_config", return_value=provider_config) as load_provider, \
         patch("robot_server.runtime.load_config", return_value=config), \
         patch("robot_server.runtime.SessionManager"), \
         patch("robot_server.runtime.AgentLoop.from_config", return_value=loop) as factory:
        runtime = create_agent_runtime(tmp_path / "config.json")

    load_provider.assert_called_once_with(tmp_path / "config.json")
    factory.assert_called_once()
    assert isinstance(runtime, AgentRuntime)
    assert factory.call_args.kwargs["tool_loader"].__class__ is RobotToolLoader
    assert factory.call_args.kwargs["enable_builtin_commands"] is False
    assert factory.call_args.kwargs["system_prompt_addendum"] == ROBOT_RUNTIME_PROMPT


def test_runtime_factory_uses_saved_profile_tools_after_restart(tmp_path: Path) -> None:
    config = MagicMock()
    config.workspace_path = tmp_path
    loop = MagicMock()
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
         patch("robot_server.runtime.load_config", return_value=config), \
         patch("robot_server.runtime.SessionManager"), \
         patch("robot_server.runtime.AgentLoop.from_config", return_value=loop) as factory:
        create_agent_runtime(tmp_path / "config.json")

    loader = factory.call_args.kwargs["tool_loader"]
    assert isinstance(loader, RobotToolLoader)
    assert loader._enabled_tools == ["robot_knowledge"]
