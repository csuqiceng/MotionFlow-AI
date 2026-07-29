from __future__ import annotations

from pathlib import Path

from robot_ai.backends.factory import RobotBackendConfig
from robot_ai.models import RobotState, ToolResult
from robot_ai.zmotion_readonly_smoke import (
    format_zmotion_readonly_setup_help,
    main,
    run_zmotion_readonly_smoke,
)


ROOT = Path(__file__).resolve().parents[2]


class RecordingBackend:
    def __init__(self) -> None:
        self.moves: list[tuple[str, float]] = []
        self.home_calls = 0
        self.stop_calls = 0

    def get_state(self) -> RobotState:
        return RobotState(
            mode="idle",
            axes_mm={"x": 1.0, "y": 2.0, "z": 3.0, "rx": 4.0, "ry": 5.0, "rz": 6.0},
            connected_real_device=True,
        )

    def move_axis(self, axis: str, delta: float) -> ToolResult:
        self.moves.append((axis, delta))
        return ToolResult.failure(state="unexpected_write", message="write should not happen")

    def home(self) -> ToolResult:
        self.home_calls += 1
        return ToolResult.failure(state="unexpected_write", message="write should not happen")

    def stop(self) -> ToolResult:
        self.stop_calls += 1
        return ToolResult.failure(state="unexpected_write", message="write should not happen")


def test_readonly_smoke_refuses_without_explicit_confirmation() -> None:
    created_configs: list[RobotBackendConfig] = []

    def backend_factory(config: RobotBackendConfig):
        created_configs.append(config)
        return RecordingBackend()

    result = run_zmotion_readonly_smoke(
        confirmed_readonly_diagnostics=False,
        backend_factory=backend_factory,
    )

    assert result["ok"] is False
    assert result["state"] == "readonly_diagnostics_confirmation_required"
    assert created_configs == []


def test_readonly_smoke_reads_state_once_without_motion_writes() -> None:
    backend = RecordingBackend()
    created_configs: list[RobotBackendConfig] = []

    def backend_factory(config: RobotBackendConfig):
        created_configs.append(config)
        return backend

    result = run_zmotion_readonly_smoke(
        confirmed_readonly_diagnostics=True,
        config=RobotBackendConfig(
            mode="simulation",
            controller_host="ignored",
            zmotion_wrapper_path="ignored_wrapper.py",
            zmotion_dll_dir="ignored_dll_dir",
        ),
        backend_factory=backend_factory,
    )

    assert result["ok"] is True
    assert result["state"] == "zmotion_readonly_smoke_passed"
    assert created_configs == [
        RobotBackendConfig(
            mode="zmotion_readonly",
            controller_host="ignored",
            zmotion_wrapper_path="ignored_wrapper.py",
            zmotion_dll_dir="ignored_dll_dir",
        )
    ]
    assert result["data"]["robot_state"]["connected_real_device"] is True
    assert result["data"]["robot_state"]["axes_mm"]["x"] == 1.0
    assert backend.moves == []
    assert backend.home_calls == 0
    assert backend.stop_calls == 0


def test_readonly_smoke_reports_missing_sdk_config_before_backend_creation() -> None:
    created_configs: list[RobotBackendConfig] = []

    def backend_factory(config: RobotBackendConfig):
        created_configs.append(config)
        return RecordingBackend()

    result = run_zmotion_readonly_smoke(
        confirmed_readonly_diagnostics=True,
        config=RobotBackendConfig(
            mode="simulation",
            controller_host="10.168.3.21",
            zmotion_wrapper_path="",
            zmotion_dll_dir="",
        ),
        backend_factory=backend_factory,
    )

    assert result["ok"] is False
    assert result["state"] == "zmotion_readonly_configuration_missing"
    assert result["data"]["missing"] == ["ROBOT_ZMOTION_WRAPPER_PATH", "ROBOT_ZMOTION_DLL_DIR"]
    assert "tools\\verify_zmotion_readonly.py --read-only-diagnostics --json" in result["message"]
    assert created_configs == []


def test_zmotion_readonly_setup_help_includes_operator_workflow() -> None:
    help_text = format_zmotion_readonly_setup_help(
        RobotBackendConfig(
            mode="simulation",
            controller_host="10.168.3.21",
            zmotion_wrapper_path="",
            zmotion_dll_dir="",
        )
    )

    assert "ROBOT_AI_BACKEND=zmotion_readonly" in help_text
    assert "ROBOT_CONTROLLER_HOST=10.168.3.21" in help_text
    assert "ROBOT_ZMOTION_WRAPPER_PATH" in help_text
    assert "ROBOT_ZMOTION_DLL_DIR" in help_text
    assert "--read-only-diagnostics" in help_text
    assert "IEEE(32)" in help_text


def test_readonly_smoke_cli_requires_confirmation(capsys) -> None:
    exit_code = main(["--json"])

    assert exit_code == 1
    assert '"readonly_diagnostics_confirmation_required"' in capsys.readouterr().out


def test_readonly_smoke_cli_script_exists() -> None:
    script = ROOT / "tools" / "verify_zmotion_readonly.py"

    assert script.exists()
    text = script.read_text(encoding="utf-8")
    assert "run_zmotion_readonly_smoke" in text
    assert "--read-only-diagnostics" in text


def test_current_robot_architecture_and_migration_document_exists() -> None:
    doc = ROOT / "docs" / "architecture" / "motionflow-decoupling-componentization-master-plan.md"

    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    assert "ExecutionPermitVerifierPort" in text
    assert "EmergencyStopApplicationService" in text
    assert "OUTCOME_UNKNOWN" in text
