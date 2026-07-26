"""Optional ZMotion backend registration for product composition roots."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from robot_platform.backends.contracts import RobotBackend
from robot_platform.backends.registry import BackendRegistry
from robot_platform.backends.zmotion_backend import ZMotionReadableClient, ZMotionReadOnlyBackend
from robot_platform.backends.zmotion_sdk import ZMotionSdkClient, ZMotionSdkConfig
from robot_platform.backends.zmotion_shared_client import shared_client_enabled


def register_zmotion_backends(registry: BackendRegistry) -> None:
    """Attach the ZMotion modes to a registry owned by a product composition root."""
    registry.register(
        "zmotion_readonly",
        _create_zmotion_readonly,
        aliases=("zreadonly", "real_readonly"),
    )


def _create_zmotion_readonly(
    config: Any,
    *,
    client_factory: Any = None,
    **options: Any,
) -> RobotBackend:
    if client_factory is not None:
        return ZMotionReadOnlyBackend(host=config.controller_host, client_factory=client_factory)
    if shared_client_enabled():
        from robot_platform.backends import zmotion_shared_client as shared

        sdk_config = resolve_sdk_config(config)
        if sdk_config is None:
            return ZMotionReadOnlyBackend(
                host=config.controller_host,
                client_factory=_missing_zmotion_client_factory,
            )
        shared.configure(config.controller_host, sdk_config)
        return ZMotionReadOnlyBackend(host=config.controller_host, use_shared=True)
    return ZMotionReadOnlyBackend(
        host=config.controller_host,
        client_factory=_create_zmotion_sdk_client_factory(config),
    )


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
