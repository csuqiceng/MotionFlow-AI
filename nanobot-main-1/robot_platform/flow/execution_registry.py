"""Thread-safe, persisted progress and cooperative controls for library runs."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from pathlib import Path
from threading import Condition, Thread
from typing import Any, Callable
from uuid import uuid4

from robot_platform.flow.execution_history import ExecutionHistory


def _default_execution_history_path() -> Path:
    from robot_platform.runtime import get_robot_data_dir

    return get_robot_data_dir() / "library_executions.json"
_ACTIVE_STATES = frozenset({"queued", "running", "paused", "stopping"})
_TERMINAL_STATES = frozenset({
    "completed", "failed", "stopped", "reset", "reconcile_required",
})


@dataclass
class LibraryExecution:
    execution_id: str
    steps: list[dict[str, Any]]
    kind: str = "flow"
    source_id: str = ""
    actor: str = ""
    state: str = "queued"
    message: str = ""
    result: dict[str, Any] | None = None
    created_at: str = ""
    updated_at: str = ""
    completed_at: str | None = None
    step_budget: int = field(default=0, repr=False)

    def snapshot(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "kind": self.kind,
            "source_id": self.source_id,
            "actor": self.actor,
            "state": self.state,
            "control_state": self.state,
            "message": self.message,
            "steps": [dict(item) for item in self.steps],
            "result": self.result,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "allowed_actions": self._allowed_actions(),
        }

    def _allowed_actions(self) -> list[str]:
        if self.state in {"queued", "running"}:
            return ["pause", "stop"]
        if self.state == "paused":
            return ["resume", "step", "stop"]
        if self.state in _TERMINAL_STATES:
            return ["reset"]
        return []


class LibraryExecutionRegistry:
    def __init__(self, *, history: ExecutionHistory | None = None) -> None:
        self._condition = Condition()
        self._items: dict[str, LibraryExecution] = {}
        self._history = history or ExecutionHistory(_default_execution_history_path())
        self.recovered_execution_ids = self._recover_interrupted()

    def _recover_interrupted(self) -> tuple[str, ...]:
        """Never auto-replay executions whose physical outcome may be unknown."""
        recovered: list[str] = []
        for record in self._history.list():
            if record.get("state") not in _ACTIVE_STATES:
                continue
            execution_id = str(record.get("execution_id", ""))
            if not execution_id:
                continue
            record["state"] = "reconcile_required"
            record["control_state"] = "reconcile_required"
            record["message"] = (
                "Execution was interrupted; inspect physical state before a new run."
            )
            record["allowed_actions"] = ["reset"]
            record["result"] = {
                "ok": False,
                "state": "execution_outcome_unknown",
                "message": "Execution outcome requires reconciliation.",
                "errors": [{"code": "execution_outcome_unknown"}],
            }
            self._history.upsert(record)
            recovered.append(execution_id)
        return tuple(recovered)

    def start(
        self,
        step_count: int,
        worker: Callable[..., dict[str, Any]],
        *,
        kind: str = "flow",
        source_id: str = "",
        actor: str = "",
        start_paused: bool = False,
    ) -> str:
        execution_id = uuid4().hex
        self._history.create(
            kind=kind,
            source_id=source_id,
            step_count=step_count,
            actor=actor,
            execution_id=execution_id,
        )
        stored = self._history.get(execution_id)
        assert stored is not None
        record = LibraryExecution(
            execution_id=execution_id,
            steps=list(stored["steps"]),
            kind=kind,
            source_id=source_id,
            actor=actor,
            created_at=str(stored["created_at"]),
            updated_at=str(stored["updated_at"]),
            state="paused" if start_paused else "queued",
        )
        with self._condition:
            self._items[execution_id] = record

        def update(index: int, state: str, result: dict[str, Any] | None) -> None:
            with self._condition:
                current = self._items[execution_id]
                if current.state == "queued":
                    current.state = "running"
                current.steps[index - 1] = {
                    "step_index": index,
                    "state": state,
                    **({"result": result} if result is not None else {}),
                }
                self._persist(current)

        def wait_for_step(_index: int) -> bool:
            with self._condition:
                current = self._items[execution_id]
                while current.state == "paused" and current.step_budget == 0:
                    self._condition.wait()
                if current.state == "stopping":
                    return False
                if current.step_budget:
                    current.step_budget -= 1
                return current.state in {"queued", "running", "paused"}

        def run() -> None:
            try:
                with self._condition:
                    current = self._items[execution_id]
                    if current.state == "queued":
                        current.state = "running"
                        self._persist(current)
                result = self._call_worker(worker, update, wait_for_step)
                with self._condition:
                    current = self._items[execution_id]
                    if current.state == "stopping" or result.get("state") == "flow_stopped":
                        current.state = "stopped"
                        current.message = str(result.get(
                            "message", "Stopped before the next step.",
                        ))
                        for item in current.steps:
                            if item["state"] == "queued":
                                item["state"] = "skipped"
                    elif result.get("ok"):
                        current.state = "completed"
                    else:
                        current.state = "failed"
                        current.message = str(result.get("message", "Execution failed."))
                        failed = int((result.get("data") or {}).get("failed_step_index") or 0)
                        if failed:
                            for item in current.steps[failed:]:
                                if item["state"] == "queued":
                                    item["state"] = "skipped"
                    current.result = result
                    self._persist(current, terminal=True)
                    self._condition.notify_all()
            except Exception:  # defensive boundary for a background task
                with self._condition:
                    current = self._items[execution_id]
                    current.state = "failed"
                    current.message = "Execution worker failed."
                    self._persist(current, terminal=True)
                    self._condition.notify_all()

        Thread(target=run, daemon=True).start()
        return execution_id

    @staticmethod
    def _call_worker(
        worker: Callable[..., dict[str, Any]],
        update: Callable[[int, str, dict[str, Any] | None], None],
        wait_for_step: Callable[[int], bool],
    ) -> dict[str, Any]:
        parameters = inspect.signature(worker).parameters
        return worker(update, wait_for_step) if len(parameters) >= 2 else worker(update)

    def pause(self, execution_id: str) -> dict[str, Any]:
        with self._condition:
            current = self._require_active(execution_id, {"queued", "running"})
            current.state = "paused"
            self._persist(current)
            return current.snapshot()

    def resume(self, execution_id: str) -> dict[str, Any]:
        with self._condition:
            current = self._require_active(execution_id, {"paused"})
            current.state = "running"
            current.step_budget = 0
            self._persist(current)
            self._condition.notify_all()
            return current.snapshot()

    def step_once(self, execution_id: str) -> dict[str, Any]:
        with self._condition:
            current = self._require_active(execution_id, {"paused"})
            current.step_budget += 1
            self._persist(current)
            self._condition.notify_all()
            return current.snapshot()

    def stop(self, execution_id: str) -> dict[str, Any]:
        with self._condition:
            current = self._require_active(execution_id, {"queued", "running", "paused"})
            current.state = "stopping"
            current.step_budget = 0
            self._persist(current)
            self._condition.notify_all()
            return current.snapshot()

    def reset(self, execution_id: str) -> dict[str, Any]:
        with self._condition:
            current = self._items.get(execution_id)
            if current is None:
                raise KeyError(execution_id)
            if current.state not in _TERMINAL_STATES:
                raise ValueError(f"Cannot reset execution in state '{current.state}'.")
            current.state = "reset"
            current.message = ""
            current.result = None
            current.steps = [
                {"step_index": index, "state": "queued"}
                for index in range(1, len(current.steps) + 1)
            ]
            current.completed_at = None
            self._persist(current)
            return current.snapshot()

    def get(self, execution_id: str) -> dict[str, Any] | None:
        with self._condition:
            item = self._items.get(execution_id)
            if item is not None:
                return item.snapshot()
        return self._history.get(execution_id)

    def list(self) -> list[dict[str, Any]]:
        with self._condition:
            active = {execution_id: item.snapshot() for execution_id, item in self._items.items()}
        stored = {item["execution_id"]: item for item in self._history.list()}
        stored.update(active)
        return sorted(stored.values(), key=lambda item: str(item.get("created_at", "")), reverse=True)

    def _require_active(self, execution_id: str, allowed: set[str]) -> LibraryExecution:
        current = self._items.get(execution_id)
        if current is None:
            raise KeyError(execution_id)
        if current.state not in allowed:
            raise ValueError(f"Cannot control execution in state '{current.state}'.")
        return current

    def _persist(self, current: LibraryExecution, *, terminal: bool = False) -> None:
        existing = self._history.get(current.execution_id) or {}
        current.updated_at = str(existing.get("updated_at", current.updated_at))
        snapshot = current.snapshot()
        snapshot["updated_at"] = existing.get("updated_at", snapshot["updated_at"])
        if terminal:
            from datetime import datetime, timezone
            snapshot["completed_at"] = datetime.now(timezone.utc).isoformat()
            current.completed_at = snapshot["completed_at"]
        self._history.upsert(snapshot)
        saved = self._history.get(current.execution_id)
        if saved is not None:
            current.updated_at = str(saved["updated_at"])


_registry = LibraryExecutionRegistry()


def get_library_execution_registry() -> LibraryExecutionRegistry:
    return _registry
