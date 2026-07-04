from __future__ import annotations

from pathlib import Path

import robot_ai.backends.factory as backend_factory_module
from robot_ai.bridge import RobotApi
from robot_ai.backends.factory import RobotBackendConfig, create_robot_backend
from robot_ai.backends.zmotion_sdk import ZMotionSdkClient, ZMotionSdkConfig
from robot_ai.backends.zmotion_backend import ZMotionReadOnlyBackend
from robot_ai.models import RobotState, ToolResult


class FakeZMotionClient:
    def __init__(self) -> None:
        self.connected = False
        self.float_reads: list[tuple[int, int]] = []
        self.long_reads: list[tuple[int, int]] = []
        self.writes: list[object] = []

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def read_modbus_float(self, request) -> list[float]:
        self.float_reads.append((request.start_vr, request.count))
        if request.start_vr == 1612:
            return [1000.0, 0.0, 800.0, 0.0, 90.0, 0.0]
        if request.start_vr == 56:
            return [0.0]
        return [0.0] * request.count

    def read_modbus_long(self, request) -> list[int]:
        self.long_reads.append((request.start_vr, request.count))
        if request.start_vr == 34:
            return [1 << 28]
        if request.start_vr == 38:
            return [0]
        return [0] * request.count

    def write_modbus_float(self, request) -> None:
        self.writes.append(request)


def test_get_state_reads_zmotion_pose_and_status_without_writing() -> None:
    fake_client = FakeZMotionClient()
    backend = ZMotionReadOnlyBackend(client_factory=lambda host: fake_client, host="10.168.3.21")

    state = backend.get_state()

    assert isinstance(state, RobotState)
    assert state.connected_real_device is True
    assert state.mode == "idle"
    assert state.axes_mm == {"x": 1000.0, "y": 0.0, "z": 800.0, "rx": 0.0, "ry": 90.0, "rz": 0.0}
    assert state.alarms == []
    assert (1612, 6) in fake_client.float_reads
    assert (56, 1) in fake_client.float_reads
    assert (34, 1) in fake_client.long_reads
    assert (38, 1) in fake_client.long_reads
    assert fake_client.writes == []


def test_readonly_backend_reports_alarm_bits_from_controller_status() -> None:
    class AlarmClient(FakeZMotionClient):
        def read_modbus_long(self, request) -> list[int]:
            self.long_reads.append((request.start_vr, request.count))
            if request.start_vr == 34:
                return [(1 << 24) | (1 << 28)]
            if request.start_vr == 38:
                return [64]
            return [0] * request.count

    backend = ZMotionReadOnlyBackend(client_factory=lambda host: AlarmClient(), host="10.168.3.21")

    state = backend.get_state()

    assert state.mode == "alarm"
    assert "controller_alarm" in state.alarms
    assert "alarm_detail_64" in state.alarms


def test_readonly_backend_rejects_motion_and_control_methods() -> None:
    fake_client = FakeZMotionClient()
    backend = ZMotionReadOnlyBackend(client_factory=lambda host: fake_client, host="10.168.3.21")

    move_result = backend.move_axis("x", 10.0)
    home_result = backend.home()
    stop_result = backend.stop()

    for result in (move_result, home_result, stop_result):
        assert isinstance(result, ToolResult)
        assert result.ok is False
        assert result.state == "real_control_disabled"
        assert result.errors[0]["code"] == "readonly_backend"
    assert fake_client.writes == []


def test_backend_factory_creates_zmotion_readonly_backend_from_config() -> None:
    fake_client = FakeZMotionClient()

    backend = create_robot_backend(
        RobotBackendConfig(mode="zmotion_readonly", controller_host="10.168.3.21"),
        client_factory=lambda host: fake_client,
    )

    state = backend.get_state()

    assert isinstance(backend, ZMotionReadOnlyBackend)
    assert state.connected_real_device is True
    assert state.axes_mm["x"] == 1000.0


def test_robot_api_uses_backend_factory_for_readonly_real_status() -> None:
    fake_client = FakeZMotionClient()

    api = RobotApi(
        backend_factory=lambda: create_robot_backend(
            RobotBackendConfig(mode="zmotion_readonly", controller_host="10.168.3.21"),
            client_factory=lambda host: fake_client,
        )
    )

    result = api.get_robot_state()

    assert result["ok"] is True
    assert result["data"]["robot_state"]["connected_real_device"] is True
    assert result["data"]["robot_state"]["axes_mm"]["x"] == 1000.0


class FakeZAuxDevice:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def ZAux_OpenEth(self, host: str) -> int:
        self.calls.append(("open", host))
        return 0

    def ZAux_Close(self) -> int:
        self.calls.append(("close",))
        return 0

    def ZAux_Modbus_Get4x_Float(self, start_vr: int, count: int):
        self.calls.append(("read_float", start_vr, count))
        return 0, [float(start_vr), float(count)]

    def ZAux_Modbus_Get4x_Long(self, start_vr: int, count: int):
        self.calls.append(("read_long", start_vr, count))
        return 0, [int(start_vr), int(count)]


class FakeSdkModule:
    def __init__(self, device: FakeZAuxDevice) -> None:
        self.device = device

    def ZAUXDLL(self) -> FakeZAuxDevice:
        return self.device


def test_zmotion_sdk_client_connects_and_reads_via_vendor_module(tmp_path: Path) -> None:
    device = FakeZAuxDevice()
    sdk_config = ZMotionSdkConfig(wrapper_path=tmp_path / "zauxdllPython.py", dll_dir=tmp_path)
    client = ZMotionSdkClient(
        host="10.168.3.21",
        sdk_config=sdk_config,
        sdk_module=FakeSdkModule(device),
    )

    client.connect()
    float_values = client.read_modbus_float(type("Req", (), {"start_vr": 1612, "count": 2})())
    long_values = client.read_modbus_long(type("Req", (), {"start_vr": 34, "count": 1})())
    client.disconnect()

    assert float_values == [1612.0, 2.0]
    assert long_values == [34, 1]
    assert device.calls == [
        ("open", "10.168.3.21"),
        ("read_float", 1612, 2),
        ("read_long", 34, 1),
        ("close",),
    ]


def test_backend_factory_uses_zmotion_sdk_client_when_paths_are_configured(monkeypatch, tmp_path: Path) -> None:
    created: dict[str, object] = {}

    class FakeSdkClient(FakeZMotionClient):
        def __init__(self, *, host: str, sdk_config: ZMotionSdkConfig) -> None:
            super().__init__()
            created["host"] = host
            created["sdk_config"] = sdk_config

    monkeypatch.setattr(backend_factory_module, "ZMotionSdkClient", FakeSdkClient)
    wrapper_path = tmp_path / "zauxdllPython.py"
    dll_dir = tmp_path / "dll"

    backend = create_robot_backend(
        RobotBackendConfig(
            mode="zmotion_readonly",
            controller_host="10.168.3.21",
            zmotion_wrapper_path=str(wrapper_path),
            zmotion_dll_dir=str(dll_dir),
        )
    )
    state = backend.get_state()

    assert state.connected_real_device is True
    assert created["host"] == "10.168.3.21"
    assert created["sdk_config"] == ZMotionSdkConfig(wrapper_path=wrapper_path, dll_dir=dll_dir)
