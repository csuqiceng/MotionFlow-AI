"""Import boundary for the reusable robot platform core."""

from pathlib import Path
import re


_FORBIDDEN = re.compile(r"^\s*(?:from\s+nanobot(?:\.|\s)|import\s+nanobot(?:\.|\s|$))", re.MULTILINE)


def test_robot_ai_does_not_import_nanobot() -> None:
    package_root = Path(__file__).parents[2] / "robot_ai"
    violations = [
        str(path.relative_to(package_root))
        for path in package_root.rglob("*.py")
        if _FORBIDDEN.search(path.read_text(encoding="utf-8"))
    ]

    assert violations == [], f"robot_ai must remain host-independent: {violations}"
