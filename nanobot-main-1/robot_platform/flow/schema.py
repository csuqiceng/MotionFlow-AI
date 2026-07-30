"""Strict schemas shared by Flow authoring and immutable snapshots."""

from __future__ import annotations

import math
from typing import Any


SUPPORTED_ACTION_FUNCS = frozenset({104, 108, 110, 120})
_AXES = ("x", "y", "z", "rx", "ry", "rz")


def validate_legacy_step_payload(step: Any) -> list[str]:
    if not isinstance(step, dict):
        return ["Every flow step must be a mapping."]
    errors: list[str] = []
    step_id = step.get("step_id")
    if isinstance(step_id, bool) or not isinstance(step_id, int):
        errors.append("Every flow step_id must be an integer (not boolean).")
    func_id = step.get("func_id")
    if isinstance(func_id, bool) or not isinstance(func_id, int):
        errors.append("Every flow func_id must be an integer (not boolean).")
        return errors
    if func_id not in SUPPORTED_ACTION_FUNCS:
        errors.append(f"Unsupported flow func_id: {func_id}.")
        return errors
    params = step.get("params", {})
    if not isinstance(params, dict):
        errors.append("Flow step params must be a mapping.")
        return errors
    if func_id == 120:
        _validate_io(params, errors)
    elif func_id == 110:
        seconds = params.get("seconds", params.get("delay_sec", 0))
        if not _finite_number(seconds) or seconds < 0:
            errors.append("Delay seconds must be a finite nonnegative number.")
    elif func_id == 104:
        action = params.get("action")
        if not isinstance(action, str) or not action.strip():
            errors.append("System action must be a non-empty string.")
    elif func_id == 108:
        _validate_motion(params, step, errors)
    return errors


def validate_flow_draft_payload(
    payload: dict[str, Any], *, flow_id: str = "preview",
) -> list[str]:
    """Validate one Flow draft without reading or mutating registry state."""
    errors: list[str] = []
    if not str(payload.get("name", "")).strip():
        errors.append("Flow name must not be empty.")
    steps = payload.get("steps")
    if not isinstance(steps, list) or not steps:
        errors.append("Flow must contain at least one step.")
    else:
        for index, step in enumerate(steps, start=1):
            errors.extend(
                f"Step {index}: {message}"
                for message in validate_legacy_step_payload(step)
            )
        if all(isinstance(step, dict) for step in steps):
            step_ids = [step.get("step_id") for step in steps]
            try:
                unique_step_ids = set(step_ids)
            except TypeError:
                errors.append("Every flow step_id must be hashable.")
            else:
                if len(unique_step_ids) != len(step_ids):
                    errors.append("Flow step IDs must be unique.")
        if any(_is_dedicated_emergency_stop_step(step) for step in steps):
            errors.append(
                "Emergency stop cannot be authored inside a Flow; "
                "use the dedicated safety surface."
            )
    delay = payload.get("step_delay_ms", 1000)
    if not _finite_number(delay):
        errors.append("Step delay must be finite.")
    elif delay < 0:
        errors.append("Step delay must be nonnegative.")
    speed = payload.get("rehearsal_spd", 20)
    if not _finite_number(speed) or speed <= 0:
        errors.append("Rehearsal speed must be finite and positive.")
    node_graph = payload.get("node_graph")
    if node_graph is not None:
        try:
            from robot_platform.flow.models import FlowEntry
            from robot_platform.flow.nodes import ConditionNode, iter_nodes, node_from_dict
            from robot_platform.flow.snapshot import FlowExecutionSnapshot

            if not isinstance(node_graph, dict):
                raise ValueError("node_graph must be an object")
            root = node_from_dict(node_graph)
            inputs = {
                node.input_name: None for node in iter_nodes(root)
                if isinstance(node, ConditionNode)
            }
            FlowExecutionSnapshot.create(
                FlowEntry.from_dict({
                    "name": payload.get("name", ""),
                    "flow_id": flow_id,
                    "version": payload.get("version", 0),
                    "steps": steps or [],
                    "node_graph": node_graph,
                }),
                product_profile_version="validation",
                capability_version="validation",
                core_version="validation",
                root_node=root,
                execution_inputs=inputs,
            )
        except Exception:
            errors.append("Flow node_graph does not match its immutable steps.")
    return errors


def require_strict_io_parameters(params: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    _validate_io(params, errors)
    if errors:
        raise ValueError(" ".join(errors))
    return {
        "io_number": params["io_number"],
        "enabled": params["enabled"],
        "allowed_io_channels": list(params.get("allowed_io_channels", [])),
    }


def _validate_io(params: dict[str, Any], errors: list[str]) -> None:
    channel = params.get("io_number")
    if isinstance(channel, bool) or not isinstance(channel, int) or channel < 0:
        errors.append("IO io_number must be a nonnegative integer (not boolean).")
    if not isinstance(params.get("enabled"), bool):
        errors.append("IO enabled must be boolean.")
    allowed = params.get("allowed_io_channels", [])
    if not isinstance(allowed, list) or any(
        isinstance(item, bool) or not isinstance(item, int) or item < 0
        for item in allowed
    ):
        errors.append("IO allowed_io_channels must contain nonnegative integers.")


def _validate_motion(
    params: dict[str, Any], step: dict[str, Any], errors: list[str],
) -> None:
    target = params.get("target_pose")
    if target is not None:
        if not isinstance(target, dict):
            errors.append("Motion target_pose must be a mapping.")
        else:
            for axis in _AXES:
                if axis not in target or not _finite_number(target[axis]):
                    errors.append(f"Motion target_pose.{axis} must be finite.")
    else:
        for axis in _AXES:
            value = params.get(f"target_{axis}", params.get(axis, 0.0))
            if not _finite_number(value):
                errors.append(f"Motion target_{axis} must be finite.")
    speed = params.get("speed_pct", step.get("spd_pct", 50))
    for name, value in (
        ("speed_pct", speed),
        ("acceleration_pct", params.get("acceleration_pct", speed)),
        ("deceleration_pct", params.get("deceleration_pct", speed)),
    ):
        if not _finite_number(value) or not 0 < value <= 100:
            errors.append(f"Motion {name} must be finite and within (0, 100].")
    for name in ("r_min", "r_max", "z_min", "z_max"):
        if name in params and not _finite_number(params[name]):
            errors.append(f"Motion {name} must be finite.")


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _is_dedicated_emergency_stop_step(step: object) -> bool:
    if not isinstance(step, dict):
        return False
    params = step.get("params")
    try:
        func_id = int(step.get("func_id", 0) or 0)
    except (TypeError, ValueError):
        return False
    return bool(
        func_id == 104 and isinstance(params, dict)
        and params.get("action") == "emergency_stop"
    )
