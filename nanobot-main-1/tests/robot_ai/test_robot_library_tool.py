from __future__ import annotations

import asyncio
import json

from nanobot.agent.tools.robot_library import RobotLibraryTool
from robot_platform.adapters import FileRobotPositionLibraryAdapter
from robot_platform.application import (
    InMemoryLibraryConfirmationStore,
    RobotLibraryApplicationService,
)
from ai_runtime.identity import bind_verified_principal, issue_verified_principal


def _identity(role: str, actor_id: str):
    return bind_verified_principal(issue_verified_principal(
        actor_id=actor_id, role=role,
        session_id=f"test:{actor_id}", auth_source="test",
    ))


def _run(tool: RobotLibraryTool, **kwargs):
    return json.loads(asyncio.run(tool.execute(**kwargs)))


def _tool(data_dir) -> RobotLibraryTool:
    return RobotLibraryTool(library_application=RobotLibraryApplicationService(
        FileRobotPositionLibraryAdapter(data_dir),
        InMemoryLibraryConfirmationStore(),
    ))


def test_operator_must_confirm_before_a_new_position_is_persisted(tmp_path) -> None:
    tool = _tool(tmp_path)
    with _identity("operator", "user-1"):
        preview = _run(tool, action="preview_save", resource_type="position", name="位置A", pose={"x": 1, "y": 2, "z": 3, "rx": 0, "ry": 0, "rz": 0})
        assert preview["ok"] is True
        assert not (tmp_path / "positions.json").exists()
        saved = _run(tool, action="confirm_save", confirmation_token=preview["data"]["confirmation_token"])
    assert saved["ok"] is True
    assert saved["data"]["resource_type"] == "position"
    assert "位置A" in (tmp_path / "positions.json").read_text(encoding="utf-8")


def test_confirmation_cannot_be_reused_by_another_actor(tmp_path) -> None:
    tool = _tool(tmp_path)
    with _identity("operator", "user-1"):
        preview = _run(tool, action="preview_save", resource_type="position", name="位置A", pose={"x": 1, "y": 2, "z": 3, "rx": 0, "ry": 0, "rz": 0})
    with _identity("operator", "user-2"):
        denied = _run(tool, action="confirm_save", confirmation_token=preview["data"]["confirmation_token"])
    assert denied["ok"] is False
    assert denied["state"] == "library_confirmation_forbidden"


def test_saved_chat_flow_keeps_the_versioned_registry_schema(tmp_path) -> None:
    tool = _tool(tmp_path)
    with _identity("operator", "user-1"):
        preview = _run(tool, action="preview_save", resource_type="flow", name="搬运", steps=[{"step_id": 1, "func_id": 110, "params": {"delay_sec": 1}}])
        saved = _run(tool, action="confirm_save", confirmation_token=preview["data"]["confirmation_token"])
    assert saved["ok"] is True
    payload = json.loads((tmp_path / "flows.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == "2.0"
    assert payload["flows"]["搬运"]["published_version"] == 1


def test_only_engineer_can_confirm_position_update_or_delete(tmp_path) -> None:
    tool = _tool(tmp_path)
    with _identity("operator", "user-1"):
        created = _run(
            tool,
            action="preview_save",
            resource_type="position",
            name="位置A",
            pose={"x": 1, "y": 2, "z": 3, "rx": 0, "ry": 0, "rz": 0},
        )
        _run(tool, action="confirm_save", confirmation_token=created["data"]["confirmation_token"])
        denied = _run(
            tool,
            action="preview_update",
            resource_type="position",
            name="位置A",
            pose={"x": 9, "y": 8, "z": 7, "rx": 0, "ry": 0, "rz": 0},
        )
    assert denied["state"] == "library_forbidden"

    with _identity("engineer", "user-1"):
        updated_preview = _run(
            tool,
            action="preview_update",
            resource_type="position",
            name="位置A",
            pose={"x": 9, "y": 8, "z": 7, "rx": 0, "ry": 0, "rz": 0},
        )
        updated = _run(tool, action="confirm_save", confirmation_token=updated_preview["data"]["confirmation_token"])
        deleted_preview = _run(tool, action="preview_delete", resource_type="position", name="位置A")
        deleted = _run(tool, action="confirm_save", confirmation_token=deleted_preview["data"]["confirmation_token"])
    assert updated["ok"] is True
    assert updated["data"]["position"]["pose"] == [9.0, 8.0, 7.0, 0.0, 0.0, 0.0]
    assert deleted["ok"] is True
    assert json.loads((tmp_path / "positions.json").read_text(encoding="utf-8"))["positions"] == []
