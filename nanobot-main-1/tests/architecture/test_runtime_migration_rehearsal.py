from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from robot_platform.migration_rehearsal import rehearse_legacy_runtime_migration


def _legacy_runtime(root: Path) -> Path:
    runtime = root / "runtime"
    legacy = runtime / "robot_ai"
    legacy.mkdir(parents=True)
    (runtime / "config.json").write_text('{"tools":{"execution_mode":"dry_run_only"}}', encoding="utf-8")
    (runtime / "sessions.json").write_text('{"sessions":["operator-1"]}', encoding="utf-8")
    (legacy / "commands.json").write_text('{"commands":[{"id":"wait"}]}', encoding="utf-8")
    (legacy / "flows.json").write_text('{"flows":[{"id":"load"}]}', encoding="utf-8")
    (legacy / "audit.jsonl").write_text('{"action":"seed"}\n', encoding="utf-8")
    return runtime


def test_rehearsal_copies_only_to_scratch_and_proves_the_legacy_backup_is_intact(tmp_path: Path) -> None:
    source = _legacy_runtime(tmp_path / "source")
    source_before = (source / "robot_ai" / "commands.json").read_bytes()
    scratch = tmp_path / "scratch"

    report = rehearse_legacy_runtime_migration(source, scratch)

    copied_runtime = scratch / "runtime"
    assert report["ok"] is True
    assert report["simulation_only"] is True
    assert (source / "robot_ai" / "commands.json").read_bytes() == source_before
    assert (copied_runtime / "robot_ai" / "commands.json").is_file()
    assert (scratch / "legacy-replay" / "robot_platform" / "commands.json").read_bytes() == source_before
    assert report["legacy_preserved"] is True
    assert report["target_matches_legacy"] is True
    assert json.loads((scratch / "runtime-migration-rehearsal.json").read_text(encoding="utf-8"))["ok"] is True


def test_rehearsal_replays_legacy_migration_when_source_already_has_canonical_data(
    tmp_path: Path,
) -> None:
    source = _legacy_runtime(tmp_path / "source")
    canonical = source / "robot_platform"
    canonical.mkdir()
    (canonical / "commands.json").write_text('{"commands":[{"id":"newer"}]}', encoding="utf-8")
    canonical_before = (canonical / "commands.json").read_bytes()

    report = rehearse_legacy_runtime_migration(source, tmp_path / "scratch")

    assert report["ok"] is True
    assert report["migration_performed"] is True
    assert (source / "robot_platform" / "commands.json").read_bytes() == canonical_before
    assert (
        tmp_path / "scratch" / "runtime" / "robot_platform" / "commands.json"
    ).read_bytes() == canonical_before
    assert (
        tmp_path / "scratch" / "legacy-replay" / "robot_platform" / "commands.json"
    ).read_bytes() == (source / "robot_ai" / "commands.json").read_bytes()


def test_rehearsal_refuses_to_merge_with_existing_scratch_data(tmp_path: Path) -> None:
    source = _legacy_runtime(tmp_path / "source")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / "unrelated.txt").write_text("do not overwrite", encoding="utf-8")

    with pytest.raises(ValueError, match="empty"):
        rehearse_legacy_runtime_migration(source, scratch)


def test_rehearsal_refuses_a_scratch_directory_inside_the_source(tmp_path: Path) -> None:
    source = _legacy_runtime(tmp_path / "source")

    with pytest.raises(ValueError, match="inside the source"):
        rehearse_legacy_runtime_migration(source, source / "scratch")


def test_rehearsal_cli_writes_a_machine_readable_report(tmp_path: Path) -> None:
    source = _legacy_runtime(tmp_path / "source")
    scratch = tmp_path / "scratch"
    root = Path(__file__).resolve().parents[2]

    completed = subprocess.run(
        [
            sys.executable,
            str(root / "tools" / "rehearse_runtime_migration.py"),
            "--source-runtime",
            str(source),
            "--scratch-root",
            str(scratch),
        ],
        cwd=root,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["ok"] is True
