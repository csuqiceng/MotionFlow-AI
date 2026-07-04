from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_config_schema_declares_tts_config() -> None:
    schema = _read("nanobot/config/schema.py")

    assert "class TTSConfig(Base):" in schema
    assert "tts: TTSConfig = Field(default_factory=TTSConfig)" in schema
    assert "voice: str | None = None" in schema
    assert "audio_format: str | None = None" in schema


def test_webui_settings_payload_exposes_tts_section() -> None:
    settings_api = _read("nanobot/webui/settings_api.py")

    assert "resolve_tts_config" in settings_api
    assert "tts_provider_names" in settings_api
    assert "def _tts_provider_rows" in settings_api
    assert '"tts": {' in settings_api
    assert '"provider_configured": tts.configured' in settings_api


def test_webui_settings_routes_expose_tts_update() -> None:
    settings_api = _read("nanobot/webui/settings_api.py")
    settings_routes = _read("nanobot/webui/settings_routes.py")

    assert "def update_tts_settings" in settings_api
    assert '"/api/settings/tts/update"' in settings_routes
    assert "_handle_settings_tts_update" in settings_routes
