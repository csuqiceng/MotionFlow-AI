from __future__ import annotations

from robot_ai.library.transfer import apply_transfer_payload, build_transfer_payload, validate_transfer_payload


def test_build_transfer_payload_uses_versioned_schema_without_registry_metadata() -> None:
    payload = build_transfer_payload(
        commands=[{"command_id": "wait", "published_version": 1, "versions": {"1": {"component_id": "delay"}}, "draft": None}],
        flows=[{"flow_id": "wait-flow", "published_version": 1, "versions": {"1": {"steps": []}}, "draft": None}],
    )

    assert payload["schema_version"] == 1
    assert payload["commands"][0]["command_id"] == "wait"
    assert payload["flows"][0]["flow_id"] == "wait-flow"
    assert "pending_audits" not in payload


def test_validate_transfer_payload_rejects_unknown_component_and_duplicate_ids() -> None:
    payload = {
        "schema_version": 1,
        "commands": [
            {"command_id": "one", "draft": {"component_id": "missing"}, "versions": {}},
            {"command_id": "one", "draft": {"component_id": "delay"}, "versions": {}},
        ],
        "flows": [],
    }

    errors = validate_transfer_payload(payload, component_ids={"delay"})

    assert "commands[0].draft.component_id is unknown: missing" in errors
    assert "commands[1].command_id duplicates commands[0].command_id: one" in errors


def test_apply_transfer_renames_conflicting_draft_without_overwriting_published(tmp_path) -> None:
    from robot_ai.flow.versioned_registry import VersionedFlowRegistry
    from robot_ai.library.versioned_registry import VersionedCommandRegistry

    commands = VersionedCommandRegistry(tmp_path / "commands.json", audit_path=tmp_path / "audit.jsonl")
    commands.create_entity("wait", "delay", "Wait", {"ms": 100})
    commands.publish("wait", component_risk_level="low")
    flows = VersionedFlowRegistry(tmp_path / "flows.json", audit_path=tmp_path / "audit.jsonl")
    payload = {"schema_version": 1, "commands": [{
        "command_id": "wait", "published_version": None, "versions": {},
        "draft": {"name": "Wait copy", "component_id": "delay", "parameters": {"ms": 200}},
    }], "flows": []}

    result = apply_transfer_payload(payload, command_registry=commands, flow_registry=flows, component_ids={"delay"}, strategy="rename")

    assert result["errors"] == []
    assert result["commands"]["imported"] == ["wait-2"]
    assert commands.get_entity("wait")["published_version"] == 1
    assert commands.get_entity("wait-2")["draft"]["name"] == "Wait copy"
