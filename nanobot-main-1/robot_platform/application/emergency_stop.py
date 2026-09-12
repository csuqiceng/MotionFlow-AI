"""Dedicated emergency-stop use case, separate from normal execution permits."""

from __future__ import annotations

from copy import deepcopy
import queue
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from robot_platform.application.principal import AuthenticatedPrincipal


@dataclass(frozen=True)
class RobotEmergencyStopCommand:
    principal: AuthenticatedPrincipal

    def __post_init__(self) -> None:
        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError("RobotEmergencyStopCommand requires AuthenticatedPrincipal")


@dataclass(frozen=True)
class RobotEmergencyStopError:
    code: str
    message: str

    def __post_init__(self) -> None:
        if not self.code.strip() or not self.message.strip():
            raise ValueError("RobotEmergencyStopError requires code and message")


@dataclass(frozen=True)
class RobotEmergencyStopResponse:
    payload: dict[str, Any] | None = None
    error: RobotEmergencyStopError | None = None

    def __post_init__(self) -> None:
        if (self.payload is None) == (self.error is None):
            raise ValueError(
                "RobotEmergencyStopResponse requires exactly one of payload or error"
            )
        if self.payload is not None and not isinstance(self.payload, dict):
            raise TypeError("RobotEmergencyStopResponse payload must be a dict")

    @property
    def ok(self) -> bool:
        return self.payload is not None


class EmergencyStopPort(Protocol):
    def emergency_stop(
        self,
        principal: AuthenticatedPrincipal,
        *,
        operation_id: str,
        on_late_outcome: Callable[[bool, str], None],
    ) -> dict[str, Any]: ...


class EmergencyStopAuditOutboxPort(Protocol):
    def append(self, event: dict[str, Any]) -> None: ...


class RobotEmergencyStopApplicationPort(Protocol):
    def execute(
        self, command: RobotEmergencyStopCommand,
    ) -> RobotEmergencyStopResponse: ...


_AUDIT_STOP = object()


