from __future__ import annotations

from robot_ai.safety import SafetyLimits, Z_PIVOT_MM


def test_default_limits_match_production_calibration() -> None:
    limits = SafetyLimits.default()
    assert limits.x == (-3000.0, 3000.0)
    assert limits.y == (-3000.0, 3000.0)
    assert limits.z == (0.0, 3000.0)
    assert limits.safe_r_min == 200.0
    assert limits.safe_r_max == 1800.0
    assert limits.safe_z_min == 0.0
    assert limits.safe_z_max == 2500.0
    assert limits.safe_speed_max == 100.0
    assert limits.safe_acc_max == 100.0
    assert limits.safe_dec_max == 100.0
    assert limits.joint_limits == ()


def test_z_pivot_is_legacy_geometry_constant() -> None:
    assert Z_PIVOT_MM == 650.0


def test_limits_are_frozen() -> None:
    limits = SafetyLimits.default()
    try:
        limits.safe_speed_max = 10.0  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("SafetyLimits should be frozen")
