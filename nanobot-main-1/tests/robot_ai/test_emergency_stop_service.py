from __future__ import annotations

import json
import threading
import time

import pytest

from robot_platform.application import (
    AuthenticatedPrincipal,
    EmergencyStopApplicationService,
    RobotEmergencyStopCommand,
)
from robot_platform.backends.emergency_stop import ProductEmergencyStopAdapter
from robot_platform.backends.factory import RobotBackendConfig
from robot_server.emergency_stop_audit import EmergencyStopAuditOutbox


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal("operator", "operator", "session", "test")


class _StopPort:
    def __init__(self) -> None:
        self.calls = 0

    def emergency_stop(self, principal: AuthenticatedPrincipal, **kwargs) -> dict:
        del kwargs
        assert principal == _principal()
        self.calls += 1
        return {"ok": True, "state": "estopped"}


class _RecoveringOutbox:
    def __init__(self) -> None:
        self.available = False
        self.events: list[dict] = []
        self.late_seen = threading.Event()

    def append(self, event: dict) -> None:
        if not self.available:
            raise OSError("disk temporarily unavailable")
        self.events.append(dict(event))
        if event.get("event") == "emergency_stop_result_late":
            self.late_seen.set()


def test_audit_failure_never_blocks_stop_and_events_can_be_flushed_later() -> None:
    port = _StopPort()
    outbox = _RecoveringOutbox()
    service = EmergencyStopApplicationService(port, audit_outbox=outbox)

    result = service.execute(RobotEmergencyStopCommand(_principal()))

    assert result.payload["ok"] is True
    assert port.calls == 1
    assert outbox.events == []
    outbox.available = True
    service.flush_audit()
    assert [event["event"] for event in outbox.events] == [
        "emergency_stop_requested",
        "emergency_stop_result",
    ]
    assert outbox.events[0]["operation_id"] == outbox.events[1]["operation_id"]


def test_adapter_uses_frozen_selected_backend_not_later_environment(monkeypatch) -> None:
    monkeypatch.setenv("ROBOT_AI_BACKEND", "zmotion_readonly")
    selected = RobotBackendConfig(mode="simulation", controller_host="selected-host")
    adapter = ProductEmergencyStopAdapter(config=selected)

    result = adapter.emergency_stop(_principal())

    assert result["ok"] is True
    assert result["state"] == "simulated_system_action_completed"
    assert result["data"]["action"] == "emergency_stop"


def test_blocked_audit_io_never_delays_first_or_concurrent_emergency_stop() -> None:
    entered = threading.Event()
    release = threading.Event()

    class BlockingOutbox:
        def append(self, event: dict) -> None:
            del event
            entered.set()
            release.wait(timeout=5)

    port = _StopPort()
    service = EmergencyStopApplicationService(port, audit_outbox=BlockingOutbox())
    try:
        first = service.execute(RobotEmergencyStopCommand(_principal()))
        assert first.payload["ok"] is True
        assert entered.wait(timeout=1)
        second = service.execute(RobotEmergencyStopCommand(_principal()))
        assert second.payload["ok"] is True
        assert port.calls == 2
    finally:
        release.set()
        service.flush_audit()


def test_zmotion_dispatch_writes_minimum_sequence_without_any_status_read() -> None:
    class WriteOnlyClient:
        connected = False

        def __init__(self) -> None:
            self.writes: list[tuple[int, list[float | int]]] = []

        def connect(self) -> None:
            self.connected = True

        def disconnect(self) -> None:
            self.connected = False

        def dispatch_emergency_stop(self, claim_authority) -> int:
            assert claim_authority() is True
            self.writes.extend([
                (0, [104.0]), (2, [1.0]), (4, [0.0]),
                (6, [0.0]), (8, [0.0]), (32, [1.0]),
            ])
            return 6

    client = WriteOnlyClient()
    adapter = ProductEmergencyStopAdapter(
        config=RobotBackendConfig(mode="zmotion_readonly"),
        client_factory=lambda config: client,
    )

    result = adapter.emergency_stop(_principal())

    assert result["ok"] is True
    assert client.writes == [
        (0, [104.0]), (2, [1.0]), (4, [0.0]),
        (6, [0.0]), (8, [0.0]), (32, [1.0]),
    ]


