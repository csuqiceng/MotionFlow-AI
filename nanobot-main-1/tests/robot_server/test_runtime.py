from pathlib import Path
from unittest.mock import MagicMock, patch

from ai_runtime import AgentRuntime
from ai_runtime.tool_loader import RobotToolLoader
from robot_server.runtime import create_agent_runtime


def test_runtime_factory_builds_loop_without_channel_manager(tmp_path: Path) -> None:
    config = MagicMock()
    config.workspace_path = tmp_path
    loop = MagicMock()

    with patch("robot_server.runtime.load_config", return_value=config), \
         patch("robot_server.runtime.SessionManager"), \
         patch("robot_server.runtime.AgentLoop.from_config", return_value=loop) as factory:
        runtime = create_agent_runtime(tmp_path / "config.json")

    factory.assert_called_once()
    assert isinstance(runtime, AgentRuntime)
    assert factory.call_args.kwargs["tool_loader"].__class__ is RobotToolLoader
    assert factory.call_args.kwargs["enable_builtin_commands"] is False
