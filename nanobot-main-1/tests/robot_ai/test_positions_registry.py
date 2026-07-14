from __future__ import annotations

import pytest

from robot_ai.positions.registry import NamedPosition, PositionRegistry


def test_load_get_resolve(tmp_path) -> None:
    p = tmp_path / "pos.json"
    PositionRegistry(p).replace(
        [NamedPosition(name="A", pose=[1000.0, 0.0, 800.0, 0.0, 90.0, 0.0], spd=50)]
    )
    reg = PositionRegistry(p)
    assert reg.get("a").name == "A"  # case-insensitive
    assert reg.resolve("A")["x"] == 1000.0
    assert reg.resolve("missing") is None
    assert [n.name for n in reg.list_all()] == ["A"]


def test_unknown_position_returns_none(tmp_path) -> None:
    assert PositionRegistry(tmp_path / "pos.json").resolve("ghost") is None


def test_register_temporary_does_not_change_registry_or_file(tmp_path) -> None:
    p = tmp_path / "pos.json"
    PositionRegistry(p).replace([NamedPosition(name="A", pose=[1.0])])
    reg = PositionRegistry(p)
    source_bytes = p.read_bytes()
    original_positions = reg.list_all()
    temporary = NamedPosition(name="B", pose=[2.0], spd=25.0, move_type=1)

    result = reg.register(temporary, persistence="temporary")

    assert result == temporary
    assert result.to_dict() == {
        "name": "B",
        "pose": [2.0],
        "spd": 25.0,
        "move_type": 1,
    }
    assert p.read_bytes() == source_bytes
    assert reg.list_all() == original_positions
    assert reg.get("B") is None


def test_register_persistent_survives_reload(tmp_path) -> None:
    p = tmp_path / "pos.json"
    position = NamedPosition(name="B", pose=[2.0], spd=25.0, move_type=1)

    assert PositionRegistry(p).register(position) == position

    assert PositionRegistry(p).get("b") == position


def test_register_rejects_invalid_persistence(tmp_path) -> None:
    with pytest.raises(ValueError, match="persistence"):
        PositionRegistry(tmp_path / "pos.json").register(
            NamedPosition(name="B", pose=[2.0]), persistence="session"
        )
