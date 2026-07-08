from __future__ import annotations

from pathlib import Path

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
