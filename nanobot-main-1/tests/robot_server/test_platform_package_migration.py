from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_platform_implementation_is_physical_and_legacy_package_is_only_alias() -> None:
    assert (ROOT / "robot_platform" / "platform.py").is_file()
    legacy_files = [path.name for path in (ROOT / "robot_ai").glob("*.py")]
    assert legacy_files == ["__init__.py"]


def test_legacy_and_canonical_imports_share_the_same_module() -> None:
    import robot_ai.runtime as legacy_runtime
    import robot_platform.runtime as platform_runtime

    assert legacy_runtime is platform_runtime
