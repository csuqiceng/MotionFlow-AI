from __future__ import annotations

import json
from pathlib import Path

import pytest


def _seed(seed_root: Path) -> None:
    (seed_root / "robot_ai").mkdir(parents=True)
    (seed_root / "config.default.json").write_text('{"gateway": {}}', encoding="utf-8")
    for name in ("positions.json", "commands.json", "flows.json", "knowledge.json"):
        (seed_root / "robot_ai" / name).write_text('{"version": "1.0"}', encoding="utf-8")


def test_initialize_runtime_seeds_once_and_writes_ready_manifest(tmp_path: Path) -> None:
    from nanobot.runtime_data import initialize_runtime_data

    seed_root = tmp_path / "defaults"
    runtime = tmp_path / "userData" / "runtime"
    _seed(seed_root)

    result = initialize_runtime_data(runtime, seed_root=seed_root, legacy_home=None)

    assert result.action == "seeded"
    assert (runtime / "config.json").exists()
    manifest = json.loads((runtime / "runtime.manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "ready"
    assert (runtime / "robot_ai" / "positions.json").exists()
    for relative in ("cron", "webui", "media", "workspace"):
        assert (runtime / relative).is_dir()
    users = json.loads((runtime / "robot_ai" / "users.json").read_text(encoding="utf-8"))
    assert {user["username"] for user in users["users"].values()} == {"admin", "operator"}
    assert all("must_change_password" not in user for user in users["users"].values())


def test_initialize_runtime_migrates_legacy_before_using_defaults(tmp_path: Path) -> None:
    from nanobot.runtime_data import initialize_runtime_data

    seed_root = tmp_path / "defaults"
    runtime = tmp_path / "userData" / "runtime"
    legacy = tmp_path / "legacy"
    _seed(seed_root)
    (legacy / "robot_ai").mkdir(parents=True)
    (legacy / "config.json").write_text('{"gateway": {"port": 9999}}', encoding="utf-8")
    for name in ("positions.json", "commands.json", "flows.json"):
        (legacy / "robot_ai" / name).write_text('{"version": "1.0"}', encoding="utf-8")

    result = initialize_runtime_data(runtime, seed_root=seed_root, legacy_home=legacy)

    assert result.action == "migrated"
    assert json.loads((runtime / "config.json").read_text(encoding="utf-8"))["gateway"]["port"] == 9999
    assert legacy.exists()


def test_initialize_runtime_blocks_gateway_when_recovery_artifacts_exist(tmp_path: Path) -> None:
    from nanobot.runtime_data import RuntimeRecoveryRequired, initialize_runtime_data

    seed_root = tmp_path / "defaults"
    runtime = tmp_path / "userData" / "runtime"
    _seed(seed_root)
    staging = runtime.parent / "runtime.staging.interrupted"
    staging.mkdir(parents=True)

    with pytest.raises(RuntimeRecoveryRequired):
        initialize_runtime_data(runtime, seed_root=seed_root, legacy_home=None)


def test_environment_bootstrap_migrates_before_gateway_loads_missing_config(
    monkeypatch, tmp_path: Path
) -> None:
    from nanobot.runtime_data import initialize_runtime_from_environment

    runtime = tmp_path / "runtime"
    defaults = tmp_path / "defaults"
    legacy = tmp_path / "legacy"
    _seed(defaults)
    (legacy / "robot_ai").mkdir(parents=True)
    (legacy / "config.json").write_text('{"gateway": {}}', encoding="utf-8")
    for name in ("positions.json", "commands.json", "flows.json"):
        (legacy / "robot_ai" / name).write_text('{"version": "1.0"}', encoding="utf-8")
    monkeypatch.setenv("NANOBOT_HOME", str(runtime))
    monkeypatch.setenv("NANOBOT_DEFAULTS_DIR", str(defaults))

    result = initialize_runtime_from_environment(runtime / "config.json", legacy_home=legacy)

    assert result is not None and result.action == "migrated"
    assert (runtime / "runtime.manifest.json").exists()


def test_environment_bootstrap_applies_electron_ports_after_migration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Electron must not create a partial config before legacy migration."""
    from nanobot.runtime_data import initialize_runtime_from_environment

    runtime = tmp_path / "runtime"
    defaults = tmp_path / "defaults"
    legacy = tmp_path / "legacy"
    _seed(defaults)
    (legacy / "robot_ai").mkdir(parents=True)
    (legacy / "config.json").write_text('{"gateway": {}}', encoding="utf-8")
    for name in ("positions.json", "commands.json", "flows.json"):
        (legacy / "robot_ai" / name).write_text('{"version": "1.0"}', encoding="utf-8")
    monkeypatch.setenv("NANOBOT_HOME", str(runtime))
    monkeypatch.setenv("NANOBOT_DEFAULTS_DIR", str(defaults))
    monkeypatch.setenv("NANOBOT_RUNTIME_CHANNEL_PORT", "31001")
    monkeypatch.setenv("NANOBOT_RUNTIME_GATEWAY_PORT", "31002")

    result = initialize_runtime_from_environment(runtime / "config.json", legacy_home=legacy)

    assert result is not None and result.action == "migrated"
    config = json.loads((runtime / "config.json").read_text(encoding="utf-8"))
    assert config["channels"]["websocket"]["port"] == 31001
    assert config["gateway"]["port"] == 31002


def test_initial_seed_marker_adds_first_run_accounts_when_electron_seeded_files(tmp_path: Path, monkeypatch) -> None:
    from nanobot.runtime_data import initialize_runtime_data

    seed_root = tmp_path / "defaults"
    runtime = tmp_path / "runtime"
    _seed(seed_root)
    (runtime / "robot_ai").mkdir(parents=True)
    (runtime / "config.json").write_text('{"gateway": {}}', encoding="utf-8")
    for name in ("positions.json", "commands.json", "flows.json"):
        (runtime / "robot_ai" / name).write_text('{"version": "1.0"}', encoding="utf-8")
    monkeypatch.setenv("NANOBOT_INITIAL_SEED", "1")

    result = initialize_runtime_data(runtime, seed_root=seed_root, legacy_home=None)

    assert result.action == "adopted"
    assert (runtime / "robot_ai" / "users.json").exists()


def test_runtime_recovers_a_switched_directory_after_state_write_interruption(tmp_path: Path) -> None:
    from nanobot.runtime_data import initialize_runtime_data

    seed_root = tmp_path / "defaults"
    runtime = tmp_path / "runtime"
    _seed(seed_root)
    initialize_runtime_data(runtime, seed_root=seed_root, legacy_home=None)
    state_path = runtime.parent / "migration-state.json"
    state_path.write_text('{"status": "ready_to_switch"}', encoding="utf-8")

    result = initialize_runtime_data(runtime, seed_root=seed_root, legacy_home=None)

    assert result.action == "ready"
    assert json.loads(state_path.read_text(encoding="utf-8"))["status"] == "complete"


def test_runtime_recovery_rejects_a_tampered_switched_manifest(tmp_path: Path) -> None:
    from nanobot.runtime_data import RuntimeRecoveryRequired, initialize_runtime_data

    seed_root = tmp_path / "defaults"
    runtime = tmp_path / "runtime"
    _seed(seed_root)
    initialize_runtime_data(runtime, seed_root=seed_root, legacy_home=None)
    (runtime / "config.json").write_text('{"gateway": {"port": 9999}}', encoding="utf-8")
    (runtime.parent / "migration-state.json").write_text(
        '{"status": "ready_to_switch"}', encoding="utf-8"
    )

    with pytest.raises(RuntimeRecoveryRequired, match="hash"):
        initialize_runtime_data(runtime, seed_root=seed_root, legacy_home=None)


def test_migration_leaves_atomic_lock_as_recovery_evidence_on_copy_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import nanobot.runtime_data as runtime_data

    seed_root = tmp_path / "defaults"
    runtime = tmp_path / "runtime"
    _seed(seed_root)
    monkeypatch.setattr(runtime_data, "_copy_seed", lambda *_args: (_ for _ in ()).throw(OSError("disk full")))

    with pytest.raises(OSError, match="disk full"):
        runtime_data.initialize_runtime_data(runtime, seed_root=seed_root, legacy_home=None)

    lock = runtime.parent / "migration.lock"
    assert lock.exists()
    assert json.loads(lock.read_text(encoding="utf-8"))["runtime"] == str(runtime)


def test_migration_records_noncritical_files_skipped_for_size_limit(tmp_path: Path, monkeypatch) -> None:
    import nanobot.runtime_data as runtime_data

    seed_root = tmp_path / "defaults"
    runtime = tmp_path / "runtime"
    legacy = tmp_path / "legacy"
    _seed(seed_root)
    (legacy / "robot_ai").mkdir(parents=True)
    (legacy / "config.json").write_text('{"gateway": {}}', encoding="utf-8")
    for name in ("positions.json", "commands.json", "flows.json"):
        (legacy / "robot_ai" / name).write_text('{"version": "1.0"}', encoding="utf-8")
    (legacy / "media.bin").write_bytes(b"x" * 32)
    monkeypatch.setattr(runtime_data, "MAX_FILE_BYTES", 20)

    runtime_data.initialize_runtime_data(runtime, seed_root=seed_root, legacy_home=legacy)

    report = json.loads((runtime / "migration-report.json").read_text(encoding="utf-8"))
    assert report["skipped"] == [{"path": "media.bin", "reason": "file_size_limit"}]
    assert not (runtime / "media.bin").exists()


def test_migration_preserves_unknown_legacy_runtime_content(tmp_path: Path) -> None:
    from nanobot.runtime_data import initialize_runtime_data

    seed_root = tmp_path / "defaults"
    runtime = tmp_path / "userData" / "runtime"
    legacy = tmp_path / "legacy-nanobot"
    _seed(seed_root)
    (legacy / "robot_ai").mkdir(parents=True)
    (legacy / "config.json").write_text('{"gateway": {"port": 9999}}', encoding="utf-8")
    for name in ("positions.json", "commands.json", "flows.json"):
        (legacy / "robot_ai" / name).write_text('{"version": "1.0"}', encoding="utf-8")
    (legacy / "cron").mkdir()
    (legacy / "cron" / "jobs.json").write_text('{"jobs": []}', encoding="utf-8")
    (legacy / "media").mkdir()
    (legacy / "media" / "capture.bin").write_bytes(b"capture")
    (legacy / "workspace" / "future-plugin").mkdir(parents=True)
    (legacy / "workspace" / "future-plugin" / "state.txt").write_text("keep", encoding="utf-8")

    result = initialize_runtime_data(runtime, seed_root=seed_root, legacy_home=legacy)

    assert result.action == "migrated"
    assert (runtime / "cron" / "jobs.json").read_text(encoding="utf-8") == '{"jobs": []}'
    assert (runtime / "media" / "capture.bin").read_bytes() == b"capture"
    assert (runtime / "workspace" / "future-plugin" / "state.txt").read_text(encoding="utf-8") == "keep"
    assert legacy.exists()
