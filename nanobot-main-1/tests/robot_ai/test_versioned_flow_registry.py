from __future__ import annotations

import json
from pathlib import Path

import pytest

from robot_ai.flow.versioned_registry import VersionedFlowRegistry
from robot_ai.library.versioned_registry import ConflictError


def _steps() -> list[dict[str, object]]:
    return [{"step_id": 1, "action": "move", "func_id": 108, "spd_pct": 50, "params": {}}]


def _reg(tmp_path: Path) -> VersionedFlowRegistry:
    return VersionedFlowRegistry(tmp_path / "flows.json", audit_path=tmp_path / "audit.jsonl")


def test_create_entity_persists_schema_draft_and_audit(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    entity = reg.create_entity("home", "Home", _steps())

    assert entity["flow_id"] == "home"
    assert entity["published_version"] is None
    assert entity["draft"]["revision"] == 1
    assert entity["draft"]["steps"] == _steps()
    payload = json.loads((tmp_path / "flows.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == "2.0"
    assert payload["pending_audits"] == []
    assert json.loads((tmp_path / "audit.jsonl").read_text(encoding="utf-8"))["action"] == "flow_create"


def test_drain_pending_audits_recovers_after_audit_write_failure(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    reg.audit_path = blocker / "audit.jsonl"
    reg.create_entity("home", "Home", _steps())

    assert len(reg._data["pending_audits"]) == 1
    reg.audit_path = tmp_path / "audit.jsonl"
    assert len(reg.drain_pending_audits()) == 1
    assert reg._data["pending_audits"] == []


def test_update_draft_uses_revision_and_rejects_stale_write(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("home", "Home", _steps())

    reg.update_draft("home", expected_revision=1, name="Home v2", steps=_steps(), step_delay_ms=0,
                     rehearsal_spd=20, description="updated")
    draft = reg.get_entity("home")["draft"]
    assert draft["revision"] == 2
    assert draft["name"] == "Home v2"
    with pytest.raises(ConflictError) as caught:
        reg.update_draft("home", expected_revision=1, name="stale", steps=_steps(), step_delay_ms=0,
                         rehearsal_spd=20)
    assert caught.value.current_revision == 2


def test_validate_draft_requires_name_steps_unique_ids_finite_delay_and_positive_speed(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("home", "Home", _steps())

    assert reg.validate_draft("home") == []
    invalid = [
        ("", _steps(), 0, 20, "name"),
        ("Home", [], 0, 20, "step"),
        ("Home", _steps() * 2, 0, 20, "unique"),
        ("Home", _steps(), float("inf"), 20, "finite"),
        ("Home", _steps(), -1, 20, "nonnegative"),
        ("Home", _steps(), 0, 0, "positive"),
    ]
    for name, steps, delay, speed, expected in invalid:
        reg.update_draft("home", expected_revision=reg.get_entity("home")["draft"]["revision"], name=name,
                         steps=steps, step_delay_ms=delay, rehearsal_spd=speed)
        assert any(expected in error.lower() for error in reg.validate_draft("home"))


@pytest.mark.parametrize(
    ("steps", "expected"),
    [
        (["not-a-step"], "mapping"),
        ([{}], "step_id"),
        ([{"step_id": []}], "step_id"),
    ],
)
def test_validate_draft_rejects_malformed_step_shapes_without_type_error(
    tmp_path: Path, steps: list[object], expected: str
) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("home", "Home", _steps())
    reg.update_draft("home", expected_revision=1, name="Home", steps=steps, step_delay_ms=0,
                     rehearsal_spd=20)

    errors = reg.validate_draft("home")
    assert any(expected in error.lower() for error in errors)
    with pytest.raises(ValueError, match=expected):
        reg.publish("home")


def test_drain_pending_audits_tolerates_audit_path_directory(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    audit_directory = tmp_path / "audit-dir"
    audit_directory.mkdir()
    reg.audit_path = audit_directory

    reg.create_entity("home", "Home", _steps())

    assert reg.get_entity("home") is not None
    assert len(reg._data["pending_audits"]) == 1
    assert len(json.loads((tmp_path / "flows.json").read_text(encoding="utf-8"))["pending_audits"]) == 1


def test_publish_makes_immutable_version_and_start_draft_copies_it(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("home", "Home", _steps())
    reg.publish("home")
    published = reg.get_entity("home")["versions"]["1"]

    assert published["status"] == "published"
    assert reg.get_entity("home")["draft"] is None
    reg.start_draft("home")
    changed_steps = [{**_steps()[0], "spd_pct": 75}]
    reg.update_draft("home", expected_revision=1, name="Home v2", steps=changed_steps, step_delay_ms=5,
                     rehearsal_spd=30)
    reg.publish("home")
    assert reg.get_entity("home")["versions"]["1"]["steps"] == _steps()
    assert reg.get_entity("home")["versions"]["2"]["steps"] == changed_steps


def test_publish_rejects_invalid_draft_and_archive_only_allows_unpublished(tmp_path: Path) -> None:
    reg = _reg(tmp_path)
    reg.create_entity("bad", "", _steps())
    with pytest.raises(ValueError, match="name"):
        reg.publish("bad")
    reg.archive("bad")
    assert reg.get_entity("bad") is None

    reg.create_entity("home", "Home", _steps())
    reg.publish("home")
    with pytest.raises(ConflictError):
        reg.archive("home")
