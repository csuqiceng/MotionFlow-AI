"""Runtime path helpers derived from the active config context."""

from __future__ import annotations

import os
from pathlib import Path

from nanobot.utils.helpers import ensure_dir


def _default_home() -> Path:
    """Root directory for nanobot user data.

    Honors ``NANOBOT_HOME`` so self-contained builds (e.g. the Electron desktop
    app) can redirect all user data to a writable location such as ``%APPDATA%``.
    Falls back to ``~/.nanobot`` when unset, preserving the historical behavior.
    """
    home = os.environ.get("NANOBOT_HOME")
    return Path(home).expanduser() if home else Path.home() / ".nanobot"


def get_config_path() -> Path:
    """Get the configuration file path (lazy import to break circular dependency).

    Delegates to ``nanobot.config.loader.get_config_path`` at call time so
    that importing this module never triggers a circular import during startup.
    """
    from nanobot.config.loader import get_config_path as _loader_get_config_path
    return _loader_get_config_path()


def get_nanobot_home() -> Path:
    """Return the one authoritative runtime root for this process.

    Runtime data follows the final configuration path so a CLI ``--config``
    cannot accidentally read libraries from a different ``NANOBOT_HOME``.
    Electron supplies both values and must keep them identical.
    """
    config_parent = get_config_path().expanduser().parent.resolve(strict=False)
    configured_home = os.environ.get("NANOBOT_HOME")
    if configured_home:
        env_home = Path(configured_home).expanduser().resolve(strict=False)
        if env_home != config_parent:
            raise RuntimeError(
                "NANOBOT_HOME must match the parent directory of the active config path."
            )
    return config_parent


def get_robot_ai_dir() -> Path:
    """Return the robot library directory below the authoritative runtime root."""
    return get_nanobot_home() / "robot_ai"


def get_runtime_path(*parts: str) -> Path:
    """Return a path below the authoritative runtime root without creating it."""
    return get_nanobot_home().joinpath(*parts)


def get_data_dir() -> Path:
    """Return the instance-level runtime data directory."""
    return ensure_dir(get_nanobot_home())


def get_runtime_subdir(name: str) -> Path:
    """Return a named runtime subdirectory under the instance data dir."""
    return ensure_dir(get_data_dir() / name)


def get_media_dir(channel: str | None = None) -> Path:
    """Return the media directory, optionally namespaced per channel."""
    base = get_runtime_subdir("media")
    return ensure_dir(base / channel) if channel else base


def get_cron_dir() -> Path:
    """Return the cron storage directory."""
    return get_runtime_subdir("cron")


def get_logs_dir() -> Path:
    """Return the logs directory."""
    return get_runtime_subdir("logs")


def get_webui_dir() -> Path:
    """Return the directory for WebUI-only persisted display threads (JSON)."""
    return get_runtime_subdir("webui")


def get_workspace_path(workspace: str | None = None) -> Path:
    """Resolve and ensure the agent workspace path."""
    path = Path(workspace).expanduser() if workspace else get_nanobot_home() / "workspace"
    return ensure_dir(path)


def is_default_workspace(workspace: str | Path | None) -> bool:
    """Return whether a workspace resolves to nanobot's default workspace path."""
    default = get_nanobot_home() / "workspace"
    current = Path(workspace).expanduser() if workspace is not None else default
    return current.resolve(strict=False) == default.resolve(strict=False)


def get_cli_history_path() -> Path:
    """Return the shared CLI history file path."""
    return get_nanobot_home() / "history" / "cli_history"


def get_legacy_sessions_dir() -> Path:
    """Return the legacy global session directory used for migration fallback."""
    return Path.home() / ".nanobot" / "sessions"
