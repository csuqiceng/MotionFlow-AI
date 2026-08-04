from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from robot_platform.application.operations import RobotOperationRequest
from robot_platform.backends.factory import RobotBackendConfig
from robot_platform.backends.product_wiring import create_product_robot_backend
from robot_platform.backends.simulation_backend import PyBulletSimulationBackend
from robot_platform.backends.wiring import run_composed_operator_command
from robot_platform.simulation.catalog import SimulationModelError, load_simulation_model
from robot_platform.simulation.engine import SimulationOperationResult, SimulationSnapshot
from robot_platform.simulation.pybullet_engine import PyBulletSimulationEngine


class _FakeEngine:
    def __init__(self) -> None:
        self.started = False
        self.commands: list[tuple[str, dict[str, object]]] = []

    def start(self) -> None:
        self.started = True

    def close(self) -> None:
        self.started = False

    def snapshot(self) -> SimulationSnapshot:
        return SimulationSnapshot("idle", (1, 2, 3, 4, 5, 6), (100, 200, 300, 0, 90, 0))

    def move_joint(self, index: int, delta_deg: float) -> SimulationOperationResult:
        return SimulationOperationResult(True, "simulated_motion_completed", "ok", {"index": index, "delta": delta_deg})

    def home(self) -> SimulationOperationResult:
        return SimulationOperationResult(True, "simulated_motion_completed", "home")

    def execute(self, command: str, parameters: dict[str, object]) -> SimulationOperationResult:
        self.commands.append((command, parameters))
        return SimulationOperationResult(True, "simulated_motion_completed", "ok", {"command": command})

    def stop(self) -> SimulationOperationResult:
        return SimulationOperationResult(True, "simulated_motion_stopped", "stopped")


def test_default_model_manifest_is_confined_and_has_six_joints() -> None:
    model = load_simulation_model("generic-six-axis")
    assert model.urdf_path.is_file()
    assert len(model.joint_names) == 6
    assert model.tool_link == "tool"
    assert model.base_to_world_mm_deg == (0, 0, 0, 0, 0, 0)
    assert model.tcp_offset_mm_deg == (0, 0, 0, 0, 0, 0)
    assert model.joint_directions == (1, 1, 1, 1, 1, 1)


def test_model_catalog_rejects_path_escaping_urdf(tmp_path: Path) -> None:
    package = tmp_path / "evil"
    package.mkdir()
    (package / "manifest.json").write_text(json.dumps({
        "robot_id": "evil", "display_name": "evil", "urdf": "../outside.urdf", "tool_link": "j6",
        "joints": [{"name": f"j{i}", "lower_deg": -1, "upper_deg": 1} for i in range(6)],
    }), encoding="utf-8")
    try:
        load_simulation_model("evil", models_root=tmp_path)
    except SimulationModelError as exc:
        assert str(exc) == "simulation_model_path_outside_package"
    else:
        raise AssertionError("escaping manifest path was accepted")


def test_pybullet_adapter_has_no_real_write_and_routes_only_offline_operations() -> None:
    fake = _FakeEngine()
    backend = PyBulletSimulationBackend(engine=fake)
    assert backend.capabilities.supports_real_writes is False
    result = backend.execute_operation(RobotOperationRequest(
        command="linear_move", parameters={"target_pose": {"x": 1}},
    ))
    assert result["ok"] is True
    assert fake.commands == [("linear_move", {"target_pose": {"x": 1}})]
    assert backend.get_state().joints_deg == [1, 2, 3, 4, 5, 6]
    rejected = backend.execute_operation(RobotOperationRequest(
        command="linear_move", parameters={"target_pose": {}}, execute_real=True,
    ))
    assert rejected["state"] == "simulation_real_execution_rejected"
    axis_result = backend.move_axis("x", 100.0)
    assert axis_result.state == "simulation_cartesian_axis_unsupported"


