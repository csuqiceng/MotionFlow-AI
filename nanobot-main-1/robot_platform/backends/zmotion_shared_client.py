"""Single shared ZMotion SDK client for the gateway process.

Both the read-only status backend and the operator motion path draw from this one
client so the gateway holds exactly ONE ``ZAux_OpenEth`` connection to the
controller — matching the legacy Qt app, which holds a single persistent
``ZMotionVrClient``. Without this, the status path and the motion path each
opened their own connection; combined with ZRobotView/HMIUI that exceeded the
controller's limited ZAux session table and motion commands failed with code
3402.

Gateway-only: enabled by the ``ROBOT_AI_SHARED_CLIENT`` env var (set in
``start_gateway.sh``). The CLI and tests do not set it, so they keep creating
their own clients (factory mode) — no behavior change there.

Thread-safe (one lock around connect/reset). On a read/write failure the caller
invokes :func:`reset` so the next :func:`get` opens a fresh connection; without
that, a dead ZAux handle would be reused forever.
"""

from __future__ import annotations

import os
import threading
from typing import Any

from robot_platform.backends.zmotion_sdk import ZMotionSdkClient, ZMotionSdkConfig


def shared_client_enabled(env: dict[str, str] | None = None) -> bool:
    """Whether the gateway shared-client mode is on (``ROBOT_AI_SHARED_CLIENT``)."""
    source = env if env is not None else os.environ
    return source.get("ROBOT_AI_SHARED_CLIENT", "").strip().lower() in {"1", "true", "yes", "on"}


_lock = threading.Lock()
_client: ZMotionSdkClient | None = None
_host: str | None = None
_sdk_config: ZMotionSdkConfig | None = None
# Tests inject a fake client here without touching the real SDK.
_override: Any = None


def configure(host: str, sdk_config: ZMotionSdkConfig) -> None:
    """Set the host/sdk_config the shared client connects with."""
    global _host, _sdk_config
    _host = host
    _sdk_config = sdk_config


def is_configured() -> bool:
    """Whether :func:`configure` has supplied host + sdk_config."""
    return _host is not None and _sdk_config is not None


def set_override(client: Any) -> None:
    """Tests: inject a fake client (pass None to clear). Bypasses the real SDK."""
    global _override, _client
    with _lock:
        _override = client
        _client = None


def get() -> ZMotionSdkClient:
    """Return the connected shared client, creating/reconnecting as needed."""
    global _client
    with _lock:
        if _override is not None:
            return _override
        if _client is not None and _client.connected:
            return _client
        if _host is None or _sdk_config is None:
            raise RuntimeError("Shared ZMotion client used before configure().")
        _client = ZMotionSdkClient(host=_host, sdk_config=_sdk_config)
        _client.connect()
        return _client


def reset() -> None:
    """Drop the shared client so the next ``get()`` reconnects.

    Called by consumers when a read/write fails (dead handle, controller reboot,
    kicked by another client). Best-effort disconnect so the dead session does
    not linger on the controller.
    """
    global _client
    with _lock:
        if _override is not None or _client is None:
            return
        try:
            _client.disconnect()
        except Exception:
            _client.connected = False
        _client = None


def _reset_state_for_tests() -> None:
    """Clear all module state. Tests only — used by the autouse fixture in
    tests/robot_ai/conftest.py so shared-mode state can't leak between tests."""
    global _client, _host, _sdk_config, _override
    with _lock:
        _client = None
        _host = None
        _sdk_config = None
        _override = None
