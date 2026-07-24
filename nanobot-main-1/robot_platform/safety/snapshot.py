"""Bridge the flat ``RobotState`` to the legacy snapshot/plan dict shape.

This is the decoupling seam between the new project and the ported L1 safety
services. ``SafetyPrecheckService.run_l1`` consumes a ``snapshot`` dict (keys
``safety``/``connection``/``motion``/``position``) and a ``plan`` dict
(``target``/``speed``/``func_id``/``action_type``). The new project only has
``RobotState`` (``mode``/``axes_mm``/``alarms``/``connected_real_device``);
this module maps one to the other with no Qt coupling.

Estop/ alarm derivation mirrors ``robot_platform.backends.zmotion_backend``:
``_alarms_from_status`` appends ``"emergency_stop"`` when the ESTOP bit is
set, and ``_mode_from_status`` returns ``"stopped"`` for the same bit.
"""

from __future__ import annotations

import math
from typing import Any

from robot_platform.models import RobotState


def build_controller_snapshot(robot_state: RobotState) -> dict[str, Any]:
    """Map ``RobotState`` to the legacy snapshot dict consumed by L1 services."""
    axes = robot_state.axes_mm
    x = float(axes.get("x", 0.0))
    y = float(axes.get("y", 0.0))
    z = float(axes.get("z", 0.0))
    radius = math.hypot(x, y)
    mode = str(robot_state.mode or "idle")

    alarms = [str(alarm) for alarm in robot_state.alarms]
    alarm_text = " ".join(alarms).lower()
    estop = mode == "stopped" or "emergency_stop" in alarm_text or "estop" in alarm_text
    alarm_active = bool(alarms) or mode == "alarm"
    paused = mode == "paused"

    running_state = "executing" if mode == "moving" else mode
    connection_state = "online" if robot_state.connected_real_device else "offline"

    return {
        "safety": {
            "estop": estop,
            "alarm_active": alarm_active,
            "paused": paused,
        },
        "connection": {
            "controller": connection_state,
            "realtime_feedback": connection_state,
        },
        "motion": {
            "active_plan_id": None,
            "running_state": running_state,
        },
        "position": {
            "cartesian": {
                "x": x,
                "y": y,
                "z": z,
                "r": radius,
                "rx": float(axes.get("rx", 0.0)),
                "ry": float(axes.get("ry", 0.0)),
                "rz": float(axes.get("rz", 0.0)),
            }
        },
    }


def build_l1_plan(
    *,
    func_id: int,
    target: dict[str, float] | None = None,
    speed: dict[str, float] | None = None,
    action_type: str = "move",
    plan_id: str = "operator",
) -> dict[str, Any]:
    """Build the legacy ``plan`` dict consumed by L1 services."""
    return {
        "plan_id": plan_id,
        "func_id": int(func_id),
        "action_type": action_type,
        "target": dict(target or {}),
        "speed": dict(speed or {}),
    }
