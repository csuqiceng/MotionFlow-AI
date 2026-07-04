from __future__ import annotations

import contextlib
import importlib.util
import io
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from robot_ai.backends.zmotion_backend import ModbusReadRequest


class ZMotionSdkError(RuntimeError):
    pass


@dataclass(frozen=True)
class ZMotionSdkConfig:
    wrapper_path: Path
    dll_dir: Path


class ZMotionSdkClient:
    """Read-only wrapper around the vendor ZMotion Python/DLL SDK."""

    def __init__(
        self,
        *,
        host: str,
        sdk_config: ZMotionSdkConfig,
        sdk_module: Any | None = None,
    ) -> None:
        self.host = host
        self.sdk_config = sdk_config
        self._sdk_module = sdk_module or load_zmotion_sdk_module(sdk_config)
        self._device = self._sdk_module.ZAUXDLL()
        self.connected = False

    def connect(self) -> None:
        ret = self._device.ZAux_OpenEth(self.host)
        self._ensure_ok(ret, f"connect({self.host})")
        self.connected = True

    def disconnect(self) -> None:
        if not self.connected:
            return
        ret = self._device.ZAux_Close()
        self._ensure_ok(ret, "disconnect")
        self.connected = False

    def read_modbus_float(self, request: ModbusReadRequest) -> list[float]:
        if not self.connected:
            raise ZMotionSdkError("ZMotion controller is not connected.")
        ret, values = self._device.ZAux_Modbus_Get4x_Float(request.start_vr, request.count)
        self._ensure_ok(ret, "ZAux_Modbus_Get4x_Float")
        return [float(value) for value in values]

    def read_modbus_long(self, request: ModbusReadRequest) -> list[int]:
        if not self.connected:
            raise ZMotionSdkError("ZMotion controller is not connected.")
        ret, values = self._device.ZAux_Modbus_Get4x_Long(request.start_vr, request.count)
        self._ensure_ok(ret, "ZAux_Modbus_Get4x_Long")
        return [int(value) for value in values]

    @staticmethod
    def _ensure_ok(ret: int, action: str) -> None:
        if int(ret) != 0:
            raise ZMotionSdkError(f"{action} failed with code {ret}")


def load_zmotion_sdk_module(config: ZMotionSdkConfig) -> Any:
    wrapper_path = Path(config.wrapper_path)
    dll_dir = Path(config.dll_dir)
    if not wrapper_path.exists():
        raise ZMotionSdkError(f"ZMotion SDK wrapper not found: {wrapper_path}")
    if not dll_dir.exists():
        raise ZMotionSdkError(f"ZMotion SDK DLL directory not found: {dll_dir}")

    spec = importlib.util.spec_from_file_location("robot_ai_vendor_zaux", wrapper_path)
    if spec is None or spec.loader is None:
        raise ZMotionSdkError(f"Unable to load ZMotion SDK wrapper: {wrapper_path}")

    module = importlib.util.module_from_spec(spec)
    old_cwd = Path.cwd()
    old_path = os.environ.get("PATH", "")
    try:
        os.chdir(dll_dir)
        os.environ["PATH"] = f"{dll_dir}{os.pathsep}{old_path}"
        with contextlib.redirect_stdout(io.StringIO()):
            spec.loader.exec_module(module)
    finally:
        os.chdir(old_cwd)
        os.environ["PATH"] = old_path
    return module
