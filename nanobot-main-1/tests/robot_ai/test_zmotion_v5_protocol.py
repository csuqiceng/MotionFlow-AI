"""V5.0 protocol field-decoding regression tests.

The audit (Phase 2) confirmed the new project's protocol layer matches the
``上位机通讯寄存器说明书V5.0.md`` spec exactly. These tests lock in the
spec-mandated encodings so they cannot silently drift:

- Func parameter VR maps (asserted in test_zmotion_write_plan.py).
- LONG(34) function-state 2-bit fields per function (104/108/110/120) — the
  critical input to completion detection. Spec §6.1.
- LONG(34) system-level status bits (24=alarm, 25=estop, 26=paused, 27=cancel,
  28=ready). Spec §6.1.
- Func110 program-delay parameter address is IEEE(6) (spec §4.2), NOT IEEE(2)
  — the legacy README's "IEEE(2)=delay_sec" note refers to the parameter
  name, not the wire address. Func109 (T0 delay, IEEE(4)) is intentionally not
  implemented; the operator uses Func110 only.
"""

from __future__ import annotations

from robot_ai.backends.zmotion_backend import (
    STATUS_ALARM_BIT,
    STATUS_ESTOP_BIT,
    STATUS_PAUSED_BIT,
    STATUS_READY_BIT,
)
from robot_ai.backends.zmotion_write_executor import (
    _FUNCTION_STATE_FIELDS,
    _function_state,
)


def test_long34_system_bits_match_spec() -> None:
    assert STATUS_ALARM_BIT == 24
    assert STATUS_ESTOP_BIT == 25
    assert STATUS_PAUSED_BIT == 26
    assert STATUS_READY_BIT == 28


def test_function_state_fields_match_spec_masks() -> None:
    # Spec §6.1: 104→bits0-1/$3, 108→bits6-7/$C0, 110→bits10-11/$C00,
    # 120→bits18-19/$C0000.
    assert _FUNCTION_STATE_FIELDS == {
        104: (0, 0x00000003),
        108: (6, 0x000000C0),
        110: (10, 0x00000C00),
        120: (18, 0x000C0000),
    }


def test_function_state_decodes_idle_executing_done_error() -> None:
    # Spec §6.1 2-bit encoding: 0=idle, 1=executing, 2=done, 3=error.
    for func_code, (shift, _) in _FUNCTION_STATE_FIELDS.items():
        idle = 0 << shift
        executing = 1 << shift
        done = 2 << shift
        error = 3 << shift
        assert _function_state(idle, func_code) == 0
        assert _function_state(executing, func_code) == 1
        assert _function_state(done, func_code) == 2
        assert _function_state(error, func_code) == 3


def test_function_state_isolated_from_other_functions_bits() -> None:
    # Func120's done bits (18-19) must not be decoded as Func110 activity.
    func120_done = 2 << 18  # bits 18-19 = done(2)
    assert _function_state(func120_done, 110) == 0  # Func110 sees idle
    assert _function_state(func120_done, 120) == 2  # Func120 sees done

    func108_executing = 1 << 6  # bits 6-7 = executing(1)
    assert _function_state(func108_executing, 108) == 1
    assert _function_state(func108_executing, 110) == 0
