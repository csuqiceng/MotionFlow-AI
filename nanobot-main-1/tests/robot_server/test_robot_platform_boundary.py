"""The product server must use the canonical platform boundary."""

from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_robot_server_imports_only_robot_platform() -> None:
    offenders: list[str] = []
    for source in (ROOT / "robot_server").rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        if "robot_ai" in text:
            offenders.append(source.relative_to(ROOT).as_posix())
    assert offenders == []


def test_canonical_platform_reuses_compatibility_runtime_singletons() -> None:
    from robot_platform import get_robot_data_dir
    from robot_ai.runtime import get_robot_data_dir as compatibility_get_robot_data_dir

    assert get_robot_data_dir is compatibility_get_robot_data_dir
