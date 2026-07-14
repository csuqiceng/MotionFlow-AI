from __future__ import annotations

from pathlib import Path
from threading import Event
from time import sleep

from nanobot.api.robot_routes import (
    process_robot_library_command,
    process_robot_library_commands,
    process_robot_library_component,
    process_robot_library_components,
    process_robot_library_flow,
    process_robot_library_flows,
)
from robot_ai.flow.models import FlowEntry, FlowStep
from robot_ai.flow.registry import FlowRegistry
from robot_ai.library.models import Command
from robot_ai.library.registry import CommandRegistry


def _seed(path: Path) -> None:
    reg = CommandRegistry(path)
    reg.add(Command(id="io0-off", name="IO0关闭", component_id="io_write",
                    aliases=["grip"], parameters={"io_no": 0, "io_action": 0}))
    reg.add(Command(id="home", name="home", component_id="linear_move",
                    parameters={"target_x": 1400.0, "target_y": 0.0, "target_z": 1270.0,
                                "target_rx": 0.0, "target_ry": 90.0, "target_rz": 0.0,
                                "spd_pct": 50.0, "acc_pct": 60.0, "dec_pct": 60.0,
                                "move_type": 0, "stop_cmd": 0}))


def test_list_commands_envelope_and_total(tmp_path: Path) -> None:
    commands = tmp_path / "commands.json"
    _seed(commands)
    status, result = process_robot_library_commands(commands_path=str(commands))
    assert status == 200
    assert result["ok"] is True
    assert result["data"]["total"] == 2
    assert {c["id"] for c in result["data"]["items"]} == {"io0-off", "home"}


def test_list_commands_filter_by_component(tmp_path: Path) -> None:
    commands = tmp_path / "commands.json"
    _seed(commands)
    _status, result = process_robot_library_commands(
        commands_path=str(commands), component_id="io_write"
    )
    assert [c["id"] for c in result["data"]["items"]] == ["io0-off"]


def test_list_commands_filter_by_q_matches_alias(tmp_path: Path) -> None:
    commands = tmp_path / "commands.json"
    _seed(commands)
    _status, result = process_robot_library_commands(commands_path=str(commands), q="grip")
    assert [c["id"] for c in result["data"]["items"]] == ["io0-off"]


def test_list_commands_rejects_bad_risk_level(tmp_path: Path) -> None:
    commands = tmp_path / "commands.json"
    _seed(commands)
    status, result = process_robot_library_commands(
        commands_path=str(commands), risk_level="extreme"
    )
    assert status == 400
    assert result["error"]["code"] == 400


def test_get_command_found_and_404(tmp_path: Path) -> None:
    commands = tmp_path / "commands.json"
    _seed(commands)
    s_ok, r_ok = process_robot_library_command("home", commands_path=str(commands))
    assert s_ok == 200 and r_ok["data"]["id"] == "home"
    s_miss, r_miss = process_robot_library_command("nope", commands_path=str(commands))
    assert s_miss == 404 and r_miss["error"]["code"] == 404


def test_list_components_has_four() -> None:
    status, result = process_robot_library_components()
    assert status == 200
    assert {c["id"] for c in result["data"]["items"]} == {
        "system_action", "linear_move", "delay", "io_write"
    }


def test_get_component_includes_schema_and_404() -> None:
    s_ok, r_ok = process_robot_library_component("delay")
    assert s_ok == 200
    assert any(p["name"] == "delay_sec" for p in r_ok["data"]["parameters"])
    s_miss, r_miss = process_robot_library_component("nope")
    assert s_miss == 404 and r_miss["error"]["code"] == 404


def _seed_flow(path: Path, name: str = "PickPlace", confirmed: bool = False) -> None:
    FlowRegistry(path).add(FlowEntry(
        name=name,
        description="pick and place",
        steps=[FlowStep(step_id=1, action="move", func_id=108, params={"target_z": 50.0})],
        step_delay_ms=500,
        confirmed=confirmed,
    ))


def test_flow_list_envelope(tmp_path: Path) -> None:
    flows = tmp_path / "flows.json"
    _seed_flow(flows, "PickPlace")
    status, result = process_robot_library_flows(flow_registry_path=str(flows))
    assert status == 200
    assert result["ok"] is True
    assert result["data"]["total"] == 1
    assert result["data"]["items"][0]["name"] == "PickPlace"
    assert result["data"]["items"][0]["flow_id"] == "pickplace"


def test_flow_list_empty(tmp_path: Path) -> None:
    flows = tmp_path / "flows.json"
    FlowRegistry(flows)  # creates empty registry file
    status, result = process_robot_library_flows(flow_registry_path=str(flows))
    assert status == 200
    assert result["data"]["total"] == 0
    assert result["data"]["items"] == []


def test_flow_detail_found_and_404(tmp_path: Path) -> None:
    flows = tmp_path / "flows.json"
    _seed_flow(flows, "PickPlace")
    s_ok, r_ok = process_robot_library_flow("pickplace", flow_registry_path=str(flows))
    assert s_ok == 200
    assert r_ok["data"]["name"] == "PickPlace"
    assert r_ok["data"]["steps"][0]["func_id"] == 108
    s_miss, r_miss = process_robot_library_flow("nope", flow_registry_path=str(flows))
    assert s_miss == 404
    assert r_miss["error"]["code"] == 404


