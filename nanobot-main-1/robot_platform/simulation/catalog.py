"""Strict, dependency-free discovery of installed robot simulation models."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_MODEL_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
_JOINT_COUNT = 6


class SimulationModelError(ValueError):
    """A model package is absent or unsafe to load."""


@dataclass(frozen=True)
class RobotSimulationModel:
    """Validated, filesystem-confined model metadata."""

    robot_id: str
    display_name: str
    package_dir: Path
    urdf_path: Path
    joint_names: tuple[str, ...]
    joint_limits_deg: tuple[tuple[float, float], ...]
    joint_directions: tuple[float, ...]
    joint_offsets_deg: tuple[float, ...]
    tool_link: str
    base_to_world_mm_deg: tuple[float, float, float, float, float, float]
    tcp_offset_mm_deg: tuple[float, float, float, float, float, float]
    scene_path: Path | None = None


class SimulationModelCatalog:
    """Find models only below a deployment-controlled root directory."""

    def __init__(self, models_root: Path | None = None) -> None:
        self._root = (models_root or Path(__file__).with_name("models")).resolve()

    def load(self, robot_id: str) -> RobotSimulationModel:
        normalized = str(robot_id or "").strip().casefold()
        if _MODEL_ID.fullmatch(normalized) is None:
            raise SimulationModelError("simulation_model_id_invalid")
        package = _confined_path(self._root, self._root / normalized)
        manifest_path = _confined_path(package, package / "manifest.json")
        if not manifest_path.is_file():
            raise SimulationModelError("simulation_model_not_found")
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SimulationModelError("simulation_model_manifest_invalid") from exc
        return _parse_manifest(payload, package, normalized)


def load_simulation_model(robot_id: str, *, models_root: Path | None = None) -> RobotSimulationModel:
    return SimulationModelCatalog(models_root).load(robot_id)


def _parse_manifest(payload: Any, package: Path, expected_id: str) -> RobotSimulationModel:
    if not isinstance(payload, dict):
        raise SimulationModelError("simulation_model_manifest_invalid")
    robot_id = payload.get("robot_id")
    display_name = payload.get("display_name")
    urdf = payload.get("urdf")
    tool_link = payload.get("tool_link")
    joints = payload.get("joints")
    if (
        robot_id != expected_id or not isinstance(display_name, str) or not display_name.strip()
        or not isinstance(urdf, str) or not isinstance(tool_link, str) or not tool_link.strip()
        or not isinstance(joints, list) or len(joints) != _JOINT_COUNT
    ):
        raise SimulationModelError("simulation_model_manifest_invalid")
    names: list[str] = []
    limits: list[tuple[float, float]] = []
    directions: list[float] = []
    offsets: list[float] = []
    for joint in joints:
        if not isinstance(joint, dict):
            raise SimulationModelError("simulation_model_manifest_invalid")
        name, lower, upper = joint.get("name"), joint.get("lower_deg"), joint.get("upper_deg")
        direction, offset = joint.get("direction", 1), joint.get("offset_deg", 0)
        if not isinstance(name, str) or not name.strip() or isinstance(lower, bool) or isinstance(upper, bool):
            raise SimulationModelError("simulation_model_manifest_invalid")
        try:
            low, high, sign, zero = float(lower), float(upper), float(direction), float(offset)
        except (TypeError, ValueError) as exc:
            raise SimulationModelError("simulation_model_manifest_invalid") from exc
        if not low < high or sign not in {-1.0, 1.0} or name in names:
            raise SimulationModelError("simulation_model_manifest_invalid")
        names.append(name)
        limits.append((low, high))
        directions.append(sign)
        offsets.append(zero)
    urdf_path = _confined_path(package, package / urdf)
    if not urdf_path.is_file():
        raise SimulationModelError("simulation_model_urdf_missing")
    scene_raw = payload.get("scene")
    scene_path = None if scene_raw is None else _confined_path(package, package / str(scene_raw))
    if scene_path is not None and not scene_path.is_file():
        raise SimulationModelError("simulation_scene_missing")
    return RobotSimulationModel(
        robot_id=robot_id, display_name=display_name.strip(), package_dir=package,
        urdf_path=urdf_path, joint_names=tuple(names),
        joint_limits_deg=tuple(limits), joint_directions=tuple(directions),
        joint_offsets_deg=tuple(offsets), tool_link=tool_link.strip(),
        base_to_world_mm_deg=_pose(payload.get("base_to_world_mm_deg", [0, 0, 0, 0, 0, 0])),
        tcp_offset_mm_deg=_pose(payload.get("tcp_offset_mm_deg", [0, 0, 0, 0, 0, 0])),
        scene_path=scene_path,
    )


def _confined_path(root: Path, candidate: Path) -> Path:
    if candidate.is_symlink():
        raise SimulationModelError("simulation_model_path_outside_package")
    resolved_root, resolved = root.resolve(), candidate.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise SimulationModelError("simulation_model_path_outside_package") from exc
    return resolved


def _pose(value: object) -> tuple[float, float, float, float, float, float]:
    if not isinstance(value, list) or len(value) != 6 or any(isinstance(item, bool) for item in value):
        raise SimulationModelError("simulation_model_manifest_invalid")
    try:
        pose = tuple(float(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise SimulationModelError("simulation_model_manifest_invalid") from exc
    if any(not math.isfinite(item) for item in pose):
        raise SimulationModelError("simulation_model_manifest_invalid")
    return pose  # type: ignore[return-value]
