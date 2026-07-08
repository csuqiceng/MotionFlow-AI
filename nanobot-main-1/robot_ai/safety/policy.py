"""Safety policy and L1 service facade for robot actions."""

from __future__ import annotations

from dataclasses import dataclass, field

from robot_ai.models import AXIS_NAMES, ToolResult
from robot_ai.safety.checker import RobotSafetyChecker
from robot_ai.safety.config import SafetyLimits
from robot_ai.safety.precheck import SafetyPrecheckService
from robot_ai.safety.sandbox import TemporarySafetySandbox
from robot_ai.safety.suggestion import SafetySuggestionService


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


@dataclass(frozen=True)
class SafetyServices:
    """Bundles the L1 safety services constructed from a single SafetyLimits.

    The operator-control path imports this facade instead of wiring each
    service separately. All services share the same ``limits`` instance.
    """

    limits: SafetyLimits
    precheck: SafetyPrecheckService
    suggestion: SafetySuggestionService
    checker: RobotSafetyChecker
    sandbox: TemporarySafetySandbox

    @classmethod
    def from_limits(cls, limits: SafetyLimits | None = None) -> "SafetyServices":
        resolved = limits or SafetyLimits.default()
        # The legacy origin-sphere check (sqrt(x²+y²+z²) <= 1200) is disabled
        # here: this robot's nominal working pose [900,0,1000] has an origin
        # sphere radius of ~1345, so the legacy 1200 constant would block most
        # of the workspace. The pivot-sphere bound against safe_r_max (centred
        # at the Z_PIVOT_MM pivot) already provides the geometric envelope.
        precheck = SafetyPrecheckService(resolved, max_sphere_radius=0.0)
        return cls(
            limits=resolved,
            precheck=precheck,
            suggestion=SafetySuggestionService(resolved),
            checker=RobotSafetyChecker(l1_service=precheck),
            sandbox=TemporarySafetySandbox(),
        )
