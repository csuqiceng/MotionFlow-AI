from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

AXIS_NAMES = ("x", "y", "z", "rx", "ry", "rz")


@dataclass(frozen=True)
class NamedPosition:
    name: str
    pose: list[float]
    spd: float = 50.0
    move_type: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "NamedPosition":
        return cls(
            name=str(d.get("name", "")),
            pose=[float(v) for v in d.get("pose", [])][:6],
            spd=float(d.get("spd", d.get("speed_pct", 50))),
            move_type=int(d.get("move_type", 0)),
        )


class PositionRegistry:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._positions: dict[str, NamedPosition] = {}
        self._load()

    @staticmethod
    def _key(name: str) -> str:
        return str(name or "").strip().lower()

    def _load(self) -> None:
        if not self.path.exists():
            return
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        for item in payload.get("positions", []):
            np = NamedPosition.from_dict(item)
            if np.name:
                self._positions[self._key(np.name)] = np

    def get(self, name: str) -> NamedPosition | None:
        return self._positions.get(self._key(name))

    def list_all(self) -> list[NamedPosition]:
        return sorted(self._positions.values(), key=lambda n: n.name)

    def resolve(self, name: str) -> dict[str, float] | None:
        np = self.get(name)
        if np is None:
            return None
        return {
            axis: float(np.pose[i]) if i < len(np.pose) else 0.0
            for i, axis in enumerate(AXIS_NAMES)
        }

    def register(
        self,
        position: NamedPosition,
        *,
        persistence: Literal["persistent", "temporary"] = "persistent",
    ) -> NamedPosition:
        if persistence not in {"persistent", "temporary"}:
            raise ValueError(
                "persistence must be either 'persistent' or 'temporary'"
            )
        if not position.name.strip():
            raise ValueError("position name must not be empty")
        if persistence == "temporary":
            return position

        positions = dict(self._positions)
        positions[self._key(position.name)] = position
        self._write_positions_atomically(positions)
        self._positions = positions
        return position

    def remove(self, name: str) -> bool:
        """Remove a persistent position and return whether it existed."""
        key = self._key(name)
        if key not in self._positions:
            return False
        positions = dict(self._positions)
        del positions[key]
        self._write_positions_atomically(positions)
        self._positions = positions
        return True

    def _write_positions_atomically(
        self, positions: dict[str, NamedPosition]
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_path = tempfile.mkstemp(
            dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp"
        )
        temporary = Path(temporary_path)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "version": "1.0",
                        "positions": [
                            np.to_dict()
                            for np in sorted(
                                positions.values(), key=lambda np: np.name
                            )
                        ],
                    },
                    handle,
                    ensure_ascii=False,
                    indent=2,
                )
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def replace(self, positions: list[NamedPosition]) -> None:
        self._positions = {self._key(np.name): np for np in positions if np.name}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "positions": [np.to_dict() for np in self.list_all()],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
