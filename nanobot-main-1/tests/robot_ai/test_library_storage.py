from __future__ import annotations

import json
from pathlib import Path

from robot_ai.library.storage import atomic_write_json


def test_atomic_write_json_creates_and_reads_back(tmp_path: Path) -> None:
    target = tmp_path / "out.json"
    atomic_write_json(target, {"version": "1.0", "items": [1, 2, 3]})
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload == {"version": "1.0", "items": [1, 2, 3]}


def test_atomic_write_json_overwrites_existing(tmp_path: Path) -> None:
    target = tmp_path / "out.json"
    atomic_write_json(target, {"v": 1})
    atomic_write_json(target, {"v": 2})
    assert json.loads(target.read_text(encoding="utf-8")) == {"v": 2}


def test_atomic_write_json_leaves_no_temp_files(tmp_path: Path) -> None:
    target = tmp_path / "out.json"
    atomic_write_json(target, {"x": True})
    leftover = [p.name for p in tmp_path.iterdir() if p.name.startswith(".out.json")]
    assert leftover == []


def test_atomic_write_json_creates_parent_dirs(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "deep" / "out.json"
    atomic_write_json(target, {"ok": True})
    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True}
