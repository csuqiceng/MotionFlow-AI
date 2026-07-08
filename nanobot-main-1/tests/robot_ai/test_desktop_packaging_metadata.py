import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_robot_desktop_console_script_is_declared() -> None:
    project = _pyproject()["project"]

    assert project["scripts"]["robot-desktop"] == "robot_desktop:main"
    assert project["scripts"]["robot-desktop-probe"] == "robot_ai.runtime_smoke:main"
    assert project["scripts"]["robot-zmotion-readonly-probe"] == "robot_ai.zmotion_readonly_smoke:main"


def test_robot_desktop_code_is_included_in_wheel_config() -> None:
    hatch = _pyproject()["tool"]["hatch"]["build"]
    wheel = hatch["targets"]["wheel"]

    assert "robot_ai/**/*.py" in hatch["include"]
    assert "robot_desktop.py" in hatch["include"]
    assert "tools/verify_robot_desktop_runtime.py" in hatch["include"]
    assert "tools/probe_robot_desktop_window.py" in hatch["include"]
    assert "tools/verify_zmotion_readonly.py" in hatch["include"]
    assert "robot_ai" in wheel["packages"]
    assert "robot_desktop.py" in wheel["force-include"]
