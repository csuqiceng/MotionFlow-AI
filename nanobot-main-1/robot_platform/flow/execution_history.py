"""Durable, bounded history for command and flow executions."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ExecutionHistory:
    """JSON-backed execution records with atomic writes and bounded retention."""

    def __init__(self, path: str | Path, *, max_records: int = 1000) -> None:
        self.path = Path(path)
        self.max_records = max(1, int(max_records))
        self._lock = RLock()
        self._items: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        items = payload.get("items", []) if isinstance(payload, dict) else []
        if not isinstance(items, list):
            return
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("execution_id"), str):
                self._items[item["execution_id"]] = self._clone(item)
        self._trim()

    @staticmethod
    def _clone(value: dict[str, Any]) -> dict[str, Any]:
        return json.loads(json.dumps(value, ensure_ascii=False))

    def _trim(self) -> None:
        ordered = sorted(
            self._items.values(),
            key=lambda item: str(item.get("created_at", "")),
            reverse=True,
        )
        self._items = {
            str(item["execution_id"]): item
            for item in ordered[: self.max_records]
        }

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "updated_at": _now(),
            "items": self.list(),
        }
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(self.path.parent),
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            delete=False,
        ) as staging:
            json.dump(payload, staging, ensure_ascii=False, indent=2)
            staging.flush()
            os.fsync(staging.fileno())
            tmp_name = staging.name
        os.replace(tmp_name, self.path)

    def create(
        self,
        *,
        kind: str,
        source_id: str,
        step_count: int,
        actor: str = "",
        execution_id: str | None = None,
    ) -> str:
        with self._lock:
            execution_id = execution_id or uuid4().hex
            timestamp = _now()
            self._items[execution_id] = {
                "execution_id": execution_id,
                "kind": kind,
                "source_id": source_id,
                "actor": actor,
                "state": "queued",
                "control_state": "running",
                "message": "",
                "result": None,
                "steps": [
                    {"step_index": index, "state": "queued"}
                    for index in range(1, max(0, int(step_count)) + 1)
                ],
                "created_at": timestamp,
                "updated_at": timestamp,
                "completed_at": None,
            }
            self._trim()
            self._save()
            return execution_id

    def get(self, execution_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._items.get(execution_id)
            return self._clone(item) if item is not None else None

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                self._clone(item)
                for item in sorted(
                    self._items.values(),
                    key=lambda value: str(value.get("created_at", "")),
                    reverse=True,
                )
            ]

    def mark_step(
        self,
        execution_id: str,
        step_index: int,
        state: str,
        result: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            item = self._require(execution_id)
            item["state"] = "running" if item["state"] == "queued" else item["state"]
            item["steps"][step_index - 1] = {
                "step_index": step_index,
                "state": state,
                **({"result": self._clone(result)} if result is not None else {}),
            }
            self._touch(item)
            self._save()

    def finish(
        self,
        execution_id: str,
        state: str,
        result: dict[str, Any] | None,
        message: str = "",
    ) -> None:
        with self._lock:
            item = self._require(execution_id)
            item["state"] = state
            item["message"] = message
            item["result"] = self._clone(result) if result is not None else None
            item["completed_at"] = _now()
            self._touch(item)
            self._save()

    def upsert(self, record: dict[str, Any]) -> None:
        execution_id = record.get("execution_id")
        if not isinstance(execution_id, str) or not execution_id:
            raise ValueError("execution_id is required")
        with self._lock:
            item = self._clone(record)
            item.setdefault("updated_at", _now())
            self._items[execution_id] = item
            self._trim()
            self._save()

    @staticmethod
    def _touch(item: dict[str, Any]) -> None:
        item["updated_at"] = _now()

    def _require(self, execution_id: str) -> dict[str, Any]:
        item = self._items.get(execution_id)
        if item is None:
            raise KeyError(execution_id)
        return item
