from __future__ import annotations

from dataclasses import dataclass, replace
import threading


@dataclass
class SessionState:
    session_key: str
    logged_in: bool = True  # POC: single-user, default True
    operator_permission: bool = True
    wake_word_valid: bool = True
    pending_plan_id: str | None = None
    confirmed: bool = False


class SessionGateStore:
    """Per-session gate state. POC: in-memory, default-allow for CLI."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}
        self._lock = threading.RLock()

    def get(self, session_key: str | None) -> SessionState:
        with self._lock:
            # Compatibility API: callers historically receive the stable
            # per-session object. New read-only consumers should use snapshot().
            return self._get_locked(session_key)

    def snapshot(self, session_key: str | None) -> SessionState:
        with self._lock:
            return replace(self._get_locked(session_key))

    def restore_if_current(
        self,
        session_key: str | None,
        failed_plan_id: str,
        previous: SessionState,
    ) -> bool:
        """Rollback a failed staging write without erasing a newer plan."""
        with self._lock:
            current = self._get_locked(session_key)
            if current.pending_plan_id != failed_plan_id:
                return False
            # Only undo the plan fields written by set_pending_plan().  Other
            # session gates may have been revoked concurrently and must never
            # be resurrected by a staging rollback.  Mutating in place also
            # preserves the stable object identity of get().
            current.pending_plan_id = previous.pending_plan_id
            current.confirmed = previous.confirmed
            return True

    def _get_locked(self, session_key: str | None) -> SessionState:
        if not session_key:
            # CLI / no-session path: default-allow (single-user POC). Cached so
            # set_pending_plan/confirm persist across calls within one process.
            key = "_cli_"
        else:
            key = session_key
        if key not in self._sessions:
            self._sessions[key] = SessionState(session_key=key)
        return self._sessions[key]

    def set_pending_plan(self, session_key: str | None, plan_id: str) -> None:
        with self._lock:
            s = self._get_locked(session_key)
            s.pending_plan_id = plan_id
            s.confirmed = False

    def clear_pending_plan(self, session_key: str | None, plan_id: str) -> bool:
        with self._lock:
            s = self._get_locked(session_key)
            if s.pending_plan_id != plan_id:
                return False
            s.pending_plan_id = None
            s.confirmed = False
            return True

    def confirm(self, session_key: str | None, plan_id: str) -> bool:
        with self._lock:
            s = self._get_locked(session_key)
            if s.pending_plan_id != plan_id:
                return False
            s.confirmed = True
            return True

    def is_confirmed(self, session_key: str | None, plan_id: str) -> bool:
        with self._lock:
            s = self._get_locked(session_key)
            return s.confirmed and s.pending_plan_id == plan_id
