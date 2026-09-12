from __future__ import annotations

import json

from nanobot.cron.service import CronService
from nanobot.utils.run_records import write_run_record
from robot_platform.flow.events import FlowExecutionEvent
from robot_platform.library.migration import _audit_append, verify_audit_chain
from robot_server.emergency_stop_audit import EmergencyStopAuditOutbox
from robot_server.flow_event_audit import JsonlFlowEventSink


def test_numeric_audit_timestamp_includes_readable_utc_value(tmp_path) -> None:
    path = tmp_path / "audit.jsonl"

    _audit_append(path, {"action": "test", "timestamp": 0})

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["timestamp"] == 0
    assert record["timestamp_iso"] == "1970-01-01T00:00:00+00:00"
    verify_audit_chain(path)


def test_flow_event_log_includes_readable_utc_timestamp(tmp_path) -> None:
    path = tmp_path / "flow_events.jsonl"
    sink = JsonlFlowEventSink(path)

    sink.append(FlowExecutionEvent(
        execution_id="execution-1", snapshot_hash="snapshot-1",
        kind="step_completed", timestamp=0,
    ))

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["timestamp"] == 0
    assert record["timestamp_iso"] == "1970-01-01T00:00:00+00:00"


def test_emergency_stop_outbox_includes_readable_utc_timestamp(tmp_path) -> None:
    path = tmp_path / "emergency_stop_outbox.jsonl"
    outbox = EmergencyStopAuditOutbox(path)
    try:
        outbox.append({"event": "emergency_stop_requested", "timestamp": 0})
    finally:
        outbox.close()

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["timestamp"] == 0
    assert record["timestamp_iso"] == "1970-01-01T00:00:00+00:00"


def test_cron_action_log_includes_readable_utc_timestamp(tmp_path) -> None:
    service = CronService(tmp_path / "jobs.json")

    service._append_action("add", {"job_id": "job-1"})

    record = json.loads((tmp_path / "action.jsonl").read_text(encoding="utf-8"))
    assert isinstance(record["timestamp"], float)
    assert record["timestamp_iso"].endswith("+00:00")


def test_automation_run_log_includes_readable_update_timestamp(tmp_path) -> None:
    path = write_run_record(tmp_path, "run-1", {"status": "queued"})

    record = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(record["updated_at_ms"], int)
    assert record["updated_at_iso"].endswith("+00:00")
