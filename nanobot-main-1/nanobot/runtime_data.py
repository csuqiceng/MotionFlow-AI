"""Crash-safe preparation of the Electron runtime data directory.

The Electron main process decides the root and passes it to Gateway as both
``NANOBOT_HOME`` and the parent of ``--config``.  This module only prepares
that root; it never deletes the legacy source directory.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


_CRITICAL_FILES = (
    "config.json",
    "robot_ai/positions.json",
    "robot_ai/commands.json",
    "robot_ai/flows.json",
)
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024


class RuntimeRecoveryRequired(RuntimeError):
    """Raised when a previous initialization left recovery evidence behind."""


@dataclass(frozen=True)
class RuntimeInitialization:
    action: str
    runtime_root: Path


def initialize_runtime_data(
    runtime_root: str | Path, *, seed_root: str | Path, legacy_home: str | Path | None
) -> RuntimeInitialization:
    """Prepare a ready runtime root by adopting, migrating, or seeding it.

    A staging directory is deliberately treated as recovery evidence.  Gateway
    must not start until an operator resolves it, rather than risking a second
    migration over partial data.
    """
    runtime = Path(runtime_root)
    seed = Path(seed_root)
    parent = runtime.parent
    state_path = parent / "migration-state.json"
    state = _read_migration_state(state_path)
    manifest = runtime / "runtime.manifest.json"
    staging_paths = list(parent.glob(f"{runtime.name}.staging.*"))
    if staging_paths:
        raise RuntimeRecoveryRequired("Incomplete runtime migration detected; recovery is required.")
    if state.get("status") != "complete" and manifest.exists():
        # The directory was renamed but the completion record was not written.
        # This narrow recovery path verifies the just-committed contents before
        # declaring the migration complete; ordinary later config edits do not
        # invalidate a ready runtime's historical manifest hashes.
        _validate_manifest(manifest, verify_hashes=True)
        _write_migration_state(state_path, "complete")
        _release_migration_lock(parent)
        return RuntimeInitialization("ready", runtime)
    if (parent / "migration.lock").exists():
        raise RuntimeRecoveryRequired("Incomplete runtime migration detected; recovery is required.")

    if manifest.exists():
        _validate_manifest(manifest)
        return RuntimeInitialization("ready", runtime)

    if (runtime / "config.json").exists():
        _validate_critical_files(runtime)
        _ensure_runtime_layout(runtime)
        if os.environ.get("NANOBOT_INITIAL_SEED") == "1":
            _create_initial_users(runtime)
        _write_manifest(runtime, source="adopted")
        return RuntimeInitialization("adopted", runtime)

    legacy = Path(legacy_home) if legacy_home is not None else None
    if legacy is not None and legacy.exists():
        return _build_runtime(runtime, source_root=legacy, action="migrated", source="legacy")
    return _build_runtime(runtime, source_root=seed, action="seeded", source="seed")


def initialize_runtime_from_environment(
    config_path: str | Path, *, legacy_home: str | Path | None = None
) -> RuntimeInitialization | None:
    """Prepare an Electron runtime before its configuration is loaded.

    Normal CLI installs retain their historical behavior.  Electron opts in by
    passing both ``NANOBOT_HOME`` and ``NANOBOT_DEFAULTS_DIR``.
    """
    runtime_home = os.environ.get("NANOBOT_HOME")
    defaults = os.environ.get("NANOBOT_DEFAULTS_DIR")
    if not runtime_home or not defaults:
        return None
    runtime = Path(runtime_home).expanduser().resolve(strict=False)
    expected_config = runtime / "config.json"
    actual_config = Path(config_path).expanduser().resolve(strict=False)
    if actual_config != expected_config:
        raise RuntimeError("NANOBOT_HOME must match the parent directory of --config.")
    if legacy_home is None:
        candidate = Path.home() / ".nanobot"
        legacy_home = candidate if candidate.resolve(strict=False) != runtime else None
    result = initialize_runtime_data(runtime, seed_root=defaults, legacy_home=legacy_home)
    _apply_runtime_port_overrides(runtime)
    return result


def _apply_runtime_port_overrides(runtime: Path) -> None:
    """Apply Electron's ephemeral local ports only after runtime data is ready."""
    channel_port = _runtime_port_from_environment("NANOBOT_RUNTIME_CHANNEL_PORT")
    gateway_port = _runtime_port_from_environment("NANOBOT_RUNTIME_GATEWAY_PORT")
    if channel_port is None and gateway_port is None:
        return
    config_path = runtime / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if channel_port is not None:
        channels = config.setdefault("channels", {})
        websocket = channels.setdefault("websocket", {})
        websocket["enabled"] = True
        websocket["host"] = "127.0.0.1"
        websocket["port"] = channel_port
        websocket["token_issue_secret"] = ""
        websocket.pop("token", None)
    if gateway_port is not None:
        config.setdefault("gateway", {})["port"] = gateway_port
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _runtime_port_from_environment(name: str) -> int | None:
    value = os.environ.get(name)
    if value is None:
        return None
    try:
        port = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer TCP port.") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"{name} must be between 1 and 65535.")
    return port