@dataclass
class EmergencyStopApplicationService:
    """Dispatch a stop first; audit and response normalization are secondary."""

    port: EmergencyStopPort
    audit_outbox: EmergencyStopAuditOutboxPort | None = None
    audit_queue_capacity: int = 256
    _audit_queue: queue.Queue[Any] = field(init=False)
    _failed_audit: list[dict[str, Any]] = field(default_factory=list, init=False)
    _failed_lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _worker: threading.Thread | None = field(default=None, init=False)
    _closed: bool = field(default=False, init=False)
    _dropped_audit_count: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self._audit_queue = queue.Queue(maxsize=max(1, int(self.audit_queue_capacity)))
        if self.audit_outbox is not None:
            self._worker = threading.Thread(
                target=self._audit_worker,
                name="emergency-stop-audit",
                daemon=True,
            )
            self._worker.start()
            if self._uses_durable_spool():
                self._wake_audit_worker()

    def execute(
        self, command: RobotEmergencyStopCommand,
    ) -> RobotEmergencyStopResponse:
        if not isinstance(command, RobotEmergencyStopCommand):
            return _failure("invalid_emergency_stop_request", "Emergency stop request is invalid.")
        principal = command.principal
        operation_id = f"estop-{secrets.token_urlsafe(16)}"
        self._record({
            "event": "emergency_stop_requested",
            "operation_id": operation_id,
            "actor_id": principal.actor_id,
            "session_id": principal.session_id,
            "timestamp": time.time(),
        })
        def record_late_outcome(ok: bool, state: str) -> None:
            safe_state = (
                state if isinstance(state, str)
                and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", state) else "unknown"
            )
            self._record({
                "event": "emergency_stop_result_late",
                "operation_id": operation_id,
                "ok": bool(ok),
                "state": safe_state,
                "timestamp": time.time(),
            })
        try:
            raw = self.port.emergency_stop(
                principal,
                operation_id=operation_id,
                on_late_outcome=record_late_outcome,
            )
            payload = _normalize_result(raw, operation_id)
        except Exception:
            self._record({
                "event": "emergency_stop_result_unknown",
                "operation_id": operation_id,
                "timestamp": time.time(),
            })
            return _failure(
                "emergency_stop_outcome_unknown",
                "Emergency stop outcome is unknown; use the physical emergency stop.",
            )
        self._record({
            "event": "emergency_stop_result",
            "operation_id": operation_id,
            "ok": payload["ok"],
            "state": payload["state"],
            "timestamp": time.time(),
        })
        return RobotEmergencyStopResponse(payload=payload)

    def flush_audit(self) -> None:
        """Test/maintenance hook; never called from an emergency request path."""
        self._audit_queue.join()
        if self.audit_outbox is None:
            return
        flush_spool = getattr(self.audit_outbox, "flush_spool", None)
        if callable(flush_spool):
            flush_spool()
            return
        with self._failed_lock:
            pending = list(self._failed_audit)
            self._failed_audit.clear()
        for index, event in enumerate(pending):
            try:
                self.audit_outbox.append(event)
            except Exception:
                with self._failed_lock:
                    remaining_capacity = max(
                        0, self.audit_queue_capacity - len(self._failed_audit)
                    )
                    self._failed_audit[0:0] = pending[index:index + remaining_capacity]
                return

    def close(self, *, timeout: float = 1.0) -> None:
        """Stop accepting audit work without delaying process shutdown."""
        if self._closed:
            return
        self._closed = True
        if self._worker is None:
            return
        try:
            self._audit_queue.put_nowait(_AUDIT_STOP)
        except queue.Full:
            # The daemon may be blocked in durable I/O. Shutdown must remain
            # bounded; it will observe _closed after its current append.
            pass
        self._worker.join(timeout=max(0.0, float(timeout)))

    @property
    def dropped_audit_count(self) -> int:
        return self._dropped_audit_count

    def _record(self, event: dict[str, Any]) -> None:
        if self.audit_outbox is None or self._closed:
            return
        spool = getattr(self.audit_outbox, "spool", None)
        if callable(spool):
            try:
                accepted = spool(dict(event)) is True
            except Exception:
                accepted = False
            if not accepted:
                self._dropped_audit_count += 1
                return
            self._wake_audit_worker()
            return
        try:
            self._audit_queue.put_nowait(dict(event))
        except queue.Full:
            self._dropped_audit_count += 1

    def _audit_worker(self) -> None:
        assert self.audit_outbox is not None
        try:
            self._audit_worker_loop()
        finally:
            close_outbox = getattr(self.audit_outbox, "close", None)
            if callable(close_outbox):
                close_outbox()

    def _audit_worker_loop(self) -> None:
        assert self.audit_outbox is not None
        while True:
            event = self._audit_queue.get()
            try:
                if event is _AUDIT_STOP:
                    return
                flush_spool = getattr(self.audit_outbox, "flush_spool", None)
                if callable(flush_spool):
                    flush_spool()
                else:
                    self.audit_outbox.append(event)
            except Exception:
                if self._uses_durable_spool():
                    if not self._closed:
                        time.sleep(0.05)
                        self._wake_audit_worker()
                else:
                    with self._failed_lock:
                        if len(self._failed_audit) < self.audit_queue_capacity:
                            self._failed_audit.append(event)
                        else:
                            self._dropped_audit_count += 1
            finally:
                self._audit_queue.task_done()
            if self._closed and self._audit_queue.empty():
                return

    def _uses_durable_spool(self) -> bool:
        return bool(
            self.audit_outbox is not None
            and callable(getattr(self.audit_outbox, "spool", None))
            and callable(getattr(self.audit_outbox, "flush_spool", None))
        )

    def _wake_audit_worker(self) -> None:
        try:
            self._audit_queue.put_nowait(None)
        except queue.Full:
            # One queued wake is enough: flush_spool drains every durable slot.
            pass


def _normalize_result(raw: Any, operation_id: str) -> dict[str, Any]:
    if not isinstance(raw, dict) or not isinstance(raw.get("ok"), bool):
        raise ValueError("invalid emergency stop port response")
    state = raw.get("state")
    if (
        not isinstance(state, str)
        or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", state.strip()) is None
    ):
        raise ValueError("invalid emergency stop state")
    raw_data = raw.get("data")
    data = deepcopy(raw_data) if isinstance(raw_data, dict) else {}
    # Only product-neutral fields cross the Application boundary. Vendor SDK
    # exception details, controller paths and hosts are never returned.
    public_data = {
        key: data[key]
        for key in ("action", "trigger_submitted", "write_count", "simulated")
        if key in data
    }
    public_data["emergency_stop_operation_id"] = operation_id
    ok = raw["ok"] is True
    return {
        "ok": ok,
        "state": state.strip(),
        "message": (
            "Emergency stop request dispatched."
            if ok else "Emergency stop could not be confirmed; use the physical emergency stop."
        ),
        "data": public_data,
    }


def _failure(code: str, message: str) -> RobotEmergencyStopResponse:
    return RobotEmergencyStopResponse(error=RobotEmergencyStopError(code, message))
