from __future__ import annotations

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
