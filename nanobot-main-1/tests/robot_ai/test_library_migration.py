from __future__ import annotations

import json
from pathlib import Path

from robot_ai.library.migration import migrate_commands, seed_command_library_if_missing
from robot_ai.library.models import Command
from robot_ai.library.registry import CommandRegistry

# Path to the real legacy file: tests/robot_ai/ -> parents[2] = nanobot-main-1
REAL_LEGACY = Path(__file__).resolve().parents[2] / "data" / "legacy" / "query_table.json"


def _legacy(src_dir: Path, records: list[dict]) -> None:
    (src_dir / "query_table.json").write_text(
        json.dumps({"records": records}, ensure_ascii=False), encoding="utf-8"
    )


def test_migrate_real_legacy_file_16_migrated_5_skipped(tmp_path: Path) -> None:
    commands = tmp_path / "commands.json"
    audit = tmp_path / "audit.jsonl"
    result = migrate_commands(REAL_LEGACY, commands, audit)

    assert len(result.migrated) == 16
    assert len(result.skipped) == 5
    skipped_funcs = sorted(func for func, _name, _reason in result.skipped)
    assert skipped_funcs == [11, 106, 106, 107, 109]  # 106 appears twice (J1到10度 + J2回正)
    assert result.audit_written is True
    assert result.audit_error is None

    reg = CommandRegistry(commands)
    assert len(reg.list_all()) == 16
    # spot-check one of each mapped component
    assert any(c.component_id == "io_write" for c in reg.list_all())
    assert any(c.component_id == "linear_move" for c in reg.list_all())
    assert any(c.component_id == "system_action" for c in reg.list_all())
    assert any(c.component_id == "delay" for c in reg.list_all())


