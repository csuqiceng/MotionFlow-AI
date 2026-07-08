from pathlib import Path

from robot_ai.runtime_smoke import main, run_robot_desktop_smoke


ROOT = Path(__file__).resolve().parents[2]


def test_runtime_smoke_reports_missing_dependencies() -> None:
    def missing_dependencies():
        return {
            "ready": False,
            "missing_required": ["webview"],
            "missing_optional": ["edge_tts"],
            "install_extra": "robot-desktop",
        }

    result = run_robot_desktop_smoke(dependency_status_provider=missing_dependencies)

    assert result["ok"] is False
    assert result["state"] == "runtime_dependencies_missing"
    assert result["data"]["missing_required"] == ["webview"]
    assert 'python -m pip install -e ".[robot-desktop]"' in result["message"]


def test_runtime_smoke_exercises_robot_api_when_dependencies_ready() -> None:
    def ready_dependencies():
        return {
            "ready": True,
            "missing_required": [],
            "missing_optional": ["edge_tts"],
            "install_extra": "robot-desktop",
        }

    result = run_robot_desktop_smoke(dependency_status_provider=ready_dependencies)

    assert result["ok"] is True
    assert result["state"] == "runtime_smoke_passed"
    assert result["data"]["health"]["state"] == "healthy"
    assert result["data"]["linear_move"]["ok"] is False
    assert result["data"]["linear_move"]["state"] == "zmotion_operator_configuration_missing"
    assert result["data"]["robot_state"]["data"]["robot_state"]["axes_mm"]["x"] == 0.0
    assert result["data"]["voice"]["state"] == "voice_ready"


def test_runtime_smoke_cli_script_exists() -> None:
    script = ROOT / "tools" / "verify_robot_desktop_runtime.py"

    assert script.exists()
    text = script.read_text(encoding="utf-8")
    assert "run_robot_desktop_smoke" in text
    assert "json.dumps" in text


def test_runtime_smoke_main_returns_process_status(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "robot_ai.runtime_smoke.run_robot_desktop_smoke",
        lambda: {"ok": True, "message": "ok", "state": "runtime_smoke_passed"},
    )

    exit_code = main(["--json"])

    assert exit_code == 0
    assert '"runtime_smoke_passed"' in capsys.readouterr().out
