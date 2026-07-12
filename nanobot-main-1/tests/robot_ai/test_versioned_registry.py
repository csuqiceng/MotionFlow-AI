from __future__ import annotations

import json
from pathlib import Path

from robot_ai.library.versioned_registry import ConflictError, VersionedCommandRegistry


def _reg(tmp_path: Path) -> VersionedCommandRegistry:
    return VersionedCommandRegistry(tmp_path / "commands.json", audit_path=tmp_path / "audit.jsonl")


# -- Task 2: storage + create + get + list --

def test_create_entity_with_draft(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    entity = reg.create_entity("pick-place", "linear_move", "Pick & Place", {"target_x": 100.0})
    assert entity["command_id"] == "pick-place"
    assert entity["published_version"] is None
    assert entity["draft"]["revision"] == 1


def test_get_entity(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("home", "linear_move", "Home", {})
    assert reg.get_entity("home") is not None
    assert reg.get_entity("missing") is None


def test_list_summaries_excludes_version_tree(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("home", "linear_move", "Home", {})
    reg.create_entity("io0-off", "io_write", "IO0 Off", {})
    summaries = reg.list_summaries()
    assert len(summaries) == 2
    assert "versions" not in summaries[0]
    assert "draft" not in summaries[0]


def test_persists_and_reloads(tmp_path: Path) -> None:
    path = tmp_path / "commands.json"
    VersionedCommandRegistry(path, audit_path=tmp_path / "audit.jsonl").create_entity(
        "home", "linear_move", "Home", {})
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "2.0"
    assert "pending_audits" in payload
    assert VersionedCommandRegistry(path, audit_path=tmp_path / "audit.jsonl").get_entity("home") is not None


def test_published_version_null_for_new(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("home", "linear_move", "Home", {})
    assert reg.get_entity("home")["published_version"] is None


# -- _commit_with_audit ordering --

def test_commit_writes_audit_and_drains(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("home", "linear_move", "Home", {})
    lines = [ln for ln in reg.audit_path.read_text("utf-8").splitlines() if ln.strip()]
    assert any(json.loads(ln)["action"] == "command_create" for ln in lines)
    assert reg._data["pending_audits"] == []


def test_commit_drain_failure_keeps_pending(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    reg.audit_path = blocker / "audit.jsonl"
    reg.create_entity("home", "linear_move", "Home", {})
    assert reg.get_entity("home") is not None
    assert len(reg._data["pending_audits"]) == 1
    reg.audit_path = tmp_path / "audit.jsonl"
    assert len(reg.drain_pending_audits()) == 1
    assert reg._data["pending_audits"] == []


def test_commit_crash_recovery_disk_level(tmp_path: Path) -> None:
    path = tmp_path / "commands.json"
    audit = tmp_path / "audit.jsonl"
    reg = VersionedCommandRegistry(path, audit_path=audit)
    reg.create_entity("home", "linear_move", "Home", {})
    last = json.loads(audit.read_text("utf-8").strip().splitlines()[-1])
    reg._data["pending_audits"].append({**last})
    reg._save()
    reg2 = VersionedCommandRegistry(path, audit_path=audit)
    assert len(reg2._data["pending_audits"]) == 1
    assert reg2.drain_pending_audits() == []
    assert reg2._data["pending_audits"] == []
    reg3 = VersionedCommandRegistry(path, audit_path=audit)
    assert reg3._data["pending_audits"] == []
    assert len([ln for ln in audit.read_text("utf-8").splitlines() if ln.strip()]) == 1


def test_commit_drain_failure_persists_to_disk(tmp_path: Path) -> None:
    path = tmp_path / "commands.json"
    audit = tmp_path / "audit.jsonl"
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    VersionedCommandRegistry(path, audit_path=blocker / "audit.jsonl").create_entity(
        "home", "linear_move", "Home", {})
    reg2 = VersionedCommandRegistry(path, audit_path=blocker / "audit.jsonl")
    assert len(reg2._data["pending_audits"]) == 1
    reg2.audit_path = audit
    assert len(reg2.drain_pending_audits()) == 1
    reg3 = VersionedCommandRegistry(path, audit_path=audit)
    assert reg3._data["pending_audits"] == []
    assert len([ln for ln in audit.read_text("utf-8").splitlines() if ln.strip()]) == 1


# -- update_draft (full replacement) --

def test_update_draft_full_replacement(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("home", "linear_move", "Home", {"target_x": 0.0})
    reg.update_draft("home", expected_revision=1, name="Home v2", aliases=["go"],
        description="d", component_id="linear_move", parameters={"target_x": 100.0})
    d = reg.get_entity("home")["draft"]
    assert d["revision"] == 2 and d["name"] == "Home v2" and d["aliases"] == ["go"]


def test_update_draft_stale_revision(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("home", "linear_move", "Home", {})
    try:
        reg.update_draft("home", expected_revision=99, name="X", aliases=[],
            description="", component_id="linear_move", parameters={})
        assert False
    except ConflictError as e:
        assert e.current_revision == 1


def test_update_draft_missing_field_rejected(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("home", "linear_move", "Home", {})
    try:
        reg.update_draft("home", expected_revision=1, name="X")
        assert False
    except TypeError:
        pass


# -- start_draft --

def test_start_draft_from_published(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("home", "linear_move", "Home", {"target_x": 100.0})
    reg.publish("home", component_risk_level="high")
    reg.start_draft("home")
    d = reg.get_entity("home")["draft"]
    assert d["base_version"] == 1 and d["parameters"]["target_x"] == 100.0


def test_start_draft_already_exists(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("home", "linear_move", "Home", {})
    try:
        reg.start_draft("home")
        assert False
    except ValueError:
        pass


# -- publish (immutable + id + self-exclusion) --

def test_publish_immutable_with_id(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("home", "linear_move", "Home", {})
    reg.publish("home", component_risk_level="high")
    v1 = reg.get_entity("home")["versions"]["1"]
    assert v1["status"] == "published" and v1["id"] == "home" and v1["risk_level"] == "high"
    assert reg.get_entity("home")["draft"] is None


def test_publish_v2_v1_immutable(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("home", "linear_move", "Home", {"target_x": 100.0})
    reg.publish("home", component_risk_level="high")
    reg.start_draft("home")
    reg.update_draft("home", expected_revision=1, name="Home", aliases=[],
        description="", component_id="linear_move", parameters={"target_x": 200.0})
    reg.publish("home", component_risk_level="high")
    e = reg.get_entity("home")
    assert e["versions"]["1"]["parameters"]["target_x"] == 100.0
    assert e["versions"]["2"]["parameters"]["target_x"] == 200.0
    assert e["versions"]["2"]["id"] == "home"


def test_publish_self_namespace_ok(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("home", "linear_move", "Home", {})
    reg.publish("home", component_risk_level="high")
    reg.start_draft("home")
    reg.publish("home", component_risk_level="high")
    assert reg.get_entity("home")["published_version"] == 2


# -- namespace conflict matrix --

def _assert_conflict(reg, cid: str) -> None:
    try:
        reg.publish(cid, component_risk_level="high")
        assert False, "Should conflict"
    except ValueError:
        pass


def test_ns_name_vs_name(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("a", "linear_move", "Home", {})
    reg.publish("a", component_risk_level="high")
    reg.create_entity("b", "linear_move", "Home", {})
    _assert_conflict(reg, "b")


def test_ns_name_vs_alias(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("a", "linear_move", "Alpha", {}, aliases=["gohome"])
    reg.publish("a", component_risk_level="high")
    reg.create_entity("b", "linear_move", "GoHome", {})
    _assert_conflict(reg, "b")


def test_ns_alias_vs_name(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("a", "linear_move", "Rest", {})
    reg.publish("a", component_risk_level="high")
    reg.create_entity("b", "io_write", "Other", {}, aliases=["rest"])
    _assert_conflict(reg, "b")


def test_ns_alias_vs_alias(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("a", "linear_move", "Alpha", {}, aliases=["stop"])
    reg.publish("a", component_risk_level="high")
    reg.create_entity("b", "io_write", "Bravo", {}, aliases=["stop"])
    _assert_conflict(reg, "b")


def test_ns_empty_name_rejected(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("a", "linear_move", "", {})
    try:
        reg.publish("a", component_risk_level="high")
        assert False
    except ValueError as e:
        assert "empty" in str(e).lower()


def test_ns_whitespace_evasion(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("a", "linear_move", "Home", {})
    reg.publish("a", component_risk_level="high")
    reg.create_entity("b", "io_write", "Other", {}, aliases=[" home "])
    _assert_conflict(reg, "b")


def test_ns_within_draft_alias_dup(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("a", "linear_move", "Alpha", {}, aliases=["x", "x"])
    try:
        reg.publish("a", component_risk_level="high")
        assert False
    except ValueError:
        pass


def test_ns_within_draft_alias_equals_name(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("a", "linear_move", "Home", {}, aliases=["Home"])
    try:
        reg.publish("a", component_risk_level="high")
        assert False
    except ValueError:
        pass


def test_blank_aliases_stripped_on_create(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("a", "linear_move", "Alpha", {}, aliases=["valid", "", "  "])
    assert reg.get_entity("a")["draft"]["aliases"] == ["valid"]


# -- archive (draft-only) --

def test_archive_draft_only(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("home", "linear_move", "Home", {})
    reg.archive("home")
    assert reg.get_entity("home") is None
    reg.create_entity("io", "io_write", "IO", {})
    reg.publish("io", component_risk_level="medium")
    try:
        reg.archive("io")
        assert False
    except ConflictError:
        pass


# -- all state changes audited via outbox --

def test_all_state_changes_audited(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("home", "linear_move", "Home", {})
    reg.publish("home", component_risk_level="high")
    reg.start_draft("home")
    reg.update_draft("home", expected_revision=1, name="Home v2", aliases=[],
        description="", component_id="linear_move", parameters={})
    reg.publish("home", component_risk_level="high")
    reg.create_entity("tmp", "delay", "Temp", {})
    reg.archive("tmp")
    actions = [json.loads(ln)["action"]
               for ln in reg.audit_path.read_text("utf-8").splitlines() if ln.strip()]
    assert "command_create" in actions
    assert "command_publish" in actions
    assert "draft_start" in actions
    assert "draft_update" in actions
    assert "command_archive" in actions
