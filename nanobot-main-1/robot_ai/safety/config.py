"""Safety limits consumed by the L1 precheck layer.

Ported from the legacy Qt project's ``AxisRangeConfig``
(``robot_modbus_lite/system_config.py``), keeping only the fields the safety
services read. Defaults match the production robot's calibrated limits
(legacy ``DEFAULT_SYSTEM_CONFIG``). Phase 1 has no file IO — limits are an
in-memory frozen dataclass; a JSON loader can be added later if needed.
"""

from __future__ import annotations

from dataclasses import dataclass

# Z-axis pivot (mm) for the cylinder/hemisphere R-zone model used by the L1
# target-radius check. Robot-geometry constant — kept explicit, not re-derived.
Z_PIVOT_MM: float = 650.0


@dataclass(frozen=True)
class SafetyLimits:
    """Runtime safety limits read by SafetyPrecheckService and friends."""

    x: tuple[float, float] = (-3000.0, 3000.0)
    y: tuple[float, float] = (-3000.0, 3000.0)
    z: tuple[float, float] = (0.0, 3000.0)
    safe_r_min: float = 200.0
    safe_r_max: float = 1800.0
    safe_z_min: float = 0.0
    safe_z_max: float = 2500.0
    safe_speed_max: float = 150.0
    safe_acc_max: float = 150.0
    safe_dec_max: float = 150.0
    joint_limits: tuple[tuple[float, float], ...] = ()

    @classmethod
    def default(cls) -> "SafetyLimits":
        return cls()
