from robot_ai.backends.simulation_backend import SimulationRobotBackend
from robot_ai.tools.robot_tools import RobotToolFacade


def test_robot_get_status_returns_structured_state() -> None:
    tools = RobotToolFacade(SimulationRobotBackend())

    result = tools.robot_get_status()

    assert result["ok"] is True
    assert result["state"] == "status_report"
    assert result["data"]["robot_state"]["mode"] == "idle"
    assert result["data"]["robot_state"]["connected_real_device"] is False


def test_robot_move_axis_returns_success_result() -> None:
    tools = RobotToolFacade(SimulationRobotBackend())

    result = tools.robot_move_axis(axis="x", delta=10.0)

    assert result["ok"] is True
    assert result["state"] == "simulated_motion_completed"
    assert result["data"]["axis"] == "x"
    assert result["data"]["position"] == 10.0
    assert result["errors"] == []


def test_robot_move_axis_returns_safety_rejection() -> None:
    tools = RobotToolFacade(SimulationRobotBackend())
    tools.robot_move_axis(axis="x", delta=95.0)

    result = tools.robot_move_axis(axis="x", delta=10.0)

    assert result["ok"] is False
    assert result["state"] == "motion_rejected"
    assert result["errors"][0]["code"] == "axis_limit_exceeded"
    assert tools.robot_get_status()["data"]["robot_state"]["axes_mm"]["x"] == 95.0


def test_robot_home_and_stop_return_structured_results() -> None:
    tools = RobotToolFacade(SimulationRobotBackend())
    tools.robot_move_axis(axis="z", delta=-20.0)

    home_result = tools.robot_home()
    stop_result = tools.robot_stop()

    assert home_result["ok"] is True
    assert home_result["state"] == "home_completed"
    assert stop_result["ok"] is True
    assert stop_result["state"] == "stopped"
    assert stop_result["data"]["robot_state"]["mode"] == "stopped"


def test_robot_explain_limits_describes_axis_ranges() -> None:
    tools = RobotToolFacade(SimulationRobotBackend())

    result = tools.robot_explain_limits()

    assert result["ok"] is True
    assert result["state"] == "limits_report"
    assert result["data"]["axis_limits"]["x"] == {"minimum": -100.0, "maximum": 100.0}
