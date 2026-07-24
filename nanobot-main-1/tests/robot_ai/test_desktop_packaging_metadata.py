import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_robot_server_console_scripts_are_declared() -> None:
    project = _pyproject()["project"]

    assert project["scripts"]["robot-server"] == "robot_server.cli:main"
    assert project["scripts"]["robot-admin"] == "robot_server.admin_cli:app"
    assert project["scripts"]["robot-zmotion-readonly-probe"] == "robot_platform.zmotion_readonly_smoke:main"


def test_robot_platform_code_is_included_in_wheel_config() -> None:
    hatch = _pyproject()["tool"]["hatch"]["build"]
    wheel = hatch["targets"]["wheel"]

    assert "robot_platform/**/*.py" in hatch["include"]
    assert "ai_runtime/**/*.py" in hatch["include"]
    assert "robot_server/**/*.py" in hatch["include"]
    assert "tools/verify_zmotion_readonly.py" in hatch["include"]
    assert "robot_platform" in wheel["packages"]
    assert "ai_runtime" in wheel["packages"]
    assert "robot_server" in wheel["packages"]