def _build_runtime(runtime: Path, *, source_root: Path, action: str, source: str) -> RuntimeInitialization:
    parent = runtime.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = parent / f"{runtime.name}.staging.{os.getpid()}"
    state_path = parent / "migration-state.json"
    if staging.exists():
        raise RuntimeRecoveryRequired(f"Staging directory already exists: {staging}")
    _acquire_migration_lock(parent, runtime)
    staging.mkdir()
    _write_migration_state(state_path, "copying")
    try:
        if source == "seed":
            _copy_seed(source_root, staging)
            _create_initial_users(staging)
        else:
            skipped = _copy_tree(source_root, staging)
            _write_migration_report(staging, skipped)
        _ensure_runtime_layout(staging)
        _validate_critical_files(staging)
        _write_manifest(staging, source=source)
        _write_migration_state(state_path, "ready_to_switch")
        if runtime.exists():
            raise RuntimeRecoveryRequired(f"Runtime root appeared during initialization: {runtime}")
        os.replace(staging, runtime)
        _write_migration_state(state_path, "switched_pending_cleanup")
        _write_migration_state(state_path, "complete")
        _release_migration_lock(parent)
    except Exception:
        # Preserve staging evidence for a recoverable investigation; never
        # delete either a partial target or the legacy source.
        raise
    return RuntimeInitialization(action, runtime)


