from __future__ import annotations

from pathlib import Path

from robot_ai.library.versioned_registry import VersionedCommandRegistry


def _seed_2_0(tmp_path: Path) -> Path:
    cpath = tmp_path / "commands.json"
    apath = tmp_path / "audit.jsonl"
    reg = VersionedCommandRegistry(cpath, audit_path=apath)
    reg.create_entity("home", "linear_move", "Home", {"target_x": 0.0})
    reg.publish("home", component_risk_level="high")
    reg.create_entity("io", "io_write", "IO On", {}, aliases=["ioon"])
    reg.publish("io", component_risk_level="medium")
    reg.create_entity("scratch", "delay", "Scratch", {"ms": 1})  # draft-only, NOT published
    return cpath


def test_operator_list_projects_published_version_only(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_robot_library_commands
    s, body = process_robot_library_commands(commands_path=str(_seed_2_0(tmp_path)))
    assert s == 200
    assert {c["id"] for c in body["data"]["items"]} == {"home", "io"}  # scratch hidden
    home = next(c for c in body["data"]["items"] if c["id"] == "home")
    assert home["status"] == "published" and home["version"] == 1


def test_operator_get_single_projects_published_version(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_robot_library_command
    s, body = process_robot_library_command("home", commands_path=str(_seed_2_0(tmp_path)))
    assert s == 200 and body["data"]["id"] == "home" and body["data"]["status"] == "published"


def test_operator_get_draft_only_returns_404(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_robot_library_command
    s, _ = process_robot_library_command("scratch", commands_path=str(_seed_2_0(tmp_path)))
    assert s == 404


def test_operator_list_after_full_b1a_seed_matches_a1(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_robot_library_commands
    from robot_ai.library.migration import initialize_robot_libraries
    cpath = tmp_path / "commands.json"
    apath = tmp_path / "audit.jsonl"
    initialize_robot_libraries(str(cpath), str(apath))  # seed(1.0) -> migrate(2.0)
    s, body = process_robot_library_commands(commands_path=str(cpath))
    assert s == 200 and body["data"]["total"] == 16
