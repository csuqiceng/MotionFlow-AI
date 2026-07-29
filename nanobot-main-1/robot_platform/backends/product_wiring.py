"""Current product composition for optional robot backend plugins."""

from __future__ import annotations

from typing import Any

from robot_platform.backends.contracts import RobotBackend
from robot_platform.backends.factory import RobotBackendConfig, create_robot_backend
from robot_platform.backends.lifecycle import (
    BackendManager,
    bundle_legacy_backend,
)
from robot_platform.backends.registry import BackendRegistry
from robot_platform.backends.wiring import create_default_backend_registry


def create_product_robot_backend(
    config: RobotBackendConfig | None = None,
    *,
    registry: BackendRegistry | None = None,
    client_factory: Any = None,
    probe_only: bool = False,
    permit_verifier: Any = None,
    emergency_stop_verifier: Any = None,
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
        permit_verifier=permit_verifier,
        emergency_stop_verifier=emergency_stop_verifier,
    )


def create_product_backend_manager(
    config: RobotBackendConfig | None = None,
    *,
    startup_timeout: float = 5.0,
    client_factory: Any = None,
    permit_verifier: Any = None,
    emergency_stop_verifier: Any = None,
) -> BackendManager:
    """Create, validate, and start the selected product Backend bundle."""
    resolved = config or RobotBackendConfig.from_env()
    registry = create_default_backend_registry()
    if _is_zmotion_mode(resolved.mode):
        from robot_platform.backends.zmotion_plugin import ZMotionBackendPlugin

        registry.register_plugin(ZMotionBackendPlugin())
    backend = create_robot_backend(
        resolved,
        registry=registry,
        client_factory=client_factory,
        permit_verifier=permit_verifier,
        emergency_stop_verifier=emergency_stop_verifier,
    )
    normalized = str(resolved.mode).strip().casefold()
    manifest = next(
        (
            item for item in registry.plugin_manifests
            if normalized in {mode.casefold() for mode in item.backend_modes}
        ),
        None,
    )
    if manifest is None:
        close = getattr(backend, "close", None)
        if callable(close):
            close()
        raise ValueError(f"Selected Backend has no plugin manifest: {resolved.mode}")
    manager = BackendManager(manifest, bundle_legacy_backend(backend))
    try:
        manager.start(timeout=startup_timeout)
    except BaseException:
        manager.close(timeout=startup_timeout)
        raise
    return manager


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