def test_blocked_controller_call_has_bounded_application_wait() -> None:
    release = threading.Event()

    class BlockingClient:
        connected = False

        def connect(self) -> None:
            release.wait(timeout=2)
            self.connected = True

        def disconnect(self) -> None:
            self.connected = False

        def write_modbus_float(self, request, **kwargs) -> None:
            del request, kwargs

        def dispatch_emergency_stop(self, claim_authority) -> int:
            assert claim_authority()
            return 6

    adapter = ProductEmergencyStopAdapter(
        config=RobotBackendConfig(mode="zmotion_readonly"),
        client_factory=lambda config: BlockingClient(),
        dispatch_timeout_sec=0.05,
    )
    service = EmergencyStopApplicationService(adapter)
    started = time.monotonic()
    try:
        response = service.execute(RobotEmergencyStopCommand(_principal()))
    finally:
        release.set()

    assert time.monotonic() - started < 0.5
    assert response.error.code == "emergency_stop_outcome_unknown"


@pytest.mark.parametrize("raw", [None, {}, {"ok": True}, {"ok": "yes", "state": "x"}])
def test_malformed_port_result_is_sanitized(raw) -> None:
    class BadPort:
        def emergency_stop(self, principal, **kwargs):
            del kwargs
            del principal
            return raw

    response = EmergencyStopApplicationService(BadPort()).execute(
        RobotEmergencyStopCommand(_principal())
    )

    assert response.payload is None
    assert response.error.code == "emergency_stop_outcome_unknown"


def test_port_exception_details_never_cross_application_boundary() -> None:
    class LeakingPort:
        def emergency_stop(self, principal, **kwargs):
            del kwargs
            del principal
            raise RuntimeError("secret-host C:/vendor/sdk.dll")

    response = EmergencyStopApplicationService(LeakingPort()).execute(
        RobotEmergencyStopCommand(_principal())
    )

    rendered = repr(response)
    assert response.error.code == "emergency_stop_outcome_unknown"
    assert "secret-host" not in rendered
    assert "sdk.dll" not in rendered


def test_full_audit_queue_drops_events_without_delaying_stop() -> None:
    entered = threading.Event()
    release = threading.Event()

    class BlockingOutbox:
        def append(self, event):
            del event
            entered.set()
            release.wait(timeout=5)

    service = EmergencyStopApplicationService(
        _StopPort(), audit_outbox=BlockingOutbox(), audit_queue_capacity=1,
    )
    try:
        service.execute(RobotEmergencyStopCommand(_principal()))
        assert entered.wait(timeout=1)
        started = time.monotonic()
        for _ in range(10):
            response = service.execute(RobotEmergencyStopCommand(_principal()))
            assert response.ok
        assert time.monotonic() - started < 0.5
        assert service.dropped_audit_count > 0
    finally:
        release.set()
        service.close(timeout=1)


def test_durable_spool_recovers_unflushed_event_after_restart(tmp_path) -> None:
    path = tmp_path / "emergency.jsonl"
    first = EmergencyStopAuditOutbox(path, capacity=8)
    assert first.spool({"event": "emergency_stop_requested", "operation_id": "op-1"})
    first.close()

    recovered = EmergencyStopAuditOutbox(path, capacity=8)
    try:
        assert recovered.flush_spool() == 1
    finally:
        recovered.close()

    assert json.loads(path.read_text(encoding="utf-8"))["operation_id"] == "op-1"


