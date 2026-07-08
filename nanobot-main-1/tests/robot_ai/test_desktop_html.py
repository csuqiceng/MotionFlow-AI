from robot_ai.bridge import RobotApi
from robot_desktop import HTML, create_api


def test_desktop_html_wires_voice_api() -> None:
    assert "get_voice_state" in HTML
    assert "synthesize_speech" in HTML
    assert "audioPlayer" in HTML
    assert "data:${result.data.mime_type};base64,${result.data.audio_base64}" in HTML


def test_desktop_html_refreshes_health_on_startup() -> None:
    assert "async function refreshStatus()" in HTML
    assert "window.pywebview.api.health()" in HTML
    assert 'window.addEventListener("pywebviewready", refreshStatus)' in HTML
    assert "callApi('get_robot_state')" not in HTML


def test_desktop_html_uses_restricted_operator_controls_only() -> None:
    assert "operator_system_control" in HTML
    assert "operator_linear_move" in HTML
    assert "operator_linear_path" in HTML
    assert "operator_delay" in HTML
    assert "operator_io" in HTML
    assert "move_axis" not in HTML
    assert "callApi('home')" not in HTML
    assert "callApi('stop')" not in HTML
    assert "X +10" not in HTML


def test_desktop_html_has_operator_status_card() -> None:
    assert 'id="operatorStatus"' in HTML
    assert 'id="backendMode"' in HTML
    assert 'id="backendControl"' in HTML
    assert 'id="backendConfig"' in HTML
    assert 'id="deviceState"' in HTML
    assert 'id="backendMessage"' in HTML


def test_desktop_html_renders_operator_status_from_health_result() -> None:
    assert "function renderOperatorStatus(result)" in HTML
    assert "const backend = result.data && result.data.backend ? result.data.backend : {};" in HTML
    assert "const robotState = result.data && result.data.robot_state ? result.data.robot_state : {};" in HTML
    assert 'backendMode.textContent = backend.mode || "unknown";' in HTML
    assert 'backendControl.textContent = backend.control_enabled ? "enabled" : "read-only";' in HTML
    assert 'backendConfig.textContent = backend.configuration_ready ? "ready" : missingConfig;' in HTML
    assert 'deviceState.textContent = robotState.connected_real_device ? "connected" : robotState.mode || "not connected";' in HTML
    assert "renderOperatorStatus(result);" in HTML


def test_desktop_html_wires_readonly_diagnostics_button_with_confirmation() -> None:
    assert "run_zmotion_readonly_diagnostics" in HTML
    assert "async function runReadonlyDiagnostics()" in HTML
    assert "window.confirm(" in HTML
    assert "const result = await window.pywebview.api.run_zmotion_readonly_diagnostics(confirmed);" in HTML
    assert "renderOperatorStatus(result);" in HTML
    assert "Read-only diagnostics" in HTML


def test_create_api_returns_robot_api() -> None:
    assert isinstance(create_api(), RobotApi)
