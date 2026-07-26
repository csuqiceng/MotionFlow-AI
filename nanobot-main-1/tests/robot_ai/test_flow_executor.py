from __future__ import annotations

import pytest

from robot_ai.flow import FlowEntry, FlowStep, run_flow
from robot_ai.models import ToolResult


def _step(step_id: int, func_id: int, **params) -> FlowStep:
    return FlowStep(step_id=step_id, action="step", func_id=func_id, params=params)


def _patch_runner(monkeypatch: pytest.MonkeyPatch, fail_on_command: str | None = None):
    seen = []

    def fake_runner(*, request, config=None, client_factory=None, executor_factory=None):
        seen.append(request)
        if fail_on_command is not None and request.command == fail_on_command:
            return ToolResult.failure(
                state="zmotion_operator_unsupported_command",
                message="fake failure",
                errors=[{"code": "fake_failure"}],
            ).to_dict()
        return ToolResult.success(state="zmotion_operator_dry_run", data={}).to_dict()

    import robot_platform.flow.executor as executor_module

    monkeypatch.setattr(executor_module, "run_operator_command", fake_runner)
    return seen


def test_empty_flow_returns_flow_empty() -> None:
    result = run_flow(FlowEntry(name="Empty", steps=[]))
    assert result["ok"] is False
    assert result["state"] == "flow_empty"


def test_run_flow_maps_steps_to_operator_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _patch_runner(monkeypatch)
    entry = FlowEntry(
        name="PickPlace",
        steps=[
            _step(
                1,
                108,
                target_pose={"x": 900.0, "y": 0.0, "z": 999.0, "rx": 0.0, "ry": 0.0, "rz": 0.0},
                speed_pct=5.0,
                acceleration_pct=5.0,
                deceleration_pct=5.0,
            ),
            _step(2, 110, seconds=2.0),
            _step(3, 120, io_number=4, enabled=True, allowed_io_channels=[4]),
        ],
    )

    result = run_flow(entry)

    assert result["ok"] is True
    assert result["state"] == "flow_completed"
    assert result["data"]["total_steps"] == 3
    assert [r["step_index"] for r in result["data"]["results"]] == [1, 2, 3]

    assert [request.command for request in seen] == ["linear_move", "delay", "io"]
    assert seen[0].parameters["target_pose"]["x"] == 900.0
    assert seen[1].parameters["seconds"] == 2.0
    assert seen[2].parameters["io_number"] == 4


def test_legacy_target_x_keys_are_accepted_for_linear_move(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _patch_runner(monkeypatch)
    entry = FlowEntry(
        name="Legacy",
        steps=[
            _step(1, 108, target_x=900.0, target_y=0.0, target_z=999.0, target_rx=0.0,
                  target_ry=0.0, target_rz=0.0, speed_pct=5.0),
        ],
    )

    run_flow(entry)
    pose = seen[0].parameters["target_pose"]
    assert pose == {"x": 900.0, "y": 0.0, "z": 999.0, "rx": 0.0, "ry": 0.0, "rz": 0.0}


def test_run_flow_stops_on_first_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _patch_runner(monkeypatch, fail_on_command="delay")
    entry = FlowEntry(
        name="FailMidway",
        steps=[
            _step(1, 108, target_pose={"x": 900.0, "y": 0.0, "z": 999.0, "rx": 0.0, "ry": 0.0, "rz": 0.0}),
            _step(2, 110, seconds=1.0),   # fails
            _step(3, 120, io_number=4, enabled=True, allowed_io_channels=[4]),  # must not run
        ],
    )

    result = run_flow(entry)

    assert result["ok"] is False
    assert result["state"] == "flow_step_failed"
    assert result["data"]["failed_step_index"] == 2
    assert result["data"]["completed_steps"] == 1
    assert len(seen) == 2  # third step never submitted


def test_run_flow_stops_before_a_step_when_execution_control_requests_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _patch_runner(monkeypatch)
    entry = FlowEntry(
        name="Controlled",
        steps=[_step(1, 110, seconds=1.0), _step(2, 110, seconds=1.0)],
    )
    allowed = iter([True, False])

    result = run_flow(entry, before_step=lambda _index: next(allowed))

    assert result["ok"] is False
    assert result["state"] == "flow_stopped"
    assert result["data"]["completed_steps"] == 1
    assert len(seen) == 1


def test_execute_real_and_confirmation_propagate_to_each_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _patch_runner(monkeypatch)
    entry = FlowEntry(
        name="Real",
        steps=[_step(1, 110, seconds=1.0)],
    )

    run_flow(
        entry,
        execute_real=True,
        confirm_work_area_clear=True,
        confirm_estop_ready=True,
        confirmation_code="EXECUTE_ZMOTION_REAL",
    )

    request = seen[0]
    assert request.execute_real is True
    assert request.confirm_work_area_clear is True
    assert request.confirm_estop_ready is True
    assert request.confirmation_code == "EXECUTE_ZMOTION_REAL"


def test_unsupported_func_id_step_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _patch_runner(monkeypatch)  # never returns failure for "unsupported" command
    # The operator runner fake always succeeds, but the step maps func 999 to the
    # "unsupported" command whose parameters carry the func_id. Verify the mapping.
    entry = FlowEntry(name="Bad", steps=[_step(1, 999)])
    run_flow(entry)
    assert seen[0].command == "unsupported"
    assert seen[0].parameters == {"func_id": 999}
