from __future__ import annotations

import os
import json
import shutil
from contextlib import contextmanager
from contextvars import ContextVar, Token
from pathlib import Path
from threading import RLock
from typing import Callable
_VALID_EXECUTION_MODES = frozenset({"dry_run_only", "auto_after_safety_check", "manual_confirm"})


# The robot platform must not discover its host application's configuration or
# request context.  Hosts configure this small context at startup; direct
# platform use remains safe and deterministic with a dry-run, legacy-compatible
# data location.
_runtime_lock = RLock()
_runtime_data_dir: Path | None = None
_runtime_execution_mode = "dry_run_only"
_session_key_provider: Callable[[], str | None] = lambda: None
_robot_actor: ContextVar[str] = ContextVar("robot_platform_actor", default="untrusted:local")


def configure_robot_runtime(
    *,
    data_dir: str | Path | None = None,
    execution_mode: str | None = None,
    session_key_provider: Callable[[], str | None] | None = None,
) -> None:
    """Inject host-owned runtime values without importing the host package."""
    global _runtime_data_dir, _runtime_execution_mode, _session_key_provider
    with _runtime_lock:
        if data_dir is not None:
            _runtime_data_dir = Path(data_dir).expanduser()
        if execution_mode is not None:
            candidate = str(execution_mode)
            _runtime_execution_mode = (
                candidate if candidate in _VALID_EXECUTION_MODES else "dry_run_only"
            )
        if session_key_provider is not None:
            _session_key_provider = session_key_provider


def get_robot_data_dir() -> Path:
    """Return the platform data directory without consulting a host config."""
    with _runtime_lock:
        if _runtime_data_dir is not None:
            return _runtime_data_dir
    configured = os.environ.get("ROBOT_PLATFORM_DATA_DIR") or os.environ.get("ROBOT_AI_DATA_DIR")
    return Path(configured).expanduser() if configured else Path.home() / ".nanobot" / "robot_platform"


def migrate_legacy_robot_data_dir(target: str | Path) -> bool:
    """Copy legacy ``robot_ai`` runtime data into the canonical directory.

    The old directory is retained as a rollback backup.  A report next to the
    directories makes the one-time migration observable and supportable.
    """
    target_path = Path(target).expanduser()
    source_path = target_path.with_name("robot_ai")
    if target_path.exists() or not source_path.is_dir():
        return False
    shutil.copytree(source_path, target_path)
    report = {
        "version": 1,
        "source": str(source_path),
        "target": str(target_path),
        "mode": "copy_kept_legacy_backup",
        "files": sum(1 for path in target_path.rglob("*") if path.is_file()),
    }
    (target_path.parent / "robot_platform_migration.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return True


def get_robot_execution_mode() -> str:
    """Return the injected execution mode; fail closed when it is invalid."""
    with _runtime_lock:
        return _runtime_execution_mode


def current_robot_request_session_key() -> str | None:
    """Get a host-provided request/session identifier for confirmation binding."""
    with _runtime_lock:
        provider = _session_key_provider
    return provider()


def current_robot_actor() -> str:
    """Return the role-qualified actor for the active AI turn."""
    return _robot_actor.get()


@contextmanager
def bind_robot_actor(actor: str):
    """Bind an authenticated actor to one asynchronous runtime turn."""
    token: Token[str] = _robot_actor.set(str(actor or "untrusted:local"))
    try:
        yield
    finally:
        _robot_actor.reset(token)


def reset_robot_runtime_for_tests() -> None:
    """Restore safe defaults. Intended for focused platform tests only."""
    global _runtime_data_dir, _runtime_execution_mode, _session_key_provider
    with _runtime_lock:
        _runtime_data_dir = None
        _runtime_execution_mode = "dry_run_only"
        _session_key_provider = lambda: None
