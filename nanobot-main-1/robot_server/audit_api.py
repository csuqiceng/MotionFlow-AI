"""Engineer-visible audit log projection for the robot platform."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from robot_server.identity_api import RobotIdentityService


class RobotAuditService:
    def __init__(self, data_dir: Path, identity: RobotIdentityService) -> None:
        self._audit_path = data_dir / "audit.jsonl"
        self._identity = identity

    def list(self, token: str, *, limit: str = "50", before: str = "") -> tuple[int, dict[str, Any]]:
        _session, error = self._identity.require_engineer_session(token)
        if error is not None:
            return error
        try:
            page_size = max(1, min(int(limit), 100))
        except (TypeError, ValueError):
            return _invalid("limit must be an integer")
        cursor = _decode_cursor(before)
        if before and cursor is None:
            return _invalid("malformed audit cursor")
        entries = self._entries()
        if cursor is not None:
            entries = [entry for entry in entries if _sort_key(entry) < cursor]
        page = entries[:page_size]
        next_cursor = _encode_cursor(_sort_key(page[-1])) if len(entries) > len(page) else None
        return 200, {"ok": True, "data": {"items": page, "next": next_cursor}}

    def _entries(self) -> list[dict[str, Any]]:
        if not self._audit_path.is_file():
            return []
        entries: list[dict[str, Any]] = []
        for line in self._audit_path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                entries.append(entry)
        return sorted(entries, key=_sort_key, reverse=True)


def _sort_key(entry: dict[str, Any]) -> tuple[str, str]:
    return str(entry.get("timestamp", "")), str(entry.get("audit_id") or entry.get("migration_id") or "")


def _encode_cursor(cursor: tuple[str, str]) -> str:
    return base64.urlsafe_b64encode(json.dumps(cursor).encode("utf-8")).decode("ascii")


def _decode_cursor(value: str) -> tuple[str, str] | None:
    try:
        decoded = json.loads(base64.urlsafe_b64decode(value.encode("ascii")).decode("utf-8"))
    except Exception:
        return None
    if not isinstance(decoded, list) or len(decoded) != 2:
        return None
    return str(decoded[0]), str(decoded[1])


def _invalid(message: str) -> tuple[int, dict[str, Any]]:
    return 400, {"error": {"code": "invalid_request", "message": message}}
