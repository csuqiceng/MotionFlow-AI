#!/usr/bin/env python3
"""Real-controller motion matrix (simulated arm).

Exercises every restricted ZMotion function against the real controller at
ROBOT_CONTROLLER_HOST: Func108 linear moves (small + registered positions),
Func108 linear_path, Func110 delay, Func120 io, Func104 system controls.

Each case runs through the full operator path (Phase 1 safety gate + Phase 2
V5.0 write protocol + confirmation flow). Set ROBOT_AI_FIRST_TEST_MAX_DELTA /
ROBOT_AI_FIRST_TEST_MAX_PERCENT env vars high enough to reach named positions.

Usage:
    ROBOT_AI_BACKEND=zmotion_readonly \
    ROBOT_CONTROLLER_HOST=10.168.3.21 \
    ROBOT_ZMOTION_WRAPPER_PATH=.../zauxdllPython.py \
    ROBOT_ZMOTION_DLL_DIR=.../dll库文件 \
    ROBOT_AI_FIRST_TEST_MAX_DELTA=2000 ROBOT_AI_FIRST_TEST_MAX_PERCENT=100 \
    python tools/verify_zmotion_motion_matrix.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from robot_ai.backends.factory import RobotBackendConfig
from robot_ai.zmotion_operator_control import ZMotionOperatorRequest, run_zmotion_operator_command


CONFIRM = dict(
    execute_real=True,
    confirm_work_area_clear=True,
    confirm_estop_ready=True,
    confirmation_code="EXECUTE_ZMOTION_REAL",
)
# Wide software workspace so the per-command envelope doesn't block named
# positions; the L1 SafetyLimits (r 200-1800, z 0-2500) remain the real bound.
WIDE_WS = dict(r_min=0.0, r_max=2000.0, z_min=0.0, z_max=2000.0)

REST = dict(x=900.0, y=0.0, z=1000.0, rx=0.0, ry=0.0, rz=0.0)
POS_A = dict(x=1000.0, y=0.0, z=800.0, rx=0.0, ry=90.0, rz=0.0)
POS_C = dict(x=1500.0, y=0.0, z=600.0, rx=0.0, ry=90.0, rz=0.0)
POS_HOME = dict(x=1475.0, y=0.0, z=1545.0, rx=0.0, ry=0.0, rz=0.0)


def _mv(pose: dict) -> tuple[str, dict]:
    # 50% matches the legacy project's registered-position speed. At 5% the
    # controller's DONE bit fires before physical motion completes on long moves.
    return ("linear_move", dict(
        target_pose=pose, speed_pct=50.0, acceleration_pct=50.0, deceleration_pct=50.0, **WIDE_WS,
    ))


def _sys(action: str) -> tuple[str, dict]:
    return ("system", {"action": action})


def _delay(seconds: float) -> tuple[str, dict]:
    return ("delay", {"seconds": seconds})


def _io(number: int, enabled: bool) -> tuple[str, dict]:
    return ("io", {"io_number": number, "enabled": enabled, "allowed_io_channels": [number]})


CASES: list[tuple[str, tuple[str, dict]]] = [
    ("Z 999->1000 回休息位", _mv({**REST, "z": 1000.0})),
    ("X 900->905", _mv({**REST, "x": 905.0})),
    ("X 905->900 回", _mv({**REST, "x": 900.0})),
    ("-> 位置A [1000,0,800,ry90]", _mv(POS_A)),
    ("-> 休息位", _mv(REST)),
    ("-> 位置C [1500,0,600,ry90]", _mv(POS_C)),
    ("-> 休息位", _mv(REST)),
    ("-> HOME [1475,0,1545]", _mv(POS_HOME)),
    ("-> 休息位", _mv(REST)),
    ("linear_path 休息->A->休息", ("linear_path", dict(
        target_poses=[REST, POS_A, REST], speed_pct=50.0, acceleration_pct=50.0,
        deceleration_pct=50.0, **WIDE_WS,
    ))),
    ("延时 1s (Func110)", _delay(1.0)),
    ("IO0 on (Func120)", _io(0, True)),
    ("IO0 off (Func120)", _io(0, False)),
    ("系统 pause", _sys("pause")),
    ("系统 resume", _sys("resume")),
]


def main() -> int:
    cfg = RobotBackendConfig.from_env()
    print(f"控制器: {cfg.controller_host} | 首测限位 Δ={os.environ.get('ROBOT_AI_FIRST_TEST_MAX_DELTA', '5')}mm "
          f"pct={os.environ.get('ROBOT_AI_FIRST_TEST_MAX_PERCENT', '5')}\n")
    results = []
    for name, (command, parameters) in CASES:
        request = ZMotionOperatorRequest(command=command, parameters=parameters, **CONFIRM)
        r = run_zmotion_operator_command(request=request, config=cfg)
        ok = bool(r.get("ok"))
        state = r.get("state")
        data = r.get("data", {}) or {}
        pose = data.get("actual_pose") or data.get("robot_state", {}).get("axes_mm")
        comp = data.get("completion_state")
        alarm = data.get("alarm")
        blockers = data.get("blockers")
        tag = "OK  " if ok else "FAIL"
        print(f"[{tag}] {name:34s} state={state} comp={comp} pose={pose} alarm={alarm} blockers={blockers}")
        results.append((name, ok, state))

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n汇总: {passed}/{len(results)} 通过")
    for name, ok, state in results:
        if not ok:
            print(f"  FAIL: {name} -> {state}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
