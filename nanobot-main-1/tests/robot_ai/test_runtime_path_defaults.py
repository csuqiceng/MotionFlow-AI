from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("loguru")
pytest.importorskip("pydantic")


def test_robot_tools_default_to_active_runtime_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Runtime tools must follow --config, not the process user's home directory."""
    from robot_ai.flow.execution_registry import LibraryExecutionRegistry
    from robot_ai.flow.versioned_registry import VersionedFlowRegistry
    from robot_ai.library.versioned_registry import VersionedCommandRegistry
    from robot_ai.nlp.normalizer import NlpNormalizer

    import nanobot.config.loader as loader
    from nanobot.agent.tools.robot_arm import RobotArmTool
    from nanobot.agent.tools.robot_flow import RobotFlowTool
    from nanobot.agent.tools.robot_knowledge import RobotKnowledgeTool
    from nanobot.agent.tools.robot_position import RobotPositionTool

    runtime = tmp_path / "runtime"
    monkeypatch.setenv("NANOBOT_HOME", str(runtime))
    monkeypatch.delenv("ROBOT_AI_POSITIONS_PATH", raising=False)
    monkeypatch.delenv("ROBOT_AI_FLOWS_PATH", raising=False)
    monkeypatch.delenv("ROBOT_AI_FLOW_ALIASES_PATH", raising=False)
    monkeypatch.delenv("ROBOT_AI_KNOWLEDGE_PATH", raising=False)
    monkeypatch.setattr(loader, "_current_config_path", runtime / "config.json")
    # The nanobot host injects its active runtime directory into the reusable
    # platform during configuration load; robot_ai no longer discovers it.
    loader.load_config(runtime / "config.json")

    robot_dir = runtime / "robot_platform"
    # Position storage is now selected by bootstrap and injected through an
    # Application port; standalone Tool construction stays store-free and
    # fails closed instead of discovering a host path.
    assert RobotPositionTool()._position_application is None
    assert RobotArmTool()._position_application is None
    assert RobotFlowTool()._flow_application is None
    assert RobotFlowTool()._registry_path is None
    assert RobotFlowTool()._alias_path is None
    assert Path(RobotKnowledgeTool()._path) == robot_dir / "knowledge.json"
    assert NlpNormalizer().path == robot_dir / "nlp_standard_words.json"
    assert VersionedCommandRegistry(tmp_path / "commands.json").audit_path == robot_dir / "audit.jsonl"
    assert VersionedFlowRegistry(tmp_path / "flows.json").audit_path == robot_dir / "audit.jsonl"
    assert LibraryExecutionRegistry()._history.path == robot_dir / "library_executions.json"
