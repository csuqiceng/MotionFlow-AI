"""Safe, pre-auth service checks shown by the WebUI login page."""

from __future__ import annotations

import asyncio
import ipaddress
import time
from dataclasses import replace
from typing import Any

AI_PROBE_TIMEOUT_S = 12


class PreflightInputError(ValueError):
    """Raised when a preflight request contains an unsafe controller target."""


def validate_controller_host(value: object) -> str:
    """Return a private or loopback IP address suitable for a local controller probe."""
    raw = str(value or "").strip()
    try:
        address = ipaddress.ip_address(raw)
    except ValueError as exc:
        raise PreflightInputError("controller_host must be an IP address") from exc
    if not (address.is_private or address.is_loopback):
        raise PreflightInputError("controller_host must be private or loopback")
    return raw


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))


def _probe(name: str, action) -> dict[str, object]:
    started = time.perf_counter()
    try:
        action()
    except Exception:
        return {"state": "unhealthy", "reason": f"{name}_unavailable", "latency_ms": _elapsed_ms(started)}
    return {"state": "healthy", "latency_ms": _elapsed_ms(started)}


def probe_controller(host: object) -> dict[str, object]:
    """Connect to the supplied private controller address and perform a read only state query."""
    controller_host = validate_controller_host(host)

    def check() -> None:
        from robot_ai.backends.factory import RobotBackendConfig, create_robot_backend

        backend = create_robot_backend(replace(RobotBackendConfig.from_env(), controller_host=controller_host))
        state = backend.get_state()
        data = state.to_dict() if hasattr(state, "to_dict") else dict(state)
        if data.get("mode") == "disconnected" or data.get("connected_real_device") is False:
            raise RuntimeError("controller disconnected")

    return _probe("controller", check)


def _await(coro, *, timeout_s: float = 5):
    return asyncio.run(asyncio.wait_for(coro, timeout=timeout_s))


def probe_voice(config: Any) -> dict[str, object]:
    """Probe the configured TTS provider without playing or recording audio."""
    def check() -> None:
        from nanobot.audio.tts import resolve_tts_config, synthesize_text

        _await(synthesize_text(".", resolve_tts_config(config)))

    return _probe("voice", check)


def probe_ai(config: Any) -> dict[str, object]:
    """Make one minimal request to the configured active AI provider."""
    async def check() -> None:
        from nanobot.providers.factory import make_provider

        response = await make_provider(config).chat(
            [{"role": "user", "content": "health"}], max_tokens=1, temperature=0,
        )
        if getattr(response, "finish_reason", None) == "error":
            raise RuntimeError("provider returned error")

    return _probe("ai", lambda: _await(check(), timeout_s=AI_PROBE_TIMEOUT_S))


def run_login_preflight(controller_host: object, *, config: Any | None = None) -> dict[str, dict[str, object]]:
    """Return independent controller, voice, and AI availability results."""
    from nanobot.config.loader import load_config

    host = validate_controller_host(controller_host)
    current = config or load_config()
    return {
        "controller": probe_controller(host),
        "voice": probe_voice(current),
        "ai": probe_ai(current),
    }
