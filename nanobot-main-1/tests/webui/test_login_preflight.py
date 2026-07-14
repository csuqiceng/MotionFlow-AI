from __future__ import annotations

import pytest

from nanobot.config.schema import Config
from nanobot.webui import login_preflight as preflight
from nanobot.webui.login_preflight import PreflightInputError, validate_controller_host


@pytest.mark.parametrize("host", ["10.168.3.21", "192.168.1.20", "127.0.0.1"])
def test_validate_controller_host_accepts_private_and_loopback(host: str) -> None:
    assert validate_controller_host(host) == host


@pytest.mark.parametrize("host", ["", "example.com", "8.8.8.8", "http://10.168.3.21"])
def test_validate_controller_host_rejects_non_private_targets(host: str) -> None:
    with pytest.raises(PreflightInputError):
        validate_controller_host(host)


def test_preflight_returns_all_services_when_voice_probe_fails(monkeypatch) -> None:
    monkeypatch.setattr(preflight, "probe_controller", lambda host: {"state": "healthy", "latency_ms": 4})
    monkeypatch.setattr(preflight, "probe_voice", lambda config: {"state": "unhealthy", "reason": "voice timeout", "latency_ms": 20})
    monkeypatch.setattr(preflight, "probe_ai", lambda config: {"state": "healthy", "latency_ms": 18})

    result = preflight.run_login_preflight("10.168.3.21", config=Config())

    assert result["controller"]["state"] == "healthy"
    assert result["voice"] == {"state": "unhealthy", "reason": "voice timeout", "latency_ms": 20}
    assert result["ai"]["state"] == "healthy"


def test_probe_ai_uses_active_provider_factory(monkeypatch) -> None:
    class HealthyProvider:
        async def chat(self, *_args, **_kwargs):
            return type("Response", (), {"finish_reason": "stop"})()

    monkeypatch.setattr(
        "nanobot.providers.factory.make_provider",
        lambda _config: HealthyProvider(),
    )

    result = preflight.probe_ai(Config())

    assert result["state"] == "healthy"


def test_probe_ai_allows_the_configured_response_window(monkeypatch) -> None:
    observed: dict[str, float] = {}

    def fake_await(coro, *, timeout_s: float) -> None:
        coro.close()
        observed["timeout_s"] = timeout_s

    monkeypatch.setattr(preflight, "_await", fake_await)

    result = preflight.probe_ai(Config())

    assert result["state"] == "healthy"
    assert observed["timeout_s"] >= 12
