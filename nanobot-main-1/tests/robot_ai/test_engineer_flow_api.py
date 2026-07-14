from __future__ import annotations

from pathlib import Path

from nanobot.api.robot_routes import (
    process_engineer_create_flow,
    process_engineer_publish_flow,
    process_engineer_start_flow_draft,
    process_engineer_update_flow_draft,
    process_engineer_validate_flow_draft,
    process_robot_library_flow,
    process_robot_library_flows,
)
from robot_ai.library.auth import UserSessionStore


def _flow_body() -> dict[str, object]:
    return {
        "name": "Pick Place",
        "description": "Move a part safely.",
        "steps": [{"step_id": "approach", "action": "move", "params": {}}],
        "step_delay_ms": 100,
        "rehearsal_spd": 20,
    }


def _engineer_context(tmp_path: Path) -> dict[str, object]:
    store = UserSessionStore()
    token = store.issue({"user_id": "eng-1", "username": "engineer", "role": "engineer"})
    return {
        "flows_path": str(tmp_path / "flows.json"),
        "audit_path": str(tmp_path / "audit.jsonl"),
        "token_store": store,
        "engineer_token": token,
    }


def test_engineer_can_create_validate_and_publish_flow(tmp_path: Path) -> None:
    context = _engineer_context(tmp_path)

    status, body = process_engineer_create_flow(_flow_body(), **context)
    assert status == 201
    assert body["data"]["flow_id"] == "pick_place"

    status, validation = process_engineer_validate_flow_draft("pick_place", **context)
    assert status == 200
    assert validation["data"]["errors"] == []

    status, published = process_engineer_publish_flow("pick_place", **context)
    assert status == 200
    assert published["data"]["published_version"] == 1
    assert published["data"]["draft"] is None


def test_flow_draft_update_returns_409_with_current_revision(tmp_path: Path) -> None:
    context = _engineer_context(tmp_path)
    status, created = process_engineer_create_flow(_flow_body(), **context)
    assert status == 201
    flow_id = created["data"]["flow_id"]

    update = _flow_body() | {"expected_revision": 1, "name": "Pick Place v2"}
    status, updated = process_engineer_update_flow_draft(flow_id, update, **context)
    assert status == 200
    assert updated["data"]["draft"]["revision"] == 2

    status, conflict = process_engineer_update_flow_draft(flow_id, update, **context)
    assert status == 409
    assert conflict["data"]["current_revision"] == 2
    assert conflict["error"]["code"] == "draft_conflict"


def test_only_engineers_can_manage_flows_and_published_flow_can_start_draft(tmp_path: Path) -> None:
    context = _engineer_context(tmp_path)
    status, created = process_engineer_create_flow(_flow_body(), **context)
    assert status == 201
    flow_id = created["data"]["flow_id"]
    assert process_engineer_publish_flow(flow_id, **context)[0] == 200
    assert process_engineer_start_flow_draft(flow_id, **context)[0] == 201

    store = context["token_store"]
    operator_token = store.issue({"user_id": "op-1", "username": "operator", "role": "operator"})
    status, denied = process_engineer_create_flow(
        _flow_body(),
        flows_path=context["flows_path"],
        audit_path=context["audit_path"],
        token_store=store,
        engineer_token=operator_token,
    )
    assert status == 403
    assert denied["error"]["code"] == "forbidden"


def test_publish_missing_flow_or_draft_returns_404(tmp_path: Path) -> None:
    context = _engineer_context(tmp_path)

    status, missing = process_engineer_publish_flow("missing", **context)
    assert status == 404
    assert missing["error"]["code"] == "no_draft"

    assert process_engineer_create_flow(_flow_body(), **context)[0] == 201
    assert process_engineer_publish_flow("pick_place", **context)[0] == 200
    status, no_draft = process_engineer_publish_flow("pick_place", **context)
    assert status == 404
    assert no_draft["error"]["code"] == "no_draft"


def test_published_engineer_flow_projects_canonical_id_to_read_only_library(tmp_path: Path) -> None:
    context = _engineer_context(tmp_path)
    assert process_engineer_create_flow(_flow_body(), **context)[0] == 201
    assert process_engineer_publish_flow("pick_place", **context)[0] == 200

    status, listed = process_robot_library_flows(flow_registry_path=context["flows_path"])
    assert status == 200
    assert listed["data"]["items"] == [
        {**listed["data"]["items"][0], "flow_id": "pick_place", "name": "Pick Place"}
    ]
    status, detail = process_robot_library_flow("pick_place", flow_registry_path=context["flows_path"])
    assert status == 200
    assert detail["data"]["flow_id"] == "pick_place"
