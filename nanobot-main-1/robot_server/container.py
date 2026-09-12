"""Runtime dependency container passed to the HTTP interface.

This module contains no construction logic.  Concrete implementations are
selected only by :mod:`robot_server.bootstrap`; the aiohttp adapter merely
publishes already-built objects through its typed application keys.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any


@dataclass(frozen=True)
class RuntimeContainer:
    """One process-wide object graph owned by the robot server runtime."""

    # These are intentionally structural during the migration. Stable Protocol
    # types replace ``Any`` as each use-case family moves into Application.
    config: Any
    runtime_data_dir: Path
    platform: Any
    pending_plans: Any
    session_gates: Any
    execution_permits: Any
    status_service: Any
    diagnostics_service: Any
    dry_run_service: Any
    emergency_stop_service: Any
    motion_service: Any
    operation_service: Any
    library_service: Any
    identity_service: Any
    command_management: Any
    flow_management: Any
    audit_service: Any
    library_transfer: Any
    position_maintenance: Any
    execution_service: Any
    product_profile: Any
    agent_runtime: Any
    ui_state: Any
    settings: Any
    automations: Any
    apps: Any
    media: Any
    io_service: Any = None
    knowledge_service: Any = None
    position_service: Any = None
    library_mutation_service: Any = None
    library_catalog_service: Any = None
    library_management_service: Any = None
    library_transfer_service: Any = None
    position_maintenance_service: Any = None
    flow_service: Any = None
    flow_execution_service: Any = None
    flow_management_service: Any = None
    library_execution_service: Any = None
    feature_policy: Any = None
    _cleanup_callbacks: tuple[Callable[[], None], ...] = field(
        default=(), repr=False, compare=False,
    )
    _close_lock: Lock = field(
        default_factory=Lock, init=False, repr=False, compare=False,
    )
    _closed: bool = field(default=False, init=False, repr=False, compare=False)

    def close(self) -> None:
        """Release composition-owned resources in reverse construction order."""
        with self._close_lock:
            if self._closed:
                return
            object.__setattr__(self, "_closed", True)
        first_error: BaseException | None = None
        for callback in reversed(self._cleanup_callbacks):
            try:
                callback()
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error
