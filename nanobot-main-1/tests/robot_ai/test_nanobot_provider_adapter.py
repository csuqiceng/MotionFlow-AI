from pathlib import Path
from unittest.mock import MagicMock, patch

from ai_runtime.providers.nanobot_engine import NanobotEngine
from ai_runtime.providers.nanobot_runtime import create_nanobot_engine
from ai_runtime.robot_prompt import ROBOT_RUNTIME_PROMPT
from ai_runtime.tool_loader import RobotToolLoader


def test_nanobot_adapter_owns_all_concrete_loop_composition(tmp_path: Path) -> None:
    config = MagicMock(workspace_path=tmp_path)
    loop = MagicMock()
    platform = MagicMock()

    with patch(
        "ai_runtime.providers.nanobot_runtime.load_config", return_value=config,
    ), patch(
        "ai_runtime.providers.nanobot_runtime.SessionManager",
    ), patch(
        "ai_runtime.providers.nanobot_runtime.AgentLoop.from_config",
        return_value=loop,
    ) as factory:
        runtime = create_nanobot_engine(
            tmp_path / "config.json",
            enabled_tools=["robot_knowledge"],
            platform=platform,
        )

    assert isinstance(runtime, NanobotEngine)
    loader = factory.call_args.kwargs["tool_loader"]
    assert isinstance(loader, RobotToolLoader)
    assert loader._enabled_tools == ["robot_knowledge"]
    assert loader._platform is platform
    assert factory.call_args.kwargs["enable_builtin_commands"] is False
    assert factory.call_args.kwargs["system_prompt_addendum"] == ROBOT_RUNTIME_PROMPT


def test_disabled_cron_is_not_constructed_or_started(tmp_path: Path) -> None:
    config = MagicMock(workspace_path=tmp_path)
    loop = MagicMock()
    with patch(
        "ai_runtime.providers.nanobot_runtime.load_config", return_value=config,
    ), patch(
        "ai_runtime.providers.nanobot_runtime.SessionManager",
    ), patch(
        "ai_runtime.providers.nanobot_runtime.CronService",
    ) as cron_factory, patch(
        "ai_runtime.providers.nanobot_runtime.AgentLoop.from_config",
        return_value=loop,
    ) as loop_factory:
        create_nanobot_engine(
            tmp_path / "config.json", enabled_tools=["robot_knowledge"],
        )
    cron_factory.assert_not_called()
    assert loop_factory.call_args.kwargs["cron_service"] is None
