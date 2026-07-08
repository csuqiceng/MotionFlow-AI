from __future__ import annotations

from robot_ai.safety import TemporarySafetySandbox, TemporarySafetySandboxConfig


def _record(**params) -> dict:
    base = {"target_x": 900.0, "target_y": 0.0, "target_z": 1000.0}
    base.update(params)
    return {
        "func_id": 108,
        "params": base,
        "query_key": "step",
        "description": "move",
    }


def test_z_out_of_range_blocked() -> None:
    sandbox = TemporarySafetySandbox(TemporarySafetySandboxConfig(z_max=1500.0))
    result = sandbox.check_records([_record(target_z=2000.0)])
    assert result.ok is False
    assert result.reason_code == "POSITION_OUT_OF_RANGE"
    assert result.failed_step_index == 1


def test_radius_out_of_range_blocked() -> None:
    sandbox = TemporarySafetySandbox(TemporarySafetySandboxConfig(radius_max=1000.0))
    result = sandbox.check_records([_record(target_x=2000.0)])
    assert result.ok is False
    assert result.reason_code == "POSITION_OUT_OF_RANGE"


def test_speed_over_limit_blocked() -> None:
    sandbox = TemporarySafetySandbox(TemporarySafetySandboxConfig(speed_max=100.0))
    result = sandbox.check_records([_record(spd_pct=150.0)])
    assert result.ok is False
    assert result.reason_code == "MOTION_PARAM_OUT_OF_RANGE"


def test_non_func108_record_skipped() -> None:
    # Non-Func108 records bypass position checks: a z that would otherwise fail
    # is allowed through because the record is skipped.
    sandbox = TemporarySafetySandbox(TemporarySafetySandboxConfig(z_max=1500.0))
    result = sandbox.check_records(
        [{"func_id": 104, "params": {"target_z": 99999.0}, "query_key": "k"}]
    )
    assert result.ok is True


def test_disabled_config_passes_everything() -> None:
    sandbox = TemporarySafetySandbox(TemporarySafetySandboxConfig(enabled=False))
    result = sandbox.check_records([_record(target_x=99999.0, target_z=99999.0)])
    assert result.ok is True
    assert result.reason_code == "DISABLED"


def test_multi_step_reports_failed_step_index() -> None:
    sandbox = TemporarySafetySandbox(TemporarySafetySandboxConfig(z_max=1500.0))
    records = [_record(target_z=1000.0), _record(target_z=2000.0)]
    result = sandbox.check_records(records)
    assert result.ok is False
    assert result.failed_step_index == 2


def test_accepts_legacy_attribute_records() -> None:
    class LegacyRecord:
        func_num = 108
        params = {"target_x": 900.0, "target_y": 0.0, "target_z": 2000.0}
        description = "move"
        query_key = "legacy"

    sandbox = TemporarySafetySandbox(TemporarySafetySandboxConfig(z_max=1500.0))
    result = sandbox.check_records([LegacyRecord()])
    assert result.ok is False
    assert result.reason_code == "POSITION_OUT_OF_RANGE"
