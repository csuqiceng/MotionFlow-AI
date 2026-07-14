"""Thread-safe, in-memory progress records for library executions."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock, Thread
from typing import Any, Callable
from uuid import uuid4


@dataclass
class LibraryExecution:
    execution_id: str
    steps: list[dict[str, Any]]
    state: str = "queued"
    message: str = ""
    result: dict[str, Any] | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "state": self.state,
            "message": self.message,
            "steps": [dict(item) for item in self.steps],
            "result": self.result,
        }


class LibraryExecutionRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._items: dict[str, LibraryExecution] = {}

    def start(self, step_count: int, worker: Callable[[Callable[[int, str, dict[str, Any] | None], None]], dict[str, Any]]) -> str:
        execution_id = uuid4().hex
        record = LibraryExecution(
            execution_id=execution_id,
            steps=[{"step_index": index, "state": "queued"} for index in range(1, step_count + 1)],
        )
        with self._lock:
            self._items[execution_id] = record

        def update(index: int, state: str, result: dict[str, Any] | None) -> None:
            with self._lock:
                current = self._items[execution_id]
                current.state = "running"
                current.steps[index - 1] = {"step_index": index, "state": state, **({"result": result} if result is not None else {})}

        def run() -> None:
            try:
                result = worker(update)
                with self._lock:
                    current = self._items[execution_id]
                    current.result = result
                    if result.get("ok"):
                        current.state = "completed"
                    else:
                        current.state = "failed"
                        current.message = str(result.get("message", "Execution failed."))
                        failed = int((result.get("data") or {}).get("failed_step_index") or 0)
                        if failed:
                            for item in current.steps[failed:]:
                                if item["state"] == "queued":
                                    item["state"] = "skipped"
            except Exception as exc:  # defensive boundary for a background task
                with self._lock:
                    current = self._items[execution_id]
                    current.state = "failed"
                    current.message = str(exc)

        Thread(target=run, daemon=True).start()
        return execution_id

    def get(self, execution_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._items.get(execution_id)
            return item.snapshot() if item is not None else None


_registry = LibraryExecutionRegistry()


def get_library_execution_registry() -> LibraryExecutionRegistry:
    return _registry
