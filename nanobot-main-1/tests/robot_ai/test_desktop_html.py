from robot_desktop import HTML, create_api
from robot_ai.bridge import RobotApi


def test_desktop_html_wires_voice_api() -> None:
    assert "get_voice_state" in HTML
    assert "synthesize_speech" in HTML
    assert "audioPlayer" in HTML
    assert "data:${result.data.mime_type};base64,${result.data.audio_base64}" in HTML


def test_create_api_returns_robot_api() -> None:
    assert isinstance(create_api(), RobotApi)
