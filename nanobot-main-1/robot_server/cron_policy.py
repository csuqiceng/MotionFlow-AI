"""Robot-server identity policy adapter for neutral Cron Tool mutations."""

from __future__ import annotations

from typing import Any

from nanobot.cron.application import CronMutationPolicyPort


class RobotIdentityCronMutationPolicy(CronMutationPolicyPort):
    def __init__(self, session_store: Any) -> None:
        self._session_store = session_store

    def password_change_required(self, origin_metadata: dict[str, Any]) -> bool:
        token = origin_metadata.get("user_token")
        if not isinstance(token, str) or not token:
            return False
        session = self._session_store.check(token)
        return bool(session and session.get("must_change_password"))
