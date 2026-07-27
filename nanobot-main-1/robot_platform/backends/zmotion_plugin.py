"""Optional ZMotion backend registration for product composition roots."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from robot_platform.backends.contracts import RobotBackend
from robot_platform.backends.registry import BackendRegistry
from robot_platform.backends.zmotion_backend import ZMotionReadableClient, ZMotionSafetyActionBackend
from robot_platform.backends.zmotion_sdk import ZMotionSdkClient, ZMotionSdkConfig
from robot_platform.backends.zmotion_shared_client import shared_client_enabled


class ZMotionBackendPlugin:
    """Optional vendor plugin for the ZMotion read-only controller backend."""

    plugin_id = "zmotion"
    plugin_version = "1.0.0"
    backend_modes = ("zmotion_readonly", "zreadonly", "real_readonly")

    def register(self, registry: BackendRegistry) -> None:
        registry.register(
            "zmotion_readonly",
            _create_zmotion_readonly,
            aliases=("zreadonly", "real_readonly"),
        )


def register_zmotion_backends(registry: BackendRegistry) -> None:
    """Compatibility helper for existing composition roots."""
    registry.register_plugin(ZMotionBackendPlugin())


def _create_zmotion_readonly(
    config: Any,
    *,
    client_factory: Any = None,
    probe_only: bool = False,
    **options: Any,
) -> RobotBackend:
    system_action_runner = lambda request: _run_zmotion_system_action(request, config)
    if client_factory is not None:
        return ZMotionSafetyActionBackend(
            host=config.controller_host,
            client_factory=client_factory,
            system_action_runner=system_action_runner,
        )
    if shared_client_enabled() and not probe_only:
        from robot_platform.backends import zmotion_shared_client as shared

        sdk_config = resolve_sdk_config(config)
        if sdk_config is None:
            return ZMotionSafetyActionBackend(
                host=config.controller_host,
                client_factory=_missing_zmotion_client_factory,
                system_action_runner=system_action_runner,
            )
        shared.configure(config.controller_host, sdk_config)
        return ZMotionSafetyActionBackend(
            host=config.controller_host,
            use_shared=True,
            system_action_runner=system_action_runner,
        )
    return ZMotionSafetyActionBackend(
        host=config.controller_host,
        client_factory=_create_zmotion_sdk_client_factory(config),
        system_action_runner=system_action_runner,
    )


def _run_zmotion_system_action(request: Any, config: Any) -> dict[str, Any]:
    """Defer the vendor write adapter until a selected backend receives it."""
    from robot_platform.backends.wiring import run_zmotion_operator_request

    return run_zmotion_operator_request(request=request, config=config)


def resolve_sdk_config(config: Any) -> ZMotionSdkConfig | None:
    if not config.zmotion_wrapper_path or not config.zmotion_dll_dir:
        return None
    return ZMotionSdkConfig(
        wrapper_path=Path(config.zmotion_wrapper_path),
        dll_dir=Path(config.zmotion_dll_dir),
    )


def _create_zmotion_sdk_client_factory(config: Any):
    sdk_config = resolve_sdk_config(config)
    if sdk_config is None:
        return _missing_zmotion_client_factory
    return lambda host: ZMotionSdkClient(host=host, sdk_config=sdk_config)


def _missing_zmotion_client_factory(host: str) -> ZMotionReadableClient:
    raise RuntimeError(
        "ZMotion read-only mode needs a configured ZMotion client factory or "
        "ROBOT_ZMOTION_WRAPPER_PATH plus ROBOT_ZMOTION_DLL_DIR before it can connect "
        f"to {host}."
    )
