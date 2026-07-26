from pathlib import Path

from nanobot.config.paths import (
    get_cli_history_path,
    get_cron_dir,
    get_data_dir,
    get_legacy_sessions_dir,
    get_logs_dir,
    get_media_dir,
    get_nanobot_home,
    get_robot_ai_dir,
    get_runtime_path,
    get_runtime_subdir,
    get_workspace_path,
    is_default_workspace,
)


def test_runtime_dirs_follow_config_path(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "instance-a" / "config.json"
    monkeypatch.setattr("nanobot.config.paths.get_config_path", lambda: config_file)

    assert get_data_dir() == config_file.parent
    assert get_runtime_subdir("cron") == config_file.parent / "cron"
    assert get_cron_dir() == config_file.parent / "cron"
    assert get_logs_dir() == config_file.parent / "logs"


def test_unified_runtime_paths_follow_the_final_config_parent(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "instance-c" / "config.json"
    monkeypatch.setattr("nanobot.config.paths.get_config_path", lambda: config_file)

    assert get_nanobot_home() == config_file.parent
    assert get_robot_ai_dir() == config_file.parent / "robot_ai"
    assert get_runtime_path("robot_ai", "positions.json") == (
        config_file.parent / "robot_ai" / "positions.json"
    )


def test_unified_runtime_paths_reject_nanobot_home_that_disagrees_with_config(
    monkeypatch, tmp_path: Path
) -> None:
    config_file = tmp_path / "instance-d" / "config.json"
    monkeypatch.setattr("nanobot.config.paths.get_config_path", lambda: config_file)
    monkeypatch.setenv("NANOBOT_HOME", str(tmp_path / "other-instance"))

    import pytest

    with pytest.raises(RuntimeError, match="NANOBOT_HOME"):
        get_nanobot_home()


def test_media_dir_supports_channel_namespace(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "instance-b" / "config.json"
    monkeypatch.setattr("nanobot.config.paths.get_config_path", lambda: config_file)

    assert get_media_dir() == config_file.parent / "media"
    assert get_media_dir("telegram") == config_file.parent / "media" / "telegram"


def test_cli_history_follows_the_active_runtime_but_legacy_sessions_remain_global(
    monkeypatch, tmp_path: Path
) -> None:
    config_file = tmp_path / "instance-history" / "config.json"
    monkeypatch.setattr("nanobot.config.paths.get_config_path", lambda: config_file)

    assert get_cli_history_path() == config_file.parent / "history" / "cli_history"
    assert get_legacy_sessions_dir() == Path.home() / ".nanobot" / "sessions"


def test_workspace_path_is_explicitly_resolved_from_the_active_runtime(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "instance-workspace" / "config.json"
    monkeypatch.setattr("nanobot.config.paths.get_config_path", lambda: config_file)

    assert get_workspace_path() == config_file.parent / "workspace"
    assert get_workspace_path("~/custom-workspace") == Path.home() / "custom-workspace"


def test_is_default_workspace_distinguishes_runtime_default_and_custom_paths(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "instance-default-workspace" / "config.json"
    monkeypatch.setattr("nanobot.config.paths.get_config_path", lambda: config_file)

    assert is_default_workspace(None) is True
    assert is_default_workspace(config_file.parent / "workspace") is True
    assert is_default_workspace("~/custom-workspace") is False
