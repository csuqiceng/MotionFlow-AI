"""Temporary upper-computer safety fuse.

Ported from the legacy Qt project (``robot_modbus_lite/temporary_safety_sandbox.py``).
Pure logic. Adaptations vs the legacy source:
- the JSON config loader is dropped (phase 1 has no ``data/`` dir; use the
  in-memory ``TemporarySafetySandboxConfig``);
- ``check_records`` accepts either legacy duck-typed record objects
  (``func_num``/``params``/``description``/``query_key`` attributes) or plain
  dicts (``{"func_id", "params", ...}``), so the operator path can call it
  without inventing the legacy ``CommandDraft`` type.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class TemporarySafetySandboxConfig:
    enabled: bool = True
    z_min: float = 0.0
    z_max: float = 2000.0
    radius_min: float = 0.0
    radius_max: float = 2000.0
    speed_max: float = 150.0
    acc_max: float = 150.0
    dec_max: float = 150.0


@dataclass(frozen=True)
class TemporarySafetySandboxResult:
    ok: bool
    reason_code: str = "OK"
    user_message: str = ""
    failed_step_index: int | None = None
    failed_record_key: str = ""
    detail: dict[str, Any] | None = None


class TemporarySafetySandbox:
    """Temporary upper-computer safety fuse. Remove when the controller gate is ready."""

    def __init__(self, config: TemporarySafetySandboxConfig | None = None):
        self.config = config or TemporarySafetySandboxConfig()

    def check_records(
        self,
        records: Iterable[Any],
        *,
        original_text: str = "",
        current_pose: tuple[float, float, float, float, float, float] | None = None,
    ) -> TemporarySafetySandboxResult:
        records_tuple = tuple(records or ())
        if not self.config.enabled:
            return TemporarySafetySandboxResult(True, "DISABLED")
        for index, record in enumerate(records_tuple, start=1):
            result = self._check_record(record, index, len(records_tuple), original_text, current_pose)
            if not result.ok:
                return result
        return TemporarySafetySandboxResult(True, "OK")

    def _check_record(
        self,
        record: Any,
        step_index: int,
        step_total: int,
        original_text: str,
        current_pose: tuple[float, float, float, float, float, float] | None,
    ) -> TemporarySafetySandboxResult:
        func_num, params, description, query_key = _normalize_record(record)
        try:
            func_value = int(func_num or 0)
        except (TypeError, ValueError):
            func_value = 0
        if func_value != 108:
            return TemporarySafetySandboxResult(True, "SKIPPED_NON_FUNC108")

        points = _record_points(params)
        for point_index, point in enumerate(points, start=1):
            z = point.get("z")
            if z is not None and not (self.config.z_min <= z <= self.config.z_max):
                return self._fail(
                    "POSITION_OUT_OF_RANGE",
                    description,
                    query_key,
                    step_index,
                    step_total,
                    f"目标 Z={_fmt(z)}mm，允许范围是 {_fmt(self.config.z_min)}~{_fmt(self.config.z_max)}mm。",
                    "请把目标高度改到允许范围内。例如：“移动到 X800 Y200 Z1800”。",
                    {"field": "target_z", "value": z, "point_index": point_index},
                )
            x = point.get("x")
            y = point.get("y")
            # 相对运动(position_increment=1)时 x/y 可能为 0(只改了 Z/某轴, 其余继承自当前
            # 位姿), 用传入的 current_pose 补全, 避免 R=0 误拦。
            if x == 0 and y == 0 and current_pose and int(params.get("position_increment", 0) or 0) == 1:
                x = float(current_pose[0] or 0)
                y = float(current_pose[1] or 0)
            if x is not None and y is not None:
                radius = math.sqrt(x * x + y * y)
                if not (self.config.radius_min <= radius <= self.config.radius_max):
                    return self._fail(
                        "POSITION_OUT_OF_RANGE",
                        description,
                        query_key,
                        step_index,
                        step_total,
                        (
                            f"目标半径 R={_fmt(radius)}mm，允许范围是 "
                            f"{_fmt(self.config.radius_min)}~{_fmt(self.config.radius_max)}mm。"
                        ),
                        "请修改目标 X/Y，让半径不超过安全范围。例如：“移动到 X800 Y200 Z800”。",
                        {"field": "radius", "value": radius, "point_index": point_index},
                    )

        for key, limit, label in (
            ("spd_pct", self.config.speed_max, "速度"),
            ("acc_pct", self.config.acc_max, "加速度"),
            ("dec_pct", self.config.dec_max, "减速度"),
        ):
            value = _float_or_none(params.get(key))
            if value is not None and value > limit:
                return self._fail(
                    "MOTION_PARAM_OUT_OF_RANGE",
                    description,
                    query_key,
                    step_index,
                    step_total,
                    f"运动参数超限。{label} {key}={_fmt(value)}，允许最大值是 {_fmt(limit)}。",
                    f"请把{label}改到 {_fmt(limit)} 以内。例如：“以速度 100 移动到位置A”。",
                    {"field": key, "value": value, "limit": limit},
                )

        direction = _expected_direction(original_text)
        if direction:
            mismatch = _direction_mismatch(direction, params, current_pose)
            if mismatch:
                expected_axis, actual_axis = mismatch
                return self._fail(
                    "DIRECTION_MISMATCH",
                    description,
                    query_key,
                    step_index,
                    step_total,
                    f"检测到方向解析不一致。你说的是 {expected_axis.upper()} 方向移动，但系统生成的运动主要变化在 {actual_axis.upper()} 方向。",
                    "请重新明确目标方向或直接给出坐标。例如：“X 正方向移动 500mm”，或：“移动到 X1500 Y0 Z800”。",
                    {"expected_axis": expected_axis, "actual_axis": actual_axis},
                )

        return TemporarySafetySandboxResult(True, "OK")

    def _fail(
        self,
        reason_code: str,
        description: str,
        query_key: str,
        step_index: int,
        step_total: int,
        problem: str,
        suggestion: str,
        detail: dict[str, Any],
    ) -> TemporarySafetySandboxResult:
        prefix = "临时安全预检未通过，流程未执行。" if step_total > 1 else "临时安全预检未通过，未下发机械手动作。"
        step_line = ""
        if step_total > 1:
            step_line = "\n\n失败步骤：\n第 {step} 步".format(step=step_index)
            if description:
                step_line += f"“{description}”"
        message = f"{prefix}{step_line}\n\n问题：\n{problem}\n\n建议：\n{suggestion}"
        return TemporarySafetySandboxResult(
            ok=False,
            reason_code=reason_code,
            user_message=message,
            failed_step_index=step_index,
            failed_record_key=str(query_key or ""),
            detail=detail,
        )


def _normalize_record(record: Any) -> tuple[Any, dict[str, Any], str, str]:
    """Return (func_num, params, description, query_key) from a dict or object."""
    if isinstance(record, dict):
        func_num = record.get("func_id", record.get("func_num", 0))
        params = dict(record.get("params", {}) or {})
        description = str(record.get("description", record.get("query_key", "")) or "")
        query_key = str(record.get("query_key", "") or "")
        return func_num, params, description, query_key
    func_num = getattr(record, "func_num", getattr(record, "function_id", 0))
    params = dict(getattr(record, "params", {}) or {})
    description = str(getattr(record, "description", "") or getattr(record, "query_key", "") or "")
    query_key = str(getattr(record, "query_key", "") or "")
    return func_num, params, description, query_key


def _record_points(params: dict[str, Any]) -> tuple[dict[str, float | None], ...]:
    raw_points = params.get("path_points")
    points: list[dict[str, float | None]] = []
    if isinstance(raw_points, (list, tuple)):
        for item in raw_points:
            if not isinstance(item, dict):
                continue
            points.append(
                {
                    "x": _float_or_none(item.get("x", item.get("target_x"))),
                    "y": _float_or_none(item.get("y", item.get("target_y"))),
                    "z": _float_or_none(item.get("z", item.get("target_z"))),
                }
            )
    points.append(
        {
            "x": _float_or_none(params.get("target_x")),
            "y": _float_or_none(params.get("target_y")),
            "z": _float_or_none(params.get("target_z")),
        }
    )
    return tuple(points)


def _expected_direction(text: str) -> tuple[str, int] | None:
    compact = "".join(str(text or "").lower().split())
    if not compact:
        return None
    if "x方向" in compact or "x轴" in compact:
        if any(word in compact for word in ("负", "反", "后退", "反向")):
            return ("x", -1)
        return ("x", 1)
    if "y方向" in compact or "y轴" in compact:
        if any(word in compact for word in ("负", "反", "后退", "反向")):
            return ("y", -1)
        return ("y", 1)
    if "上升" in compact or "升高" in compact:
        return ("z", 1)
    if "下降" in compact or "降低" in compact:
        return ("z", -1)
    return None


def _direction_mismatch(
    expected: tuple[str, int],
    params: dict[str, Any],
    current_pose: tuple[float, float, float, float, float, float] | None,
) -> tuple[str, str] | None:
    expected_axis, expected_sign = expected
    deltas = {
        "x": _float_or_none(params.get("delta_x")),
        "y": _float_or_none(params.get("delta_y")),
        "z": _float_or_none(params.get("delta_z")),
    }
    if all(value is None for value in deltas.values()) and current_pose is not None:
        targets = {
            "x": _float_or_none(params.get("target_x")),
            "y": _float_or_none(params.get("target_y")),
            "z": _float_or_none(params.get("target_z")),
        }
        bases = {"x": current_pose[0], "y": current_pose[1], "z": current_pose[2]}
        deltas = {
            axis: (targets[axis] - bases[axis]) if targets[axis] is not None else None
            for axis in ("x", "y", "z")
        }
    if all(value is None for value in deltas.values()):
        return None
    numeric = {axis: float(value or 0.0) for axis, value in deltas.items()}
    actual_axis = max(numeric, key=lambda axis: abs(numeric[axis]))
    if abs(numeric[actual_axis]) < 0.001:
        return None
    expected_delta = numeric.get(expected_axis, 0.0)
    if actual_axis != expected_axis and abs(numeric[actual_axis]) > max(abs(expected_delta) * 1.5, 1.0):
        return (expected_axis, actual_axis)
    if actual_axis == expected_axis and expected_delta * expected_sign < -0.001:
        return (expected_axis, expected_axis)
    return None


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.3f}".rstrip("0").rstrip(".")
