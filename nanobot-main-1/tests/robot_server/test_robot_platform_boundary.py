"""The product server must use the canonical platform boundary."""

import ast
from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_robot_server_imports_only_robot_platform() -> None:
    offenders: list[str] = []
    for source in (ROOT / "robot_server").rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        if any(module == "robot_ai" or module.startswith("robot_ai.") for module in imports):
            offenders.append(source.relative_to(ROOT).as_posix())
    assert offenders == []


def test_canonical_platform_reuses_compatibility_runtime_singletons() -> None:
    from robot_platform import get_robot_data_dir
    from robot_ai.runtime import get_robot_data_dir as compatibility_get_robot_data_dir

    assert get_robot_data_dir is compatibility_get_robot_data_dir
