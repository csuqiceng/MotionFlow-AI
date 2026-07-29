"""Architecture boundaries that must survive modular migration."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DYNAMIC_IMPORT_SENTINEL = "<unresolved-dynamic-import>"
CONCRETE_RUNTIME_SYMBOLS = {
    "RobotPlatform",
    "ExecutionPermitStore",
    "ProductEmergencyStopAdapter",
    "BackendManager",
    "create_product_backend_manager",
    "create_product_robot_backend",
    "PendingPlanStore",
    "SessionGateStore",
}
CONCRETE_RUNTIME_TARGETS = {
    "robot_platform.RobotPlatform",
    "robot_platform.platform.RobotPlatform",
    "robot_platform.execution.ExecutionPermitStore",
    "robot_platform.execution.permit.ExecutionPermitStore",
    "robot_platform.backends.emergency_stop.ProductEmergencyStopAdapter",
    "robot_platform.backends.lifecycle.BackendManager",
    (
        "robot_platform.backends.product_wiring."
        "create_product_backend_manager"
    ),
    (
        "robot_platform.backends.product_wiring."
        "create_product_robot_backend"
    ),
    "robot_platform.PendingPlanStore",
    "robot_platform.SessionGateStore",
    "robot_platform.execution.PendingPlanStore",
    "robot_platform.execution.SessionGateStore",
    "robot_platform.execution.pending_plan.PendingPlanStore",
    "robot_platform.execution.session_gate.SessionGateStore",
}
CONCRETE_RUNTIME_EXPOSURE_MODULES = {
    "robot_platform",
    "robot_platform.platform",
    "robot_platform.execution",
    "robot_platform.execution.permit",
    "robot_platform.backends.emergency_stop",
    "robot_platform.backends.lifecycle",
    "robot_platform.backends.product_wiring",
}


def _imports_from_tree(tree: ast.AST) -> set[str]:
    imported: set[str] = set()
    bindings: dict[str, str] = {"__import__": "__import__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
                bindings[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            for alias in node.names:
                bindings[alias.asname or alias.name] = f"{node.module}.{alias.name}"

    def resolve(expression: ast.expr) -> str | None:
        if isinstance(expression, ast.Name):
            return bindings.get(expression.id, expression.id)
        if isinstance(expression, ast.Attribute):
            owner = resolve(expression.value)
            return f"{owner}.{expression.attr}" if owner else expression.attr
        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if resolve(node.func) not in {"importlib.import_module", "__import__"}:
            continue
        if (
            node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            imported.add(node.args[0].value)
        else:
            imported.add(DYNAMIC_IMPORT_SENTINEL)
    return imported


def _imports_under(directory: str) -> set[str]:
    imported: set[str] = set()
    for path in (PROJECT_ROOT / directory).rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported.update(_imports_from_tree(tree))
    return imported


def _imports_by_file(directory: str) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for path in (PROJECT_ROOT / directory).rglob("*.py"):
        modules: set[str] = set()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        modules.update(_imports_from_tree(tree))
        result[path.relative_to(PROJECT_ROOT).as_posix()] = modules
    return result


def _concrete_runtime_references(source: str, *, filename: str = "<source>") -> set[str]:
    """Find concrete composition references despite normal Python aliasing.

    The small binding map follows import aliases and direct alias assignments,
    so ``RP()``, ``module.RobotPlatform()`` and ``Alias = RP; Alias()`` are
    equivalent for this gate. Literal dynamic imports are rejected outright.
    """
    tree = ast.parse(source, filename=filename)
    references: set[str] = set()
    bindings: dict[str, str] = {}

    def resolve(expression: ast.expr) -> str | None:
        if isinstance(expression, ast.Name):
            return bindings.get(expression.id, expression.id)
        if isinstance(expression, ast.Attribute):
            owner = resolve(expression.value)
            return f"{owner}.{expression.attr}" if owner else expression.attr
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                target = f"{node.module}.{alias.name}"
                bindings[alias.asname or alias.name] = target
                if target in CONCRETE_RUNTIME_TARGETS:
                    references.add(target)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bindings[alias.asname or alias.name.split(".")[0]] = alias.name
                if alias.name in CONCRETE_RUNTIME_EXPOSURE_MODULES:
                    references.add(alias.name)

    # Propagate the common ``Alias = ImportedConstructor`` escape hatch.
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            resolved = resolve(node.value)
            # Alias propagation is monotonic. Rebinding ordinary local names
            # from several assignments used to oscillate forever between the
            # resolved values while scanning larger adapter modules.
            if resolved and target.id not in bindings:
                bindings[target.id] = resolved
                changed = True

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            called = resolve(node.func)
            if called in CONCRETE_RUNTIME_TARGETS or (
                called in CONCRETE_RUNTIME_SYMBOLS
            ):
                references.add(called)
            if called in {"importlib.import_module", "__import__"}:
                if (
                    node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                ):
                    module = node.args[0].value
                    if module in CONCRETE_RUNTIME_EXPOSURE_MODULES:
                        references.add(f"dynamic:{module}")
                else:
                    references.add(DYNAMIC_IMPORT_SENTINEL)
    return references


def test_robot_platform_does_not_depend_on_product_or_agent_layers() -> None:
    imports = _imports_under("robot_platform")
    forbidden_prefixes = ("ai_runtime", "robot_server", "nanobot")

    assert not [
        module
        for module in imports
        if module in forbidden_prefixes
        or module.startswith(tuple(f"{prefix}." for prefix in forbidden_prefixes))
    ]


def test_backend_factory_does_not_import_concrete_backends() -> None:
    """The compatibility factory may select a backend, but must not wire vendors."""
    imports = _imports_by_file("robot_platform/backends")[
        "robot_platform/backends/factory.py"
    ]

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
    allowed_unresolved_dynamic_imports = {
        "nanobot/__init__.py",
        "nanobot/agent/tools/loader.py",
        "nanobot/audio/transcription_registry.py",
        "nanobot/audio/tts_registry.py",
        "nanobot/config/schema.py",
        "nanobot/cron/__init__.py",
        "nanobot/providers/__init__.py",
        "nanobot/utils/__init__.py",
    }
    forbidden_imports: list[str] = []
    for path in (PROJECT_ROOT / "nanobot").rglob("*.py"):
        relative_path = path.relative_to(PROJECT_ROOT).as_posix()
        allowed = allowed_compatibility_imports.get(relative_path, set())
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module in _imports_from_tree(tree):
            if (
                module == DYNAMIC_IMPORT_SENTINEL
                and relative_path not in allowed_unresolved_dynamic_imports
            ):
                forbidden_imports.append(f"{relative_path}: {module}")
                continue
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
            imports.update(_imports_from_tree(tree))
        else:
            imports.update(_imports_under(path.relative_to(PROJECT_ROOT).as_posix()))

    assert not [module for module in imports if ".zmotion" in module or module.endswith("zmotion_operator_control")]


def test_application_layer_does_not_depend_on_adapters_or_interfaces() -> None:
    imports = _imports_under("robot_platform/application")
    forbidden = ("robot_platform.backends", "robot_server", "ai_runtime", "nanobot")
    assert not [module for module in imports if module.startswith(forbidden)]


def test_position_and_library_interfaces_do_not_import_concrete_stores() -> None:
    guarded = (
        "ai_runtime/robot_tools/robot_arm.py",
        "ai_runtime/robot_tools/robot_position.py",
        "ai_runtime/robot_tools/robot_library.py",
        "ai_runtime/robot_tools/robot_flow.py",
        "robot_server/library_api.py",
        "robot_server/command_management.py",
        "robot_server/library_transfer.py",
        "robot_server/position_maintenance.py",
        "robot_server/flow_management.py",
    )
    forbidden = (
        "robot_platform.adapters",
        "robot_platform.library",
        "robot_platform.positions",
        "robot_platform.flow.versioned_registry",
    )
    violations: list[str] = []
    for relative in guarded:
        path = PROJECT_ROOT / relative
        imports = _imports_from_tree(ast.parse(
            path.read_text(encoding="utf-8"), filename=str(path),
        ))
        violations.extend(
            f"{relative}: {module}"
            for module in imports
            if module.startswith(forbidden)
        )
    assert not violations


def test_flow_interfaces_do_not_import_platform_or_concrete_flow_stores() -> None:
    guarded = (
        "ai_runtime/robot_tools/robot_flow.py",
        "robot_server/flow_management.py",
        "robot_server/execution_api.py",
        "robot_server/robot_api.py",
    )
    forbidden = (
        "robot_platform.adapters",
        "robot_platform.flow",
        "robot_platform.library",
        "robot_platform.platform",
    )
    violations: list[str] = []
    for relative in guarded:
        path = PROJECT_ROOT / relative
        imports = _imports_from_tree(ast.parse(
            path.read_text(encoding="utf-8"), filename=str(path),
        ))
        violations.extend(
            f"{relative}: {module}"
            for module in imports
            if module.startswith(forbidden)
        )
    assert not violations


def test_product_adapters_are_selected_only_by_bootstrap() -> None:
    offenders: list[str] = []
    for root in ("robot_platform", "ai_runtime", "robot_server"):
        for path in (PROJECT_ROOT / root).rglob("*.py"):
            relative = path.relative_to(PROJECT_ROOT).as_posix()
            if relative.startswith("robot_platform/adapters/"):
                continue
            source = path.read_text(encoding="utf-8")
            if "robot_platform.adapters" not in source:
                continue
            imports = _imports_from_tree(ast.parse(source, filename=str(path)))
            if any(module.startswith("robot_platform.adapters") for module in imports):
                offenders.append(relative)
    assert set(offenders) <= {"robot_server/bootstrap.py"}


def test_all_file_library_writers_use_shared_transaction_coordinator() -> None:
    required = {
        "robot_platform/library/mutation_service.py": "library_transaction",
        "robot_platform/adapters/library_management.py": "library_transaction",
        "robot_platform/adapters/library_maintenance.py": "library_transaction",
        "robot_platform/adapters/position_library.py": "synchronized_library_method",
        "robot_platform/adapters/flow_management.py": "synchronized_library_method",
    }
    for relative_path, marker in required.items():
        source = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        assert "robot_platform.library.transaction" in source, relative_path
        assert marker in source, relative_path


def test_ai_provider_contracts_do_not_depend_on_robot_or_server_implementations() -> None:
    imports: set[str] = set()
    for relative in (
        "ai_runtime/engine_contract.py",
        "ai_runtime/provider_contract.py",
        "ai_runtime/providers/scripted_provider.py",
    ):
        path = PROJECT_ROOT / relative
        imports.update(_imports_from_tree(ast.parse(
            path.read_text(encoding="utf-8"), filename=str(path),
        )))
    assert not [
        module for module in imports
        if module.startswith(("robot_platform.backends", "robot_server"))
        or module == "nanobot" or module.startswith("nanobot.")
    ]


def test_robot_server_does_not_import_nanobot_concrete_runtime() -> None:
    imports = _imports_under("robot_server")
    forbidden = (
        "nanobot.agent.loop",
        "nanobot.bus",
        "nanobot.session",
        "nanobot.cron.service",
    )
    assert not [
        module for module in imports
        if module in forbidden or module.startswith(tuple(f"{item}." for item in forbidden))
    ]


def test_tool_adapters_do_not_import_server_or_vendor_adapters() -> None:
    imports = _imports_under("ai_runtime/robot_tools")
    assert not [
        module for module in imports
        if module.startswith("robot_server")
        or module.startswith("robot_platform.backends.zmotion")
    ]


def test_tool_runtime_core_is_agent_sdk_and_server_independent() -> None:
    guarded = (
        "ai_runtime/tool_contracts.py",
        "ai_runtime/tool_manifest.py",
        "ai_runtime/tool_registry.py",
        "ai_runtime/tool_runtime.py",
        "ai_runtime/tool_catalog.py",
    )
    forbidden = ("nanobot", "robot_server")
    for relative in guarded:
        path = PROJECT_ROOT / relative
        imports = _imports_from_tree(ast.parse(
            path.read_text(encoding="utf-8"), filename=str(path),
        ))
        assert not [
            module for module in imports if module.startswith(forbidden)
        ], relative


def test_robot_knowledge_tool_does_not_import_concrete_store() -> None:
    path = PROJECT_ROOT / "ai_runtime/robot_tools/robot_knowledge.py"
    imports = _imports_from_tree(ast.parse(
        path.read_text(encoding="utf-8"), filename=str(path),
    ))
    assert not [
        module for module in imports
        if module.startswith(("robot_platform.knowledge", "robot_platform.adapters"))
    ]


def test_product_robot_tools_depend_only_on_application_and_domain_contracts() -> None:
    forbidden = (
        "robot_platform.backends",
        "robot_platform.adapters",
        "robot_platform.platform",
        "robot_platform.tools",
        "robot_platform.knowledge",
        "robot_platform.library",
        "robot_platform.positions",
        "robot_platform.flow",
    )
    for path in (PROJECT_ROOT / "ai_runtime" / "robot_tools").glob("robot_*.py"):
        imports = _imports_from_tree(ast.parse(
            path.read_text(encoding="utf-8"), filename=str(path),
        ))
        assert not [
            module for module in imports if module.startswith(forbidden)
        ], path.name


def test_governed_runtime_layers_reject_unresolved_dynamic_imports() -> None:
    for directory in ("robot_platform", "ai_runtime", "robot_server"):
        assert DYNAMIC_IMPORT_SENTINEL not in _imports_under(directory), (
            f"{directory} contains an importlib/__import__ target that the "
            "architecture gate cannot evaluate statically"
        )

    cron_tool = PROJECT_ROOT / "nanobot" / "agent" / "tools" / "cron.py"
    assert DYNAMIC_IMPORT_SENTINEL not in _imports_from_tree(ast.parse(
        cron_tool.read_text(encoding="utf-8"), filename=str(cron_tool),
    ))


def test_cron_tool_depends_only_on_neutral_application_contracts() -> None:
    path = PROJECT_ROOT / "nanobot" / "agent" / "tools" / "cron.py"
    imports = _imports_from_tree(ast.parse(
        path.read_text(encoding="utf-8"), filename=str(path),
    ))
    forbidden = (
        "nanobot.cron.application_adapter",
        "nanobot.cron.service",
        "robot_platform.library.auth",
    )
    assert not [module for module in imports if module.startswith(forbidden)]

    product_loader = (
        PROJECT_ROOT / "ai_runtime" / "tool_loader.py"
    ).read_text(encoding="utf-8")
    assert "cron_application=self._cron_application" not in product_loader
    assert "CronTool.create(ctx)" not in product_loader
    assert "tool = CronTool(" in product_loader


def test_concrete_runtime_construction_sites_are_explicitly_ratchet_limited() -> None:
    """Stage-0 ratchet: no new hidden composition roots during migration."""
    allowed = {
        "ai_runtime/robot_tools/robot_flow.py",
        "robot_platform/backends/product_wiring.py",
        "robot_platform/backends/wiring.py",
        "robot_platform/backends/zmotion_readonly_diagnostics.py",
        "robot_platform/bridge.py",
        "robot_platform/execution/__init__.py",
        "robot_platform/tools/robot_tools.py",
        "robot_server/app.py",
        "robot_server/bootstrap.py",
        "robot_server/cli.py",
        "robot_server/execution_api.py",
        "robot_server/product_profile.py",
        "robot_server/robot_api.py",
    }
    found: set[str] = set()
    for root in ("robot_platform", "ai_runtime", "robot_server"):
        for path in (PROJECT_ROOT / root).rglob("*.py"):
            if _concrete_runtime_references(
                path.read_text(encoding="utf-8"), filename=str(path),
            ):
                found.add(path.relative_to(PROJECT_ROOT).as_posix())
    assert found <= allowed, f"New hidden composition root(s): {sorted(found - allowed)}"


def test_http_app_does_not_construct_the_runtime_object_graph() -> None:
    moved_constructors = {
        "RobotPlatform", "ExecutionPermitStore", "PendingPlanStore",
        "SessionGateStore", "RobotOperationService",
        "ConfirmedPlanExecutionEngine", "RobotMotionApplicationService",
        "RobotIOApplicationService",
        "EmergencyStopApplicationService", "ProductEmergencyStopAdapter",
        "EmergencyStopAuditOutbox", "RobotLibraryService",
        "RobotIdentityService", "RobotCommandManagementService",
        "RobotFlowManagementService", "RobotAuditService",
        "RobotLibraryTransferService", "RobotPositionMaintenanceService",
        "RobotExecutionService", "ProductProfileService", "LocalUiStateService",
        "LocalSettingsService", "LocalAutomationService", "LocalAppsService",
        "LocalMediaService",
    }

    def calls(path: Path) -> set[str]:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        return {
            node.func.id if isinstance(node.func, ast.Name) else node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, (ast.Name, ast.Attribute))
        }

    app_calls = calls(PROJECT_ROOT / "robot_server" / "app.py")
    bootstrap_calls = calls(PROJECT_ROOT / "robot_server" / "bootstrap.py")
    assert not (app_calls & moved_constructors)
    assert moved_constructors <= bootstrap_calls


@pytest.mark.parametrize(
    "source",
    [
        "from robot_platform import RobotPlatform as RP\nRP()",
        "import robot_platform as rp\nrp.RobotPlatform()",
        (
            "from robot_platform.backends.product_wiring "
            "import create_product_robot_backend as make\nmake(None)"
        ),
        (
            "from robot_platform.backends.product_wiring "
            "import create_product_backend_manager as make\nmake(None)"
        ),
        "from robot_platform import RobotPlatform as RP\nAlias = RP\nAlias()",
        "import importlib\nimportlib.import_module('robot_platform.execution.permit')",
        (
            "from importlib import import_module as load\n"
            "load('robot_platform.execution.permit')"
        ),
        "__import__('robot_platform.backends.emergency_stop')",
        "from robot_platform import RobotPlatform as RP\nclass Local(RP): pass\nLocal()",
        "import robot_platform as rp\ngetattr(rp, 'RobotPlatform')()",
    ],
)
def test_concrete_runtime_reference_detector_rejects_alias_escape_hatches(
    source: str,
) -> None:
    assert _concrete_runtime_references(source)


def test_import_scanner_sees_literal_dynamic_dependencies_and_rejects_unknowns() -> None:
    literal = ast.parse(
        "from importlib import import_module as load\nload('robot_server.app')"
    )
    assert "robot_server.app" in _imports_from_tree(literal)

    unresolved = ast.parse(
        "from importlib import import_module as load\n"
        "prefix = 'robot_server.'\nload(prefix + 'app')"
    )
    assert DYNAMIC_IMPORT_SENTINEL in _imports_from_tree(unresolved)

    ordinary_vendor_import = ast.parse(
        "import robot_platform.backends.zmotion_adapter"
    )
    assert "robot_platform.backends.zmotion_adapter" in _imports_from_tree(
        ordinary_vendor_import
    )
