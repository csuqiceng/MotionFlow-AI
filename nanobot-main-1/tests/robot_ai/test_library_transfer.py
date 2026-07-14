from __future__ import annotations

from robot_ai.library.transfer import build_transfer_payload, validate_transfer_payload


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
