from __future__ import annotations

import json
from pathlib import Path

from robot_ai.library.models import Command
from robot_ai.library.registry import CommandRegistry


def _cmd(cid: str = "io0-off", name: str = "IO0关闭", aliases: list[str] | None = None) -> Command:
    return Command(id=cid, name=name, component_id="io_write", aliases=aliases or [])


def test_add_get_list(tmp_path: Path) -> None:
    reg = CommandRegistry(tmp_path / "commands.json")
    ok, _ = reg.add(_cmd("io0-off", "IO0关闭", ["IO0"]))
    assert ok is True
    assert reg.get("io0-off").name == "IO0关闭"
    assert reg.get("missing") is None
    assert [c.id for c in reg.list_all()] == ["io0-off"]


def test_add_rejects_duplicate_id(tmp_path: Path) -> None:
    reg = CommandRegistry(tmp_path / "commands.json")
    assert reg.add(_cmd("io0-off", "IO0关闭"))[0] is True
    assert reg.add(_cmd("io0-off", "Other"))[0] is False


def test_add_rejects_name_conflicting_with_existing_alias(tmp_path: Path) -> None:
    reg = CommandRegistry(tmp_path / "commands.json")
    reg.add(_cmd("a", "Alpha", aliases=["al"]))
    # "al" is an alias of Alpha; a new command named "al" must be rejected.
    assert reg.add(_cmd("b", "al"))[0] is False


def test_add_rejects_alias_conflicting_with_existing_name(tmp_path: Path) -> None:
    reg = CommandRegistry(tmp_path / "commands.json")
    reg.add(_cmd("a", "Alpha"))
    # "alpha" collides with the existing command name (case-insensitive).
    assert reg.add(_cmd("b", "Bravo", aliases=["alpha"]))[0] is False


def test_add_rejects_alias_conflicting_with_existing_alias(tmp_path: Path) -> None:
    reg = CommandRegistry(tmp_path / "commands.json")
    reg.add(_cmd("a", "Alpha", aliases=["shared"]))
    assert reg.add(_cmd("b", "Bravo", aliases=["shared"]))[0] is False


def test_persists_and_reloads(tmp_path: Path) -> None:
    path = tmp_path / "commands.json"
    reg = CommandRegistry(path)
    reg.add(_cmd("io0-off", "IO0关闭"))
    reg.add(_cmd("home", "home"))

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == "1.0"
    assert [c["id"] for c in payload["commands"]] == ["home", "io0-off"]  # sorted

    reloaded = CommandRegistry(path)
    assert [c.id for c in reloaded.list_all()] == ["home", "io0-off"]


def test_idempotent_add_does_not_duplicate_or_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "commands.json"
    reg = CommandRegistry(path)
    reg.add(_cmd("io0-off", "IO0关闭", ["IO0"]))
    before = path.read_text(encoding="utf-8")

    # Re-adding the same id is rejected (no-op for migration to skip on).
    assert reg.add(_cmd("io0-off", "Overwrite"))[0] is False
    assert path.read_text(encoding="utf-8") == before  # file unchanged


def test_list_filters(tmp_path: Path) -> None:
    reg = CommandRegistry(tmp_path / "commands.json")
    reg.add(_cmd("io0-off", "IO0关闭", aliases=["grip"]))
    reg.add(Command(id="home", name="home", component_id="linear_move", aliases=["回零"]))
    io_only = reg.list(component_id="io_write")
    assert [c.id for c in io_only] == ["io0-off"]
    by_q = reg.list(q="回零")
    assert [c.id for c in by_q] == ["home"]
    assert reg.list(q="grip")[0].id == "io0-off"
