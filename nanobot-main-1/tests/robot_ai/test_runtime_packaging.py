import tomllib
from pathlib import Path

import pytest

from robot_ai.runtime import (
    desktop_runtime_dependency_status,
    format_desktop_dependency_help,
)
import robot_desktop
from robot_desktop import HTML


ROOT = Path(__file__).resolve().parents[2]


def _optional_dependencies() -> dict[str, list[str]]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["optional-dependencies"]


def test_pyproject_declares_desktop_and_voice_extras() -> None:
    extras = _optional_dependencies()

    assert "desktop" in extras
    assert "voice" in extras
    assert "robot-desktop" in extras
    assert any(dep.startswith("pywebview>=") for dep in extras["desktop"])
    assert any(dep.startswith("edge-tts>=") for dep in extras["voice"])
    assert any(dep.startswith("pywebview>=") for dep in extras["robot-desktop"])
    assert any(dep.startswith("edge-tts>=") for dep in extras["robot-desktop"])


def test_desktop_html_uses_readable_chinese_labels() -> None:
    assert "输入机械手指令或对话" in HTML
    assert "发送" in HTML
    assert "查询状态" in HTML
    assert "语音状态" in HTML
    assert "朗读" in HTML
    assert "杈" not in HTML
    assert "鍙" not in HTML


def test_desktop_runtime_dependency_status_reports_missing_modules() -> None:
    available = {"pydantic", "loguru"}

    def fake_find_spec(name: str):
        return object() if name in available else None

    status = desktop_runtime_dependency_status(find_spec=fake_find_spec)

    assert status["ready"] is False
    assert status["missing_required"] == ["webview"]
    assert status["missing_optional"] == ["edge_tts"]
    assert status["install_extra"] == "robot-desktop"


def test_desktop_runtime_dependency_status_reports_ready_when_required_exist() -> None:
    available = {"pydantic", "loguru", "webview"}

    def fake_find_spec(name: str):
        return object() if name in available else None

    status = desktop_runtime_dependency_status(find_spec=fake_find_spec)

    assert status["ready"] is True
    assert status["missing_required"] == []
    assert status["missing_optional"] == ["edge_tts"]


def test_format_desktop_dependency_help_includes_install_command() -> None:
    status = {
        "missing_required": ["webview"],
        "missing_optional": ["edge_tts"],
        "install_extra": "robot-desktop",
    }

    message = format_desktop_dependency_help(status)

    assert "Missing required desktop dependencies: webview" in message
    assert "Missing optional voice dependencies: edge_tts" in message
    assert 'python -m pip install -e ".[robot-desktop]"' in message


def test_format_desktop_dependency_help_requires_missing_status() -> None:
    with pytest.raises(RuntimeError, match="Desktop runtime dependencies are ready"):
        format_desktop_dependency_help({"missing_required": [], "missing_optional": []})


def test_desktop_main_reports_dependency_help(monkeypatch) -> None:
    monkeypatch.setattr(
        robot_desktop,
        "desktop_runtime_dependency_status",
        lambda: {
            "ready": False,
            "missing_required": ["webview"],
            "missing_optional": ["edge_tts"],
            "install_extra": "robot-desktop",
        },
    )

    with pytest.raises(RuntimeError) as exc_info:
        robot_desktop.main()

    assert "Missing required desktop dependencies: webview" in str(exc_info.value)
    assert 'python -m pip install -e ".[robot-desktop]"' in str(exc_info.value)
