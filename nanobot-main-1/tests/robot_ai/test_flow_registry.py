from __future__ import annotations

import json
from pathlib import Path

from robot_ai.flow import FlowEntry, FlowRegistry, FlowState, FlowStep


def _entry(name: str = "PickPlace", func_id: int = 108) -> FlowEntry:
    return FlowEntry(
        name=name,
        steps=[FlowStep(step_id=1, action="move", func_id=func_id, params={"seconds": 1})],
    )


def test_add_get_list_case_insensitive(tmp_path: Path) -> None:
    registry = FlowRegistry(tmp_path / "flows.json")
    ok, _ = registry.add(_entry("PickPlace"))
    assert ok is True

    assert registry.get("pickplace") is not None  # case-insensitive
    assert registry.get("PickPlace").name == "PickPlace"
    assert registry.get("missing") is None
    names = [flow.name for flow in registry.list_all()]
    assert names == ["PickPlace"]


def test_add_rejects_empty_name_and_duplicates(tmp_path: Path) -> None:
    registry = FlowRegistry(tmp_path / "flows.json")
    assert registry.add(FlowEntry(name="   "))[0] is False
    assert registry.add(_entry("PickPlace"))[0] is True
    assert registry.add(_entry("pickplace"))[0] is False  # duplicate (case-insensitive)


def test_remove(tmp_path: Path) -> None:
    registry = FlowRegistry(tmp_path / "flows.json")
    registry.add(_entry("PickPlace"))
    assert registry.remove("pickplace")[0] is True
    assert registry.get("PickPlace") is None
    assert registry.remove("PickPlace")[0] is False


def test_confirm_sets_ready_state(tmp_path: Path) -> None:
    registry = FlowRegistry(tmp_path / "flows.json")
    registry.add(_entry("PickPlace"))
    ok, _ = registry.confirm("PickPlace")
    assert ok is True
    flow = registry.get("PickPlace")
    assert flow.confirmed is True
    assert flow.state == FlowState.READY.value


def test_confirmed_flow_requires_draft_to_edit(tmp_path: Path) -> None:
    registry = FlowRegistry(tmp_path / "flows.json")
    registry.add(_entry("PickPlace"))
    registry.confirm("PickPlace")

    # Direct edit of a confirmed flow is rejected.
    ok, _ = registry.update("PickPlace", description="new")
    assert ok is False

    # Draft edit bumps the version and un-confirms.
    ok, _ = registry.update("PickPlace", create_draft=True, description="new")
    assert ok is True
    flow = registry.get("PickPlace")
    assert flow.version == 2
    assert flow.confirmed is False
    assert flow.description == "new"


def test_transition_respects_state_machine(tmp_path: Path) -> None:
    registry = FlowRegistry(tmp_path / "flows.json")
    registry.add(_entry("PickPlace"))
    assert registry.transition("PickPlace", FlowState.RUNNING) is False  # IDLE -> RUNNING invalid
    assert registry.transition("PickPlace", FlowState.READY) is True
    assert registry.get("PickPlace").state == FlowState.READY.value


def test_registry_persists_and_reloads(tmp_path: Path) -> None:
    path = tmp_path / "flows.json"
    registry = FlowRegistry(path)
    registry.add(_entry("PickPlace"))
    registry.add(_entry("AppendLoop"))

    # File written with version header and both flows.
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == "1.1"
    names = [flow["name"] for flow in payload["flows"]]
    assert names == ["AppendLoop", "PickPlace"]  # sorted

    # A fresh registry reloads from disk.
    reloaded = FlowRegistry(path)
    assert [flow.name for flow in reloaded.list_all()] == ["AppendLoop", "PickPlace"]


def test_update_replaces_steps_with_flowstep_objects(tmp_path: Path) -> None:
    registry = FlowRegistry(tmp_path / "flows.json")
    registry.add(_entry("PickPlace"))
    ok, _ = registry.update(
        "PickPlace",
        steps=[{"step_id": 1, "action": "delay", "func_id": 110, "params": {"seconds": 2}}],
    )
    assert ok is True
    flow = registry.get("PickPlace")
    assert isinstance(flow.steps[0], FlowStep)
    assert flow.steps[0].func_id == 110
