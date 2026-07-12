from __future__ import annotations

from robot_ai.library.models import (
    AuditEntry,
    Command,
    CommandStatus,
    Component,
    ParameterField,
    RiskLevel,
    normalize_id,
)


def test_enums_have_expected_values() -> None:
    assert RiskLevel.HIGH.value == "high"
    assert CommandStatus.PUBLISHED.value == "published"
    assert {r.value for r in RiskLevel} == {"low", "medium", "high", "critical"}
    assert {s.value for s in CommandStatus} == {"draft", "published", "archived"}


def test_command_round_trip_preserves_fields() -> None:
    cmd = Command(
        id="io0-off",
        name="IO0关闭",
        component_id="io_write",
        parameters={"io_no": 0, "io_action": 0},
        aliases=["IO0", "关闭"],
        description="set Y0 off",
        risk_level="high",
        status="published",
        version=1,
        source="legacy-import",
        created_by="system:migration",
    )
    restored = Command.from_dict(cmd.to_dict())
    assert restored == cmd


def test_command_defaults_version_one_and_published() -> None:
    cmd = Command(id="x", name="X", component_id="delay")
    assert cmd.version == 1
    assert cmd.status == "published"
    assert cmd.risk_level == "high"


def test_component_round_trip_with_parameter_fields() -> None:
    comp = Component(
        id="delay",
        func_num=110,
        name="延时",
        parameters=[ParameterField(name="delay_sec", type="float", unit="sec", minimum=0)],
        flow_eligible=True,
    )
    restored = Component.from_dict(comp.to_dict())
    assert restored == comp
    assert restored.parameters[0].name == "delay_sec"
    assert restored.parameters[0].required is True


def test_audit_entry_round_trip_with_migration_id() -> None:
    entry = AuditEntry(
        action="legacy_import",
        actor="system:migration",
        timestamp="2026-07-11T00:00:00",
        migration_id="legacy-import:abcd",
        after={"migrated": 16, "skipped": 5},
    )
    restored = AuditEntry.from_dict(entry.to_dict())
    assert restored.migration_id == "legacy-import:abcd"
    assert restored.after == {"migrated": 16, "skipped": 5}


def test_normalize_id_lowercases_and_collapses_whitespace() -> None:
    assert normalize_id("IO0关闭") == "io0关闭"
    assert normalize_id("  a   b ") == "a-b"
    assert normalize_id("Home") == "home"
