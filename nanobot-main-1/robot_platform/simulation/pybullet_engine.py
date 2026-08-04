"""PyBullet DIRECT implementation kept separate from application/controller code."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from threading import Event
from typing import Any

from .catalog import RobotSimulationModel
from .engine import SimulationOperationResult, SimulationSnapshot


@dataclass
class PyBulletSimulationEngine:
    model: RobotSimulationModel
    time_step_seconds: float = 1.0 / 120.0
    _api: Any = None
    _client: int | None = None
    _body: int | None = None
    _joint_indices: tuple[int, ...] = ()
    _dof_indices: tuple[int, ...] = ()
    _tool_index: int | None = None
    _mode: str = "idle"
    _stop_requested: Event = field(default_factory=Event)
    _environment_bodies: tuple[int, ...] = ()

    def start(self) -> None:
        if self._client is not None:
            return
        try:
            import pybullet as bullet  # optional native dependency
        except ImportError as exc:
            raise RuntimeError("simulation_dependency_missing: pybullet") from exc
        self._api = bullet
        self._client = bullet.connect(bullet.DIRECT)
        if self._client < 0:
            self._client = None
            raise RuntimeError("simulation_engine_start_failed")
        try:
            bullet.setGravity(0, 0, 0, physicsClientId=self._client)
            bullet.setTimeStep(self.time_step_seconds, physicsClientId=self._client)
            base_position, base_orientation = self._pose_transform(self.model.base_to_world_mm_deg)
            self._body = bullet.loadURDF(
                str(self.model.urdf_path), basePosition=base_position, baseOrientation=base_orientation, useFixedBase=True,
                flags=bullet.URDF_USE_SELF_COLLISION, physicsClientId=self._client,
            )
            indices: dict[str, int] = {}
            link_indices: dict[str, int] = {}
            for index in range(bullet.getNumJoints(self._body, physicsClientId=self._client)):
                info = bullet.getJointInfo(self._body, index, physicsClientId=self._client)
                name = bytes(info[1]).decode("utf-8")
                link_name = bytes(info[12]).decode("utf-8")
                indices[name] = index
                link_indices[link_name] = index
                if int(info[2]) != int(bullet.JOINT_FIXED):
                    self._dof_indices += (index,)
            if any(name not in indices for name in self.model.joint_names):
                raise RuntimeError("simulation_model_joint_missing")
            self._joint_indices = tuple(indices[name] for name in self.model.joint_names)
            self._tool_index = link_indices.get(self.model.tool_link)
            if self._tool_index is None:
                raise RuntimeError("simulation_model_tool_link_missing")
            self._set_joints([0.0] * len(self._joint_indices))
            self._environment_bodies = self._load_scene()
            collision = self._collision()
            if collision is not None:
                raise RuntimeError("simulation_model_initial_collision")
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        if self._client is not None and self._api is not None:
            self._api.disconnect(physicsClientId=self._client)
        self._client = self._body = self._tool_index = None
        self._joint_indices = ()
        self._environment_bodies = ()
        self._mode = "idle"

    def snapshot(self) -> SimulationSnapshot:
        self._require_started()
        joints = tuple(
            math.degrees(self._api.getJointState(self._body, index, physicsClientId=self._client)[0]) * direction + offset
            for index, direction, offset in zip(self._joint_indices, self.model.joint_directions, self.model.joint_offsets_deg)
        )
        pose = self._api.getLinkState(self._body, self._tool_index, computeForwardKinematics=True, physicsClientId=self._client)
        position, quaternion = self._api.multiplyTransforms(
            pose[4], pose[5], *self._pose_transform(self.model.tcp_offset_mm_deg), physicsClientId=self._client,
        )
        base_inverse = self._api.invertTransform(*self._pose_transform(self.model.base_to_world_mm_deg))
        position, quaternion = self._api.multiplyTransforms(*base_inverse, position, quaternion, physicsClientId=self._client)
        roll, pitch, yaw = self._api.getEulerFromQuaternion(quaternion)
        return SimulationSnapshot(
            mode=self._mode, joints_deg=joints,
            pose_mm_deg=(position[0] * 1000, position[1] * 1000, position[2] * 1000,
                         math.degrees(roll), math.degrees(pitch), math.degrees(yaw)),
        )

    def move_joint(self, index: int, delta_deg: float) -> SimulationOperationResult:
        self._require_started()
        if not isinstance(index, int) or not 0 <= index < len(self._joint_indices):
            return _failure("simulation_joint_invalid", "Simulation joint is invalid.")
        if not _finite(delta_deg):
            return _failure("simulation_joint_delta_invalid", "Simulation joint delta is invalid.")
        current = self.snapshot().joints_deg
        target = list(current)
        target[index] += float(delta_deg)
        return self._move_to(target)

    def execute(self, command: str, parameters: dict[str, object]) -> SimulationOperationResult:
        self._require_started()
        if command == "linear_move":
            return self._linear_move(parameters)
        if command == "delay":
            seconds = parameters.get("seconds", 0.0)
            if not _finite(seconds) or not 0 <= float(seconds) <= 60:
                return _failure("simulation_delay_invalid", "Simulation delay must be within 0-60 seconds.")
            self._stop_requested.clear()
            self._mode = "running"
            for _ in range(round(float(seconds) / self.time_step_seconds)):
                if self._stop_requested.is_set():
                    return _success("simulated_motion_stopped", "Simulation motion stopped.", self.snapshot())
                self._api.stepSimulation(physicsClientId=self._client)
            self._mode = "idle"
            return _success("simulated_delay_completed", "Simulation delay completed.", self.snapshot())
        return _failure("simulation_operation_unsupported", "Simulation command is not supported.", {"command": command})

    def stop(self) -> SimulationOperationResult:
        self._require_started()
        self._stop_requested.set()
        self._mode = "stopped"
        return _success("simulated_motion_stopped", "Simulation motion stopped.", self.snapshot())

    def home(self) -> SimulationOperationResult:
        self._require_started()
        return self._move_to([0.0] * len(self._joint_indices))

    def _linear_move(self, parameters: dict[str, object]) -> SimulationOperationResult:
        raw = parameters.get("target_pose")
        if not isinstance(raw, dict):
            return _failure("simulation_target_invalid", "Simulation target pose is invalid.")
        keys = ("x", "y", "z", "rx", "ry", "rz")
        try:
            target = tuple(float(raw[key]) for key in keys)
        except (KeyError, TypeError, ValueError):
            return _failure("simulation_target_invalid", "Simulation target pose is invalid.")
        if not all(_finite(value) for value in target):
            return _failure("simulation_target_invalid", "Simulation target pose is invalid.")
        quaternion = self._api.getQuaternionFromEuler(tuple(math.radians(value) for value in target[3:]))
        lower = [math.radians(item[0]) for item in self.model.joint_limits_deg]
        upper = [math.radians(item[1]) for item in self.model.joint_limits_deg]
        local_position = tuple(value / 1000 for value in target[:3])
        world_position, world_orientation = self._api.multiplyTransforms(
            *self._pose_transform(self.model.base_to_world_mm_deg), local_position, quaternion, physicsClientId=self._client,
        )
        tcp_inverse = self._api.invertTransform(*self._pose_transform(self.model.tcp_offset_mm_deg))
        target_position, target_orientation = self._api.multiplyTransforms(
            world_position, world_orientation, *tcp_inverse, physicsClientId=self._client,
        )
        raw_lower = [math.radians((limit[0] - offset) / direction) for limit, direction, offset in zip(self.model.joint_limits_deg, self.model.joint_directions, self.model.joint_offsets_deg)]
        raw_upper = [math.radians((limit[1] - offset) / direction) for limit, direction, offset in zip(self.model.joint_limits_deg, self.model.joint_directions, self.model.joint_offsets_deg)]
        lower, upper = [min(a, b) for a, b in zip(raw_lower, raw_upper)], [max(a, b) for a, b in zip(raw_lower, raw_upper)]
        solution = self._api.calculateInverseKinematics(
            self._body, self._tool_index, targetPosition=target_position,
            targetOrientation=target_orientation, lowerLimits=lower, upperLimits=upper,
            jointRanges=[high - low for low, high in zip(lower, upper)], restPoses=[math.radians(-offset / direction) for direction, offset in zip(self.model.joint_directions, self.model.joint_offsets_deg)],
            physicsClientId=self._client,
        )
        solution_by_index = dict(zip(self._dof_indices, solution))
        if any(index not in solution_by_index for index in self._joint_indices):
            return _failure("simulation_ik_joint_mapping_invalid", "Simulation IK result does not cover model joints.")
        target_joints = [
            math.degrees(float(solution_by_index[index])) * direction + offset
            for index, direction, offset in zip(self._joint_indices, self.model.joint_directions, self.model.joint_offsets_deg)
        ]
        return self._move_to(target_joints, expected_pose=target)

    def _move_to(self, target_deg: list[float], *, expected_pose: tuple[float, ...] | None = None) -> SimulationOperationResult:
        if len(target_deg) != len(self._joint_indices):
            return _failure("simulation_joint_target_invalid", "Simulation joint target is invalid.")
        for index, (value, limits) in enumerate(zip(target_deg, self.model.joint_limits_deg)):
            if not _finite(value) or not limits[0] <= value <= limits[1]:
                return _failure("simulation_joint_limit_exceeded", "Simulation target exceeds joint limit.", {"joint_index": index})
        current = self.snapshot().joints_deg
        steps = max(1, math.ceil(max(abs(after - before) for before, after in zip(current, target_deg)) / 2.0))
        self._stop_requested.clear()
        self._mode = "running"
        for step in range(1, steps + 1):
            if self._stop_requested.is_set():
                self._mode = "stopped"
                return _success("simulated_motion_stopped", "Simulation motion stopped.", self.snapshot())
            sample = [before + (after - before) * step / steps for before, after in zip(current, target_deg)]
            self._set_joints(sample)
            collision = self._collision()
            if collision is not None:
                self._set_joints(list(current))
                self._mode = "idle"
                return _failure("simulation_collision_detected", "Simulation path collides.", collision)
            self._api.stepSimulation(physicsClientId=self._client)
        if expected_pose is not None and not self._pose_matches(expected_pose):
            self._set_joints(list(current))
            self._mode = "idle"
            return _failure(
                "simulation_ik_target_unreachable",
                "Simulation IK result does not reach the requested pose.",
            )
        self._mode = "idle"
        data: dict[str, object] = {"model_id": self.model.robot_id, "target_joints_deg": list(target_deg), "snapshot": _snapshot_data(self.snapshot())}
        if expected_pose is not None:
            data["expected_pose"] = list(expected_pose)
        return SimulationOperationResult(True, "simulated_motion_completed", "Simulation motion completed.", data)

    def _set_joints(self, values_deg: list[float]) -> None:
        for index, value, direction, offset in zip(self._joint_indices, values_deg, self.model.joint_directions, self.model.joint_offsets_deg):
            self._api.resetJointState(self._body, index, math.radians((value - offset) / direction), physicsClientId=self._client)

    def _collision(self) -> dict[str, object] | None:
        # resetJointState does not refresh broadphase/contact caches.  A query
        # immediately after a sampled joint update would otherwise miss a real
        # collision and falsely report a safe simulated path.
        self._api.performCollisionDetection(physicsClientId=self._client)
        contacts = self._api.getContactPoints(self._body, self._body, physicsClientId=self._client)
        for contact in contacts:
            if int(contact[3]) != int(contact[4]):
                return {"body": "self", "link_a": int(contact[3]), "link_b": int(contact[4])}
        for body in self._environment_bodies:
            if self._api.getContactPoints(self._body, body, physicsClientId=self._client):
                return {"body": "environment", "environment_body": body}
        return None

    def _load_scene(self) -> tuple[int, ...]:
        if self.model.scene_path is None:
            return ()
        try:
            payload = json.loads(self.model.scene_path.read_text(encoding="utf-8"))
            obstacles = payload["obstacles"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise RuntimeError("simulation_scene_invalid") from exc
        if not isinstance(obstacles, list) or len(obstacles) > 64:
            raise RuntimeError("simulation_scene_invalid")
        bodies: list[int] = []
        for obstacle in obstacles:
            if not isinstance(obstacle, dict) or set(obstacle) != {"size_mm", "pose_mm_deg"}:
                raise RuntimeError("simulation_scene_invalid")
            size = obstacle["size_mm"]
            if not isinstance(size, list) or len(size) != 3 or not all(_finite(value) and float(value) > 0 for value in size):
                raise RuntimeError("simulation_scene_invalid")
            raw_pose = obstacle["pose_mm_deg"]
            if (
                not isinstance(raw_pose, list)
                or len(raw_pose) != 6
                or not all(_finite(value) for value in raw_pose)
            ):
                raise RuntimeError("simulation_scene_invalid")
            pose = tuple(float(value) for value in raw_pose)
            shape = self._api.createCollisionShape(self._api.GEOM_BOX, halfExtents=[float(value) / 2000 for value in size], physicsClientId=self._client)
            position, orientation = self._api.multiplyTransforms(
                *self._pose_transform(self.model.base_to_world_mm_deg),
                *self._pose_transform(pose),
                physicsClientId=self._client,
            )
            bodies.append(self._api.createMultiBody(baseMass=0, baseCollisionShapeIndex=shape, basePosition=position, baseOrientation=orientation, physicsClientId=self._client))
        return tuple(bodies)

    def _pose_matches(self, expected: tuple[float, ...]) -> bool:
        actual = self.snapshot().pose_mm_deg
        position_error = math.dist(actual[:3], expected[:3])
        orientation_error = max(abs(_angle_delta(actual[index], expected[index])) for index in range(3, 6))
        return position_error <= 25.0 and orientation_error <= 5.0

    def _require_started(self) -> None:
        if self._client is None or self._body is None or self._api is None:
            raise RuntimeError("simulation_engine_not_started")

    def _pose_transform(self, pose: tuple[float, ...]) -> tuple[tuple[float, float, float], tuple[float, float, float, float]]:
        return (
            (pose[0] / 1000.0, pose[1] / 1000.0, pose[2] / 1000.0),
            self._api.getQuaternionFromEuler(tuple(math.radians(value) for value in pose[3:])),
        )


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _angle_delta(actual: float, expected: float) -> float:
    return (actual - expected + 180.0) % 360.0 - 180.0


def _snapshot_data(snapshot: SimulationSnapshot) -> dict[str, object]:
    return {"mode": snapshot.mode, "joints_deg": list(snapshot.joints_deg), "pose_mm_deg": list(snapshot.pose_mm_deg)}


def _success(state: str, message: str, snapshot: SimulationSnapshot) -> SimulationOperationResult:
    return SimulationOperationResult(True, state, message, {"snapshot": _snapshot_data(snapshot)})


def _failure(code: str, message: str, data: dict[str, object] | None = None) -> SimulationOperationResult:
    return SimulationOperationResult(False, code, message, dict(data or {}), ({"code": code},))
