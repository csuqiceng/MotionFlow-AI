from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

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
