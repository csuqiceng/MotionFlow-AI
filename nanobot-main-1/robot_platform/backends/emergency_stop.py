"""Minimal product emergency-stop dispatcher.

This path deliberately does not enter normal planning, status reads, L1 gates,
PendingPlan, or execution-permit handling.  Its one-use authority is claimed
immediately before the smallest controller write sequence.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Protocol

from robot_platform.application import AuthenticatedPrincipal
from robot_platform.backends.factory import RobotBackendConfig
from robot_platform.execution.emergency_stop import EmergencyStopAuthority


class EmergencyWriteClient(Protocol):
    connected: bool

    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def dispatch_emergency_stop(self, claim_authority: Any) -> int: ...


class ProductEmergencyStopAdapter:
    def __init__(
        self,
        *,
        config: RobotBackendConfig,
        client_factory: Callable[[RobotBackendConfig], EmergencyWriteClient] | None = None,
        dispatch_timeout_sec: float = 2.0,
    ) -> None:
        self._config = config
        self._authority = EmergencyStopAuthority()
        self._client_factory = client_factory
        self._dispatch_timeout_sec = max(0.01, float(dispatch_timeout_sec))
        self._inflight_lock = threading.Lock()
        self._inflight = False

    def emergency_stop(
        self,
        principal: AuthenticatedPrincipal,
        *,
        operation_id: str = "",
        on_late_outcome: Callable[[bool, str], None] | None = None,
    ) -> dict[str, Any]:
        del operation_id
        mode = self._config.mode.strip().lower()
        if mode in {"simulation", "sim"}:
            token = self._authority.issue(principal)
            if not self._authority.claim(token):
                raise RuntimeError("emergency stop authority unavailable")
            return {
                "ok": True,
                "state": "simulated_system_action_completed",
                "data": {
                    "action": "emergency_stop",
                    "trigger_submitted": True,
                    "write_count": 0,
                    "simulated": True,
                },
            }
        if mode not in {"zmotion_readonly", "zreadonly", "real_readonly"}:
            raise RuntimeError("selected backend has no emergency-stop dispatcher")
        with self._inflight_lock:
            if self._inflight:
                return {
                    "ok": False,
                    "state": "emergency_stop_dispatch_in_progress",
                    "data": {"action": "emergency_stop", "trigger_submitted": False},
                }
            self._inflight = True
        completed = threading.Event()
        outcome: list[Any] = []
        deadline = time.monotonic() + self._dispatch_timeout_sec
        outcome_lock = threading.Lock()
        caller_returned = False

        def dispatch() -> None:
            nonlocal caller_returned
            try:
                result: Any = self._dispatch_zmotion(principal, deadline=deadline)
            except BaseException as exc:
                result = exc
            finally:
                with outcome_lock:
                    outcome.append(result)
                    notify_late = caller_returned
                with self._inflight_lock:
                    self._inflight = False
                completed.set()
                if notify_late and on_late_outcome is not None:
                    if isinstance(result, dict):
                        on_late_outcome(
                            result.get("ok") is True,
                            str(result.get("state") or "unknown"),
                        )
                    else:
                        on_late_outcome(False, "emergency_stop_outcome_unknown")

        threading.Thread(
            target=dispatch, name="zmotion-emergency-stop", daemon=True,
        ).start()
        if not completed.wait(self._dispatch_timeout_sec):
            with outcome_lock:
                caller_returned = True
                if outcome:
                    completed.set()
            if completed.is_set() and outcome:
                result = outcome[0]
                if isinstance(result, BaseException):
                    raise result
                return result
            # A currently blocked SDK call cannot be killed safely.  The worker
            # will abort before issuing authority/first write if connect returns
            # after this deadline. The caller must use the physical E-stop.
            raise TimeoutError("emergency stop dispatch deadline exceeded")
        result = outcome[0]
        if isinstance(result, BaseException):
            raise result
        return result

    def _dispatch_zmotion(
        self, principal: AuthenticatedPrincipal, *, deadline: float,
    ) -> dict[str, Any]:
        from robot_platform.backends.zmotion_sdk import ZMotionSdkClient
        from robot_platform.backends.zmotion_shared_client import shared_client_enabled

        use_shared = self._client_factory is None and shared_client_enabled()
        client: EmergencyWriteClient | None = None
        try:
            if self._client_factory is not None:
                client = self._client_factory(self._config)
                client.connect()
            elif use_shared:
                from robot_platform.backends import zmotion_shared_client as shared
                from robot_platform.backends.zmotion_plugin import resolve_sdk_config

                sdk_config = resolve_sdk_config(self._config)
                if sdk_config is None:
                    raise RuntimeError("ZMotion emergency-stop SDK is not configured")
                if not shared.is_configured():
                    shared.configure(self._config.controller_host, sdk_config)
                client = shared.get()
            else:
                from robot_platform.backends.zmotion_plugin import resolve_sdk_config

                sdk_config = resolve_sdk_config(self._config)
                if sdk_config is None:
                    raise RuntimeError("ZMotion emergency-stop SDK is not configured")
                client = ZMotionSdkClient(
                    host=self._config.controller_host, sdk_config=sdk_config,
                )
                client.connect()

            # No status/echo read may appear between this one-use claim and the
            # minimum Func104 parameter+trigger writes.
            if time.monotonic() >= deadline:
                raise TimeoutError("emergency stop dispatch deadline exceeded")
            token = self._authority.issue(principal)
            dispatch = getattr(client, "dispatch_emergency_stop", None)
            if not callable(dispatch):
                raise RuntimeError(
                    "selected controller client lacks atomic emergency-stop dispatch"
                )
            submitted = int(dispatch(lambda: self._authority.claim(token)))
            return {
                "ok": True,
                "state": "emergency_stop_dispatched",
                "data": {
                    "action": "emergency_stop",
                    "trigger_submitted": True,
                    "write_count": submitted,
                    "simulated": False,
                },
            }
        finally:
            if client is not None and not use_shared:
                try:
                    client.disconnect()
                except Exception:
                    pass