def test_migrate_audit_record_has_migration_id_and_summary(tmp_path: Path) -> None:
    commands = tmp_path / "commands.json"
    audit = tmp_path / "audit.jsonl"
    result = migrate_commands(REAL_LEGACY, commands, audit)

    lines = [ln for ln in audit.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["action"] == "legacy_import"
    assert entry["migration_id"] == result.migration_id
    assert entry["migration_id"].startswith("legacy-import:")
    assert entry["after"]["migrated"] == 16
    assert entry["after"]["skipped"] == 5
    assert entry["after"]["skipped_by_func"]["106"] == 2


def test_migrate_is_idempotent_rerun_is_noop(tmp_path: Path) -> None:
    commands = tmp_path / "commands.json"
    audit = tmp_path / "audit.jsonl"
    first = migrate_commands(REAL_LEGACY, commands, audit)
    second = migrate_commands(REAL_LEGACY, commands, audit)

    assert second.migration_id == first.migration_id
    assert second.migrated == []  # nothing new — idempotent
    # Unmappable records are re-evaluated and skipped on every run (stateless);
    # the key idempotency guarantees are: no new commands + no duplicate audit.
    assert len(second.skipped) == 5
    # audit NOT duplicated (dedup by migration_id)
    lines = [ln for ln in audit.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1
    assert second.audit_written is True


def test_migrate_skips_unmapped_and_reports_reasons(tmp_path: Path) -> None:
    src = tmp_path / "legacy"
    src.mkdir()
    _legacy(src, [
        {"query_key": "IO0打开", "func_num": 120, "keywords": "IO0 打开",
         "description": "on", "safety_level": 5, "params": {"io_no": 0, "io_action": 1}},
        {"query_key": "J1到10度", "func_num": 106, "keywords": "J1",
         "description": "joint", "safety_level": 5,
         "params": {"axis_no": 0, "pos_val": 10.0}},
    ])
    commands = tmp_path / "commands.json"
    audit = tmp_path / "audit.jsonl"
    result = migrate_commands(src / "query_table.json", commands, audit)

    assert len(result.migrated) == 1
    assert len(result.skipped) == 1
    func, name, reason = result.skipped[0]
    assert func == 106
    assert "joint" in reason


def test_migrate_failure_semantics_commands_written_audit_missing(tmp_path: Path) -> None:
    src = tmp_path / "legacy"
    src.mkdir()
    _legacy(src, [
        {"query_key": "IO0打开", "func_num": 120, "keywords": "IO0",
         "description": "on", "safety_level": 5, "params": {"io_no": 0, "io_action": 1}},
    ])
    commands = tmp_path / "commands.json"
    # Make audit path unwritable: parent is a regular file, not a directory.
    blocker = tmp_path / "blocker"
    blocker.write_text("I am a file", encoding="utf-8")
    audit = blocker / "audit.jsonl"

    result = migrate_commands(src / "query_table.json", commands, audit)
    # Commands were written...
    assert len(result.migrated) == 1
    assert CommandRegistry(commands).get("io0打开") is not None
    # ...but audit failed.
    assert result.audit_written is False
    assert result.audit_error is not None

    # Re-run against a writable audit path: backfills audit, no dup commands.
    good_audit = tmp_path / "audit.jsonl"
    result2 = migrate_commands(src / "query_table.json", commands, good_audit)
    assert result2.migrated == []  # idempotent — command already there
    assert result2.audit_written is True
    lines = [ln for ln in good_audit.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1


def test_cli_runs_via_env_overrides(tmp_path: Path, monkeypatch) -> None:
    import importlib

    out_dir = tmp_path / "library_out"
    monkeypatch.setenv("ROBOT_LEGACY_DATA_DIR", str(REAL_LEGACY.parent))
    monkeypatch.setenv("ROBOT_LEGACY_QUERY_TABLE", str(REAL_LEGACY.name))
    monkeypatch.setenv("ROBOT_LIBRARY_OUT_DIR", str(out_dir))

    import tools.migrate_robot_commands as cli

    importlib.reload(cli)
    rc = cli.main()
    assert rc == 0
    assert (out_dir / "commands.json").exists()
    assert (out_dir / "audit.jsonl").exists()


def test_seed_first_start_migrates_16(tmp_path: Path) -> None:
    commands = tmp_path / "commands.json"
    audit = tmp_path / "audit.jsonl"
    seeded = seed_command_library_if_missing(str(commands), str(audit))
    assert seeded is True
    reg = CommandRegistry(commands)
    assert len(reg.list_all()) == 16
    assert audit.exists()  # audit record written


def test_seed_second_start_does_not_overwrite(tmp_path: Path) -> None:
    commands = tmp_path / "commands.json"
    audit = tmp_path / "audit.jsonl"
    # Pre-existing commands.json with a hand-added command must be preserved.
    CommandRegistry(commands).add(Command(id="custom", name="custom", component_id="io_write"))
    before = commands.read_text(encoding="utf-8")

    seeded = seed_command_library_if_missing(str(commands), str(audit))
    assert seeded is False  # skipped — commands.json exists
    assert commands.read_text(encoding="utf-8") == before  # untouched
    reg = CommandRegistry(commands)
    assert reg.get("custom") is not None  # custom preserved
    assert reg.get("home") is None  # seed NOT applied (no overwrite)


def test_seed_missing_resource_fails_safely(tmp_path: Path) -> None:
    commands = tmp_path / "commands.json"
    audit = tmp_path / "audit.jsonl"
    seeded = seed_command_library_if_missing(
        str(commands), str(audit), seed_path=str(tmp_path / "nonexistent.json")
    )
    assert seeded is False
    assert not commands.exists()  # no partial write — library stays empty, error logged


def test_seed_resource_is_packaged_and_readable() -> None:
    """The seed ships as a package resource so the gateway can read it via
    importlib.resources on first start (wheel include covers the .json)."""
    import importlib.resources

    with importlib.resources.as_file(
        importlib.resources.files("robot_ai.library") / "seed_query_table.json"
    ) as seed_path:
        data = json.loads(Path(seed_path).read_text(encoding="utf-8"))
    assert len(data["records"]) == 21