def test_published_command_run_preflights_before_real_execution(tmp_path: Path, monkeypatch) -> None:
    from nanobot.api.robot_routes import process_robot_library_command_run
    from robot_ai.models import ToolResult
    import robot_ai.flow.executor as executor

    commands = tmp_path / "commands.json"
    _seed(commands)
    seen = []

    def fake_runner(*, request, **_kwargs):
        seen.append(request)
        return ToolResult.success(state="ok", data={"real_execution": request.execute_real}).to_dict()

    monkeypatch.setattr(executor, "run_zmotion_operator_command", fake_runner)
    status, result = process_robot_library_command_run("home", commands_path=str(commands))
    assert status == 200 and result["ok"] is True
    assert [request.execute_real for request in seen] == [False, True]


def test_missing_command_run_does_not_call_controller(tmp_path: Path, monkeypatch) -> None:
    from nanobot.api.robot_routes import process_robot_library_command_run
    import robot_ai.flow.executor as executor

    seen = []
    monkeypatch.setattr(executor, "run_zmotion_operator_command", lambda **kwargs: seen.append(kwargs))
    status, result = process_robot_library_command_run("missing", commands_path=str(tmp_path / "commands.json"))
    assert status == 404
    assert result["error"]["code"] == "command_not_found"
    assert seen == []


def test_library_execution_status_reports_real_completed_steps(tmp_path: Path, monkeypatch) -> None:
    """A background library run exposes each completed controller step."""
    from nanobot.api.robot_routes import (
        process_robot_library_command_execution,
        process_robot_library_execution_status,
    )
    from robot_ai.models import ToolResult
    import robot_ai.flow.executor as executor

    commands = tmp_path / "commands.json"
    _seed(commands)
    monkeypatch.setattr(
        executor,
        "run_zmotion_operator_command",
        lambda *, request, **_kwargs: ToolResult.success(
            state="ok", data={"real_execution": request.execute_real}
        ).to_dict(),
    )

    status, started = process_robot_library_command_execution("home", commands_path=str(commands))
    assert status == 202
    execution_id = started["data"]["execution_id"]

    import time
    for _ in range(50):
        status, current = process_robot_library_execution_status(execution_id)
        if current["data"]["state"] in {"completed", "failed"}:
            break
        time.sleep(0.01)

    assert status == 200
    assert current["data"]["state"] == "completed"
    assert current["data"]["steps"][0]["step_index"] == 1
    assert current["data"]["steps"][0]["state"] == "succeeded"
    assert current["data"]["steps"][0]["result"]["data"]["real_execution"] is True


def test_library_execution_control_routes_pause_step_stop_and_list(tmp_path: Path, monkeypatch) -> None:
    from nanobot.api.robot_routes import (
        process_robot_library_execution_control,
        process_robot_library_execution_list,
    )
    import robot_ai.flow.execution_registry as execution_registry
    from robot_ai.flow.execution_history import ExecutionHistory
    from robot_ai.flow.execution_registry import LibraryExecutionRegistry

    registry = LibraryExecutionRegistry(history=ExecutionHistory(tmp_path / "history.json"))
    monkeypatch.setattr(execution_registry, "_registry", registry)
    first_done = Event()
    release_second = Event()

    def worker(on_step, wait_for_step):
        assert wait_for_step(1)
        on_step(1, "succeeded", {"ok": True})
        first_done.set()
        assert release_second.wait(1)
        if not wait_for_step(2):
            return {"ok": False, "state": "flow_stopped", "message": "Stopped by engineer."}
        on_step(2, "succeeded", {"ok": True})
        return {"ok": True}

    execution_id = registry.start(2, worker, kind="flow", source_id="controlled-flow")
    assert first_done.wait(1)

    status, paused = process_robot_library_execution_control(execution_id, action="pause")
    assert status == 200
    assert paused["data"]["state"] == "paused"
    release_second.set()
    sleep(0.05)
    status, stepped = process_robot_library_execution_control(execution_id, action="step")
    assert status == 200
    assert stepped["data"]["state"] == "paused"
    status, stopped = process_robot_library_execution_control(execution_id, action="stop")
    assert status == 200
    assert stopped["data"]["state"] == "stopping"

    for _ in range(100):
        status, listed = process_robot_library_execution_list()
        current = next(item for item in listed["data"]["items"] if item["execution_id"] == execution_id)
        if current["state"] == "stopped":
            break
        sleep(0.01)
    assert status == 200
    assert current["state"] == "stopped"
    assert current["source_id"] == "controlled-flow"


def test_library_execution_control_rejects_unknown_action_and_unknown_execution() -> None:
    from nanobot.api.robot_routes import process_robot_library_execution_control

    status, invalid = process_robot_library_execution_control("missing", action="dance")
    assert status == 400
    assert invalid["error"]["code"] == "invalid_execution_action"

    status, missing = process_robot_library_execution_control("missing", action="pause")
    assert status == 404
    assert missing["error"]["code"] == "execution_not_found"
