from __future__ import annotations

from dataclasses import dataclass, field

from robot_ai.models import AXIS_NAMES, ToolResult


@dataclass(frozen=True)
class AxisLimit:
    minimum: float
    maximum: float


@dataclass(frozen=True)
class SafetyPolicy:
    axis_limits: dict[str, AxisLimit] = field(
        default_factory=lambda: {axis: AxisLimit(-100.0, 100.0) for axis in AXIS_NAMES}
    )

    def validate_axis_target(self, axis: str, target: float) -> ToolResult:
        if axis not in self.axis_limits:
            return ToolResult.failure(
                state="motion_rejected",
                message=f"Unknown robot axis: {axis}",
                errors=[{"code": "unknown_axis", "axis": axis}],
            )

        limit = self.axis_limits[axis]
        if target < limit.minimum or target > limit.maximum:
            return ToolResult.failure(
                state="motion_rejected",
                message=(
                    f"Axis {axis} target {target:g} is outside "
                    f"the safe range {limit.minimum:g}..{limit.maximum:g}."
                ),
                errors=[
                    {
                        "code": "axis_limit_exceeded",
                        "axis": axis,
                        "target": target,
                        "minimum": limit.minimum,
                        "maximum": limit.maximum,
                    }
                ],
            )

        return ToolResult.success(state="motion_allowed")
