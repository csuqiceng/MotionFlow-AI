from __future__ import annotations

from pathlib import Path

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
