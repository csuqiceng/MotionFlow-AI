from __future__ import annotations

from pathlib import Path
from threading import Event
from time import sleep

from robot_ai.flow.execution_history import ExecutionHistory
from robot_ai.flow.execution_registry import LibraryExecutionRegistry


def test_execution_history_survives_reload_with_step_results(tmp_path: Path) -> None:
    path = tmp_path / "execution-history.json"
    history = ExecutionHistory(path)

    execution_id = history.create(
        kind="flow",
        source_id="delay-flow",
        step_count=2,
        actor="engineer",
    )
    history.mark_step(execution_id, 1, "succeeded", {"ok": True})
    history.finish(execution_id, "completed", {"ok": True})

    reloaded = ExecutionHistory(path).get(execution_id)
    assert reloaded is not None
    assert reloaded["kind"] == "flow"
    assert reloaded["source_id"] == "delay-flow"
    assert reloaded["actor"] == "engineer"
    assert reloaded["steps"][0]["state"] == "succeeded"
    assert reloaded["result"] == {"ok": True}
    assert reloaded["state"] == "completed"


def test_execution_history_retains_only_the_newest_records(tmp_path: Path) -> None:
    history = ExecutionHistory(tmp_path / "execution-history.json", max_records=2)
    first = history.create(kind="command", source_id="first", step_count=1)
    second = history.create(kind="command", source_id="second", step_count=1)
    third = history.create(kind="command", source_id="third", step_count=1)

    assert history.get(first) is None
    assert [item["execution_id"] for item in history.list()] == [third, second]


def test_execution_registry_pauses_steps_allows_one_step_then_stops(tmp_path: Path) -> None:
    registry = LibraryExecutionRegistry(history=ExecutionHistory(tmp_path / "history.json"))
    first_done = Event()
    allow_second_checkpoint = Event()
    second_done = Event()

    def worker(on_step, wait_for_step):
        assert wait_for_step(1) is True
        on_step(1, "succeeded", {"ok": True})
        first_done.set()
        assert allow_second_checkpoint.wait(1)
        assert wait_for_step(2) is True
        on_step(2, "succeeded", {"ok": True})
        second_done.set()
        assert wait_for_step(3) is False
        return {"ok": False, "state": "flow_stopped", "message": "Stopped by engineer."}

    execution_id = registry.start(3, worker, kind="flow", source_id="controlled")
    assert first_done.wait(1)
    assert registry.pause(execution_id)["state"] == "paused"
    allow_second_checkpoint.set()
    sleep(0.05)
    assert second_done.is_set() is False

    assert registry.step_once(execution_id)["state"] == "paused"
    assert second_done.wait(1)
    assert registry.stop(execution_id)["state"] == "stopping"

    for _ in range(100):
        current = registry.get(execution_id)
        assert current is not None
        if current["state"] == "stopped":
            break
        sleep(0.01)
    assert current["state"] == "stopped"
    assert current["steps"][0]["state"] == "succeeded"
    assert current["steps"][1]["state"] == "succeeded"
    assert current["steps"][2]["state"] == "skipped"