def test_timeout_records_late_terminal_outcome_with_same_operation_id() -> None:
    release = threading.Event()
    outbox = _RecoveringOutbox()
    outbox.available = True

    class SlowAtomicClient:
        connected = False

        def connect(self) -> None:
            self.connected = True

        def disconnect(self) -> None:
            self.connected = False

        def dispatch_emergency_stop(self, claim_authority) -> int:
            assert claim_authority()
            release.wait(timeout=2)
            return 6

    adapter = ProductEmergencyStopAdapter(
        config=RobotBackendConfig(mode="zmotion_readonly"),
        client_factory=lambda config: SlowAtomicClient(),
        dispatch_timeout_sec=0.05,
    )
    service = EmergencyStopApplicationService(adapter, audit_outbox=outbox)
    response = service.execute(RobotEmergencyStopCommand(_principal()))
    assert response.error.code == "emergency_stop_outcome_unknown"
    release.set()
    assert outbox.late_seen.wait(timeout=5)
    service.flush_audit()
    service.close(timeout=1)

    events = outbox.events
    requested = next(event for event in events if event["event"] == "emergency_stop_requested")
    unknown = next(event for event in events if event["event"] == "emergency_stop_result_unknown")
    late = next(event for event in events if event["event"] == "emergency_stop_result_late")
    assert {requested["operation_id"], unknown["operation_id"], late["operation_id"]} == {
        requested["operation_id"]
    }
    assert late["ok"] is True


def test_production_spool_absorbs_queue_pressure_without_request_io(tmp_path) -> None:
    entered = threading.Event()
    release = threading.Event()
    outbox = EmergencyStopAuditOutbox(tmp_path / "audit.jsonl", capacity=64)
    durable_append = outbox.append

    def blocked_append(event):
        entered.set()
        release.wait(timeout=5)
        durable_append(event)

    outbox.append = blocked_append
    service = EmergencyStopApplicationService(
        _StopPort(), audit_outbox=outbox, audit_queue_capacity=1,
    )
    try:
        service.execute(RobotEmergencyStopCommand(_principal()))
        assert entered.wait(timeout=1)
        started = time.monotonic()
        for _ in range(10):
            assert service.execute(RobotEmergencyStopCommand(_principal())).ok
        assert time.monotonic() - started < 0.5
        assert service.dropped_audit_count == 0
    finally:
        release.set()
        service.flush_audit()
        service.close(timeout=1)


def test_blocked_worker_releases_spool_lease_after_delayed_exit(tmp_path) -> None:
    path = tmp_path / "lease.jsonl"
    entered = threading.Event()
    release = threading.Event()
    outbox = EmergencyStopAuditOutbox(path, capacity=16)
    durable_append = outbox.append

    def blocked_append(event):
        entered.set()
        release.wait(timeout=5)
        durable_append(event)

    outbox.append = blocked_append
    service = EmergencyStopApplicationService(_StopPort(), audit_outbox=outbox)
    service.execute(RobotEmergencyStopCommand(_principal()))
    assert entered.wait(timeout=1)

    service.close(timeout=0.01)
    with pytest.raises(RuntimeError, match="already open"):
        EmergencyStopAuditOutbox(path, capacity=16)

    release.set()
    service._worker.join(timeout=5)
    assert not service._worker.is_alive()
    reopened = EmergencyStopAuditOutbox(path, capacity=16)
    reopened.close()


def test_spool_capacity_exhaustion_persists_overflow_alert(tmp_path) -> None:
    path = tmp_path / "overflow.jsonl"
    outbox = EmergencyStopAuditOutbox(path, capacity=8)
    for index in range(8):
        assert outbox.spool({"event": "queued", "index": index}) is True
    assert outbox.spool({"event": "overflow"}) is False
    assert outbox.overflow_count == 1
    outbox.close()

    recovered = EmergencyStopAuditOutbox(path, capacity=8)
    try:
        assert recovered.overflow_count == 1
        recovered.flush_spool()
        assert recovered.overflow_count == 0
    finally:
        recovered.close()
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert records[-1] == {
        "event": "emergency_stop_audit_overflow", "dropped_event_count": 1,
    }