def _read_migration_state(path: Path) -> dict[str, str]:
    if not path.exists():
        return {"status": "complete"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeRecoveryRequired("Migration state is not valid JSON.") from exc
    if not isinstance(data, dict) or not isinstance(data.get("status"), str):
        raise RuntimeRecoveryRequired("Migration state is invalid.")
    return {"status": data["status"]}


def _write_migration_state(path: Path, status: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump({"status": status}, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _acquire_migration_lock(parent: Path, runtime: Path) -> Path:
    """Create migration.lock with exclusive creation; never steal another run."""
    lock = parent / "migration.lock"
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeRecoveryRequired("Incomplete runtime migration detected; recovery is required.") from exc
    try:
        payload = {
            "runtime": str(runtime),
            "pid": os.getpid(),
            "started_at": datetime.now(UTC).isoformat(),
        }
        encoded = json.dumps(payload).encode("utf-8")
        os.write(fd, encoded)
        os.fsync(fd)
    finally:
        os.close(fd)
    return lock


def _release_migration_lock(parent: Path) -> None:
    """Remove only our completed migration marker after state is durable."""
    try:
        (parent / "migration.lock").unlink()
    except FileNotFoundError:
        pass


def _copy_seed(seed_root: Path, destination: Path) -> None:
    config = seed_root / "config.default.json"
    if not config.exists():
        raise ValueError(f"Missing seed configuration: {config}")
    shutil.copy2(config, destination / "config.json")
    for name in ("positions.json", "commands.json", "flows.json", "knowledge.json"):
        source = seed_root / "robot_ai" / name
        if not source.exists():
            raise ValueError(f"Missing seed file: {source}")
        target = destination / "robot_ai" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _create_initial_users(runtime_root: Path) -> None:
    """Create documented first-run accounts; each is server-side restricted."""
    from robot_ai.library.auth import hash_password
    from robot_ai.library.users import UserRegistry

    robot_dir = runtime_root / "robot_ai"
    users_path = robot_dir / "users.json"
    if users_path.exists():
        return
    registry = UserRegistry(users_path, audit_path=robot_dir / "audit.jsonl")
    registry.create(
        "admin", "engineer", hash_password("0000"),
        actor={"actor": "system:seed", "actor_role": "system"},
    )
    registry.create(
        "operator", "operator", hash_password("1234"),
        actor={"actor": "system:seed", "actor_role": "system"},
    )
    registry.drain_pending_audits()


def _ensure_runtime_layout(runtime_root: Path) -> None:
    """Create writable runtime-only directories without touching user content."""
    for relative in ("cron", "webui", "media", "workspace"):
        (runtime_root / relative).mkdir(parents=True, exist_ok=True)


def _copy_tree(source: Path, destination: Path) -> list[dict[str, str]]:
    """Copy regular files only, recording unsafe/oversized entries."""
    skipped: list[dict[str, str]] = []
    total = 0

    def copy_directory(current: Path, target_root: Path) -> None:
        nonlocal total
        for item in current.iterdir():
            relative = item.relative_to(source).as_posix()
            target = target_root / item.name
            if _is_reparse_or_link(item):
                skipped.append({"path": relative, "reason": "special_file"})
                continue
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                copy_directory(item, target)
                continue
            if not item.is_file():
                skipped.append({"path": relative, "reason": "non_regular_file"})
                continue
            size = item.stat().st_size
            if size > MAX_FILE_BYTES:
                skipped.append({"path": relative, "reason": "file_size_limit"})
                continue
            if total + size > MAX_TOTAL_BYTES:
                skipped.append({"path": relative, "reason": "total_size_limit"})
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            total += size

    copy_directory(source, destination)
    return skipped


def _is_reparse_or_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
    return bool(attributes & 0x0400)  # Windows FILE_ATTRIBUTE_REPARSE_POINT


def _write_migration_report(root: Path, skipped: list[dict[str, str]]) -> None:
    (root / "migration-report.json").write_text(
        json.dumps({"skipped": skipped}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _validate_critical_files(root: Path) -> None:
    for relative in _CRITICAL_FILES:
        path = root / relative
        if not path.exists():
            raise ValueError(f"Missing critical runtime file: {relative}")
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in critical runtime file: {relative}") from exc


def _validate_manifest(path: Path, *, verify_hashes: bool = False) -> None:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeRecoveryRequired("Runtime manifest is not valid JSON.") from exc
    if manifest.get("status") != "ready":
        raise RuntimeRecoveryRequired("Runtime manifest is not ready.")
    hashes = manifest.get("critical_file_hashes")
    if manifest.get("hash_algorithm") != "sha256" or not isinstance(hashes, dict):
        raise RuntimeRecoveryRequired("Runtime manifest is missing SHA-256 critical-file hashes.")
    if not verify_hashes:
        return
    for relative in _CRITICAL_FILES:
        expected = hashes.get(relative)
        actual_path = path.parent / relative
        if not isinstance(expected, str) or not actual_path.is_file():
            raise RuntimeRecoveryRequired(f"Runtime manifest hash data is invalid for {relative}.")
        actual = hashlib.sha256(actual_path.read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeRecoveryRequired(f"Runtime manifest hash mismatch for {relative}.")


def _write_manifest(root: Path, *, source: str) -> None:
    files = {
        relative: hashlib.sha256((root / relative).read_bytes()).hexdigest()
        for relative in _CRITICAL_FILES
    }
    payload = {
        "status": "ready",
        "data_format_version": 1,
        "source": source,
        "completed_at": datetime.now(UTC).isoformat(),
        "hash_algorithm": "sha256",
        "critical_file_hashes": files,
    }
    (root / "runtime.manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