def test_pybullet_plugin_is_opt_in_and_does_not_change_legacy_simulation() -> None:
    legacy = create_product_robot_backend(RobotBackendConfig(mode="simulation"))
    pybullet = create_product_robot_backend(RobotBackendConfig(mode="pybullet"))
    assert type(legacy).__name__ == "SimulationRobotBackend"
    assert type(pybullet).__name__ == "PyBulletSimulationBackend"


def test_simulation_engine_selection_is_controlled_by_environment_config() -> None:
    config = RobotBackendConfig.from_env({
        "ROBOT_SIMULATION_ENGINE": "PYBULLET",
        "ROBOT_SIMULATION_MODEL_ID": "generic-six-axis",
    })
    assert config.simulation_engine == "pybullet"
    assert config.simulation_model_id == "generic-six-axis"


def test_composed_wiring_uses_only_the_simulation_operation_port() -> None:
    class Manager:
        def __init__(self) -> None:
            self.request: RobotOperationRequest | None = None

        def execute_operation(self, request: RobotOperationRequest, **kwargs: object) -> dict[str, object]:
            self.request = request
            assert kwargs == {}
            return {"ok": True, "state": "simulated_motion_completed"}

    manager = Manager()
    request = RobotOperationRequest(command="linear_move", parameters={"target_pose": {}})
    outcome = run_composed_operator_command(
        manager=manager, request=request, config=RobotBackendConfig(mode="pybullet"),
    )
    assert outcome["ok"] is True
    assert manager.request is request


def test_real_pybullet_direct_engine_loads_and_moves_default_model() -> None:
    pytest.importorskip("pybullet")
    engine = PyBulletSimulationEngine(load_simulation_model("generic-six-axis"))
    try:
        engine.start()
        initial = engine.snapshot()
        outcome = engine.move_joint(0, 5.0)
        current = engine.snapshot()
    finally:
        engine.close()
    assert len(initial.joints_deg) == 6
    assert outcome.ok is True
    assert outcome.state == "simulated_motion_completed"
    assert current.joints_deg[0] == pytest.approx(5.0, abs=0.01)


def test_real_pybullet_direct_engine_rejects_initial_environment_collision(tmp_path: Path) -> None:
    pytest.importorskip("pybullet")
    scene_path = tmp_path / "scene.json"
    scene_path.write_text(json.dumps({"obstacles": [{
        "size_mm": [200, 200, 200],
        "pose_mm_deg": [1500, 0, 80, 0, 0, 0],
    }]}), encoding="utf-8")
    model = replace(load_simulation_model("generic-six-axis"), scene_path=scene_path)
    engine = PyBulletSimulationEngine(model)
    with pytest.raises(RuntimeError, match="simulation_model_initial_collision"):
        engine.start()
    engine.close()


def test_real_pybullet_direct_engine_rejects_environment_collision_along_path(tmp_path: Path) -> None:
    pytest.importorskip("pybullet")
    scene_path = tmp_path / "scene.json"
    scene_path.write_text(json.dumps({"obstacles": [{
        "size_mm": [150, 150, 150],
        "pose_mm_deg": [1494, 131, 80, 0, 0, 0],
    }]}), encoding="utf-8")
    model = replace(load_simulation_model("generic-six-axis"), scene_path=scene_path)
    engine = PyBulletSimulationEngine(model)
    try:
        engine.start()
        outcome = engine.move_joint(0, 5.0)
    finally:
        engine.close()
    assert outcome.ok is False
    assert outcome.state == "simulation_collision_detected"
    assert outcome.data["body"] == "environment"


def test_real_pybullet_direct_engine_rejects_self_collision_along_path() -> None:
    pytest.importorskip("pybullet")
    engine = PyBulletSimulationEngine(load_simulation_model("generic-six-axis"))
    try:
        engine.start()
        for joint, delta in ((1, -120.0), (2, -120.0), (3, -120.0)):
            assert engine.move_joint(joint, delta).ok is True
        outcome = engine.move_joint(4, 120.0)
    finally:
        engine.close()
    assert outcome.ok is False
    assert outcome.state == "simulation_collision_detected"
    assert outcome.data["body"] == "self"
