"""Architecture boundaries that must survive modular migration."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _imports_under(directory: str) -> set[str]:
    imported: set[str] = set()
    for path in (PROJECT_ROOT / directory).rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
    return imported


def test_robot_platform_does_not_depend_on_product_or_agent_layers() -> None:
    imports = _imports_under("robot_platform")
    forbidden_prefixes = ("ai_runtime", "robot_server", "nanobot")

    assert not [
        module
        for module in imports
        if module == forbidden_prefixes or module.startswith(forbidden_prefixes)
    ]


def test_backend_factory_does_not_import_concrete_backends() -> None:
    """The compatibility factory may select a backend, but must not wire vendors."""
    factory_path = PROJECT_ROOT / "robot_platform" / "backends" / "factory.py"
    tree = ast.parse(factory_path.read_text(encoding="utf-8"), filename=str(factory_path))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert not {
        module
        for module in imports
        if module.endswith("simulation_backend") or ".zmotion" in module
    }


def test_runtime_robot_tools_do_not_depend_on_nanobot_tool_runtime() -> None:
    imports = _imports_under("ai_runtime/robot_tools")

    assert not [module for module in imports if module == "nanobot" or module.startswith("nanobot.")]


def test_nanobot_core_does_not_depend_on_product_runtime_or_server() -> None:
    allowed_compatibility_imports = {
        "nanobot/__main__.py": {"robot_server.cli"},
        "nanobot/agent/tools/robot_arm.py": {"ai_runtime.robot_tools"},
        "nanobot/agent/tools/robot_flow.py": {"ai_runtime.robot_tools"},
        "nanobot/agent/tools/robot_knowledge.py": {"ai_runtime.robot_tools"},
        "nanobot/agent/tools/robot_library.py": {"ai_runtime.robot_tools"},
        "nanobot/agent/tools/robot_position.py": {"ai_runtime.robot_tools"},
    }
    forbidden_imports: list[str] = []
    for path in (PROJECT_ROOT / "nanobot").rglob("*.py"):
        relative_path = path.relative_to(PROJECT_ROOT).as_posix()
        allowed = allowed_compatibility_imports.get(relative_path, set())
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            else:
                continue
            for module in modules:
                is_product_import = module == "ai_runtime" or module.startswith("ai_runtime.")
                is_server_import = module == "robot_server" or module.startswith("robot_server.")
                if (is_product_import or is_server_import) and module not in allowed:
                    forbidden_imports.append(f"{relative_path}: {module}")

    assert not forbidden_imports


def test_robot_platform_application_paths_do_not_import_zmotion() -> None:
    paths = (
        PROJECT_ROOT / "robot_platform" / "platform.py",
        PROJECT_ROOT / "robot_platform" / "bridge.py",
        PROJECT_ROOT / "robot_platform" / "flow",
    )
    imports: set[str] = set()
    for path in paths:
        if path.is_file():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module)
        else:
            imports.update(_imports_under(path.relative_to(PROJECT_ROOT).as_posix()))

    assert not [module for module in imports if ".zmotion" in module or module.endswith("zmotion_operator_control")]
