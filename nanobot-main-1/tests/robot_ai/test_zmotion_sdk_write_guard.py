from __future__ import annotations

from pathlib import Path
import threading

import pytest

from robot_ai.backends.zmotion_sdk import (
    ModbusWriteRequest,
    ZMotionSdkClient,
    ZMotionSdkConfig,
    ZMotionSdkError,
)


class FakeWritableDevice:
    def __init__(self) -> None:
        self.float_writes: list[tuple[int, int, list[float]]] = []
        self.long_writes: list[tuple[int, int, list[int]]] = []

    def ZAux_OpenEth(self, host: str) -> int:
        return 0

    def ZAux_Modbus_Set4x_Float(self, start_vr: int, count: int, values: list[float]) -> int:
        self.float_writes.append((start_vr, count, list(values)))
        return 0

    def ZAux_Modbus_Set4x_Long(self, start_vr: int, count: int, values: list[int]) -> int:
        self.long_writes.append((start_vr, count, list(values)))
        return 0


class FakeWritableSdkModule:
    def __init__(self, device: FakeWritableDevice) -> None:
        self.device = device

    def ZAUXDLL(self) -> FakeWritableDevice:
        return self.device


def _client(device: FakeWritableDevice) -> ZMotionSdkClient:
    client = ZMotionSdkClient(
        host="10.168.3.21",
        sdk_config=ZMotionSdkConfig(wrapper_path=Path("unused.py"), dll_dir=Path(".")),
        sdk_module=FakeWritableSdkModule(device),
    )
    client.connect()
    return client


def test_zmotion_sdk_write_methods_are_disabled_by_default() -> None:
    device = FakeWritableDevice()
    client = _client(device)

    with pytest.raises(ZMotionSdkError, match="Real ZMotion writes are disabled"):
        client.write_modbus_float(ModbusWriteRequest(start_vr=32, values=[1.0]))

    with pytest.raises(ZMotionSdkError, match="Real ZMotion writes are disabled"):
        client.write_modbus_long(ModbusWriteRequest(start_vr=34, values=[1]))

    assert device.float_writes == []
    assert device.long_writes == []


def test_zmotion_sdk_write_methods_require_operator_confirmation() -> None:
    device = FakeWritableDevice()
    client = _client(device)

    with pytest.raises(ZMotionSdkError, match="Operator confirmation is required"):
        client.write_modbus_float(
            ModbusWriteRequest(start_vr=32, values=[1.0]),
            allow_real_motion_writes=True,
        )

    assert device.float_writes == []


def test_zmotion_sdk_write_methods_call_vendor_set4x_only_when_explicitly_unlocked() -> None:
    device = FakeWritableDevice()
    client = _client(device)

    client.write_modbus_float(
        ModbusWriteRequest(start_vr=32, values=[1.0]),
        allow_real_motion_writes=True,
        confirmed_real_motion=True,
    )
    client.write_modbus_long(
        ModbusWriteRequest(start_vr=312, values=[1]),
        allow_real_motion_writes=True,
        confirmed_real_motion=True,
    )

    assert device.float_writes == [(32, 1, [1.0])]
    assert device.long_writes == [(312, 1, [1])]


def test_emergency_stop_dispatch_cannot_interleave_with_normal_trigger_transaction() -> None:
    device = FakeWritableDevice()
    normal_client = _client(device)
    emergency_client = _client(device)
    normal_started = threading.Event()
    release_normal = threading.Event()

    def normal_dispatch() -> None:
        with normal_client.write_transaction():
            normal_client.write_modbus_float(
                ModbusWriteRequest(start_vr=0, values=[108.0]),
                allow_real_motion_writes=True, confirmed_real_motion=True,
            )
            normal_started.set()
            assert release_normal.wait(timeout=5)
            normal_client.write_modbus_float(
                ModbusWriteRequest(start_vr=32, values=[1.0]),
                allow_real_motion_writes=True, confirmed_real_motion=True,
            )

    normal = threading.Thread(target=normal_dispatch)
    normal.start()
    assert normal_started.wait(timeout=1)
    emergency = threading.Thread(
        target=lambda: emergency_client.dispatch_emergency_stop(lambda: True),
    )
    emergency.start()
    assert device.float_writes == [(0, 1, [108.0])]
    release_normal.set()
    normal.join(timeout=2)
    emergency.join(timeout=2)

    assert device.float_writes == [
        (0, 1, [108.0]), (32, 1, [1.0]),
        (0, 1, [104.0]), (2, 1, [1.0]), (4, 1, [0.0]),
        (6, 1, [0.0]), (8, 1, [0.0]), (32, 1, [1.0]),
    ]
