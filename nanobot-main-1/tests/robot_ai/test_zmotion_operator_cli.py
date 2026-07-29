from __future__ import annotations

import json
from pathlib import Path

import pytest

from robot_ai.models import ToolResult


class CapturingRunner:
    def __init__(self, result: dict | None = None) -> None:
        self.result = result or ToolResult.success(
            state="zmotion_operator_dry_run",
            message="dry run",
        ).to_dict()
        self.calls: list[dict] = []

    def __call__(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        return self.result


def test_cli_parses_linear_move_and_workspace_parameters(capsys) -> None:
    from robot_ai.zmotion_operator_control import main

    runner = CapturingRunner()

    status = main(
        [
            "--host",
            "10.168.3.21",
            "--wrapper-path",
            "vendor/zauxdllPython.py",
            "--dll-dir",
            "vendor/dll",
            "linear-move",
            "--x",
            "900",
            "--y",
            "0",
            "--z",
            "999",
            "--rx",
            "0",
            "--ry",
            "0",
            "--rz",
            "0",
            "--speed-pct",
            "5",
            "--acceleration-pct",
            "4",
            "--deceleration-pct",
            "3",
            "--r-min",
            "800",
            "--r-max",
            "1000",
            "--z-min",
            "900",
            "--z-max",
            "1100",
        ],
        runner=runner,
    )

    assert status == 0
    request = runner.calls[0]["request"]
    assert request.command == "linear_move"
    assert request.parameters == {
        "target_pose": {
            "x": 900.0,
            "y": 0.0,
            "z": 999.0,
            "rx": 0.0,
            "ry": 0.0,
            "rz": 0.0,
        },
        "speed_pct": 5.0,
        "acceleration_pct": 4.0,
        "deceleration_pct": 3.0,
        "r_min": 800.0,
        "r_max": 1000.0,
        "z_min": 900.0,
        "z_max": 1100.0,
    }
    assert runner.calls[0]["config"].controller_host == "10.168.3.21"
    assert capsys.readouterr().out.strip() == "dry run"


def test_cli_parses_linear_path_json_points(capsys) -> None:
    from robot_ai.zmotion_operator_control import main

    runner = CapturingRunner()

    status = main(
        [
            "linear-path",
            "--points-json",
            '[{"x":900,"y":0,"z":999,"rx":0,"ry":0,"rz":0},{"x":901,"y":0,"z":999,"rx":0,"ry":0,"rz":0}]',
            "--speed-pct",
            "5",
            "--acceleration-pct",
            "5",
            "--deceleration-pct",
            "5",
            "--r-min",
            "800",
            "--r-max",
            "1000",
            "--z-min",
            "900",
            "--z-max",
            "1100",
        ],
        runner=runner,
    )

    assert status == 0
    request = runner.calls[0]["request"]
    assert request.command == "linear_path"
    assert len(request.parameters["target_poses"]) == 2
    assert request.parameters["target_poses"][1]["x"] == 901.0


def test_cli_parses_real_execution_confirmations_for_system_command() -> None:
    from robot_ai.zmotion_operator_control import main

    runner = CapturingRunner()

    status = main(
        [
            "--host",
            "10.168.3.21",
            "--wrapper-path",
            "wrapper.py",
            "--dll-dir",
            "dll",
            "--execute-real",
            "--confirm-work-area-clear",
            "--confirm-estop-ready",
            "--confirmation-code",
            "EXECUTE_ZMOTION_REAL",
            "system",
            "--action",
            "pause",
        ],
        runner=runner,
    )

    request = runner.calls[0]["request"]
    assert status == 0
    assert request.command == "system"
    assert request.parameters == {"action": "pause"}
    assert request.execute_real is True
    assert request.confirm_work_area_clear is True
    assert request.confirm_estop_ready is True
    assert request.confirmation_code == "EXECUTE_ZMOTION_REAL"


def test_vendor_cli_cannot_bypass_dedicated_emergency_stop_application() -> None:
    from robot_ai.zmotion_operator_control import main

    with pytest.raises(SystemExit):
        main(["system", "--action", "emergency_stop"], runner=CapturingRunner())


def test_cli_parses_delay_and_io_commands() -> None:
    from robot_ai.zmotion_operator_control import main

    delay_runner = CapturingRunner()
    io_runner = CapturingRunner()

    delay_status = main(
        ["delay", "--seconds", "0.25"],
        runner=delay_runner,
    )
    io_status = main(
        [
            "io",
            "--io-number",
            "3",
            "--state",
            "off",
            "--allowed-io",
            "2,3,4",
        ],
        runner=io_runner,
    )

    assert delay_status == 0
    assert delay_runner.calls[0]["request"].parameters == {"seconds": 0.25}
    assert io_status == 0
    assert io_runner.calls[0]["request"].parameters == {
        "io_number": 3,
        "enabled": False,
        "allowed_io_channels": [2, 3, 4],
    }


def test_cli_json_output_and_failure_exit_status(capsys) -> None:
    from robot_ai.zmotion_operator_control import main

    failure = ToolResult.failure(
        state="zmotion_operator_confirmation_required",
        message="confirmation required",
    ).to_dict()

    status = main(
        ["--json", "system", "--action", "pause"],
        runner=CapturingRunner(failure),
    )

    output = json.loads(capsys.readouterr().out)
    assert status == 1
    assert output["state"] == "zmotion_operator_confirmation_required"


def test_zmotion_control_tool_script_exists() -> None:
    script = Path(__file__).resolve().parents[2] / "tools" / "verify_zmotion_control.py"

    assert script.exists()
    source = script.read_text(encoding="utf-8")
    assert "robot_ai.zmotion_operator_control import main" in source
    assert "SystemExit(main())" in source
