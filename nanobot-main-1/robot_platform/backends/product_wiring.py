"""Current product composition for optional robot backend plugins."""

from __future__ import annotations

from typing import Any

from robot_platform.backends.contracts import RobotBackend
from robot_platform.backends.factory import RobotBackendConfig, create_robot_backend
from robot_platform.backends.registry import BackendRegistry
from robot_platform.backends.wiring import create_default_backend_registry


def create_product_robot_backend(
    config: RobotBackendConfig | None = None,
    *,
    registry: BackendRegistry | None = None,
    client_factory: Any = None,
    probe_only: bool = False,
) -> RobotBackend:
    """Create a backend with only the plugin required by the selected mode."""
    resolved = config or RobotBackendConfig.from_env()
    assembled = registry or create_default_backend_registry()
    if registry is None and _is_zmotion_mode(resolved.mode):
        from robot_platform.backends.zmotion_plugin import ZMotionBackendPlugin

        assembled.register_plugin(ZMotionBackendPlugin())
    return create_robot_backend(
        resolved,
        registry=assembled,
        client_factory=client_factory,
        probe_only=probe_only,
    )


def probe_product_controller(host: str, config: RobotBackendConfig | None = None) -> dict[str, Any]:
    """Read one controller snapshot from *host* without changing live wiring.

    Login diagnostics must inspect the address the engineer entered, rather
    than the long-lived backend's configured host.  ``probe_only`` also avoids
    borrowing or reconfiguring the process-wide ZMotion connection used by
    live control.
    """
    resolved = config or RobotBackendConfig.from_env()
    probe_config = RobotBackendConfig(
        mode=resolved.mode,
        controller_host=host,
        zmotion_wrapper_path=resolved.zmotion_wrapper_path,
        zmotion_dll_dir=resolved.zmotion_dll_dir,
    )
    backend = create_product_robot_backend(probe_config, probe_only=True)
    try:
        return backend.get_state().to_dict()
    finally:
        close = getattr(backend, "close", None)
        if callable(close):
            close()


def _is_zmotion_mode(mode: str) -> bool:
    return str(mode or "").strip().lower() in {
        "zmotion_readonly",
        "zreadonly",
        "real_readonly",
    }
