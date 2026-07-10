from __future__ import annotations

from dataclasses import dataclass


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

    def get(self, session_key: str | None) -> SessionState:
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
        s = self.get(session_key)
        s.pending_plan_id = plan_id
        s.confirmed = False

    def confirm(self, session_key: str | None, plan_id: str) -> bool:
        s = self.get(session_key)
        if s.pending_plan_id != plan_id:
            return False
        s.confirmed = True
        return True

    def is_confirmed(self, session_key: str | None, plan_id: str) -> bool:
        s = self.get(session_key)
        return s.confirmed and s.pending_plan_id == plan_id
