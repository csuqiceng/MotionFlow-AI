from robot_ai.backends.simulation_backend import SimulationRobotBackend


def test_initial_state_is_idle_and_zeroed() -> None:
    backend = SimulationRobotBackend()

    state = backend.get_state()

    assert state.mode == "idle"
    assert state.axes_mm == {"x": 0.0, "y": 0.0, "z": 0.0, "rx": 0.0, "ry": 0.0, "rz": 0.0}
    assert state.alarms == []
    assert state.connected_real_device is False


def test_move_axis_updates_position_when_within_limits() -> None:
    backend = SimulationRobotBackend()

    result = backend.move_axis("x", 10.0)

    assert result.ok is True
    assert result.state == "simulated_motion_completed"
    assert backend.get_state().axes_mm["x"] == 10.0
    assert result.data["axis"] == "x"
    assert result.data["position"] == 10.0


def test_move_axis_rejects_out_of_range_without_mutating_state() -> None:
    backend = SimulationRobotBackend()
    backend.move_axis("x", 90.0)

    result = backend.move_axis("x", 20.0)

    assert result.ok is False
    assert result.state == "motion_rejected"
    assert backend.get_state().axes_mm["x"] == 90.0
    assert result.errors[0]["code"] == "axis_limit_exceeded"


def test_home_resets_all_axes() -> None:
    backend = SimulationRobotBackend()
    backend.move_axis("x", 10.0)
    backend.move_axis("z", -15.0)

    result = backend.home()

    assert result.ok is True
    assert result.state == "home_completed"
    assert all(value == 0.0 for value in backend.get_state().axes_mm.values())


def test_stop_changes_mode_without_raising_alarm() -> None:
    backend = SimulationRobotBackend()

    result = backend.stop()

    assert result.ok is True
    assert result.state == "stopped"
    assert backend.get_state().mode == "stopped"
    assert backend.get_state().alarms == []
