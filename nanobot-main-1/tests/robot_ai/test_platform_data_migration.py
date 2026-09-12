from __future__ import annotations

import json
from pathlib import Path

from robot_ai.runtime import migrate_legacy_robot_data_dir


def test_legacy_robot_data_is_copied_with_report_and_backup(tmp_path: Path) -> None:
    legacy = tmp_path / "robot_ai"
    legacy.mkdir()
    (legacy / "commands.json").write_text('{"commands": []}', encoding="utf-8")
    target = tmp_path / "robot_platform"

    assert migrate_legacy_robot_data_dir(target) is True
    assert (target / "commands.json").read_text(encoding="utf-8") == '{"commands": []}'
    assert (legacy / "commands.json").is_file()
    report = json.loads((tmp_path / "robot_platform_migration.json").read_text(encoding="utf-8"))
    assert report["mode"] == "copy_kept_legacy_backup"
    assert report["files"] == 1


def test_existing_canonical_data_is_never_overwritten(tmp_path: Path) -> None:
    (tmp_path / "robot_ai").mkdir()
    (tmp_path / "robot_ai" / "commands.json").write_text("legacy", encoding="utf-8")
    target = tmp_path / "robot_platform"
    target.mkdir()
    (target / "commands.json").write_text("canonical", encoding="utf-8")

    assert migrate_legacy_robot_data_dir(target) is False
    assert (target / "commands.json").read_text(encoding="utf-8") == "canonical"
