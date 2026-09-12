from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from robot_platform.backends.zmotion_backend import ModbusReadRequest


class ZMotionSdkError(RuntimeError):
    pass


_CONTROLLER_LOCKS_GUARD = threading.Lock()
_CONTROLLER_LOCKS: dict[str, threading.RLock] = {}


def _controller_write_lock(host: str) -> threading.RLock:
    key = str(host).strip().lower()
    with _CONTROLLER_LOCKS_GUARD:
        return _CONTROLLER_LOCKS.setdefault(key, threading.RLock())


@dataclass(frozen=True)
class ZMotionSdkConfig:
    wrapper_path: Path
    dll_dir: Path


@dataclass(frozen=True)
class ModbusWriteRequest:
    start_vr: int
    values: list[float | int]

    @property
    def count(self) -> int:
        return len(self.values)


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
        # Every SDK client targeting the same controller shares one transaction
        # lock, including separate status/operator/emergency connections.
        self._lock = _controller_write_lock(host)
        self.connected = False

    def connect(self) -> None:
        with self._lock:
            ret = self._device.ZAux_OpenEth(self.host)
            self._ensure_ok(ret, f"connect({self.host})")
            self.connected = True

    def disconnect(self) -> None:
        with self._lock:
            if not self.connected:
                return
            ret = self._device.ZAux_Close()
            self._ensure_ok(ret, "disconnect")
            self.connected = False

    def read_modbus_float(self, request: ModbusReadRequest) -> list[float]:
        with self._lock:
            if not self.connected:
                raise ZMotionSdkError("ZMotion controller is not connected.")
            ret, values = self._device.ZAux_Modbus_Get4x_Float(request.start_vr, request.count)
            self._ensure_ok(ret, "ZAux_Modbus_Get4x_Float")
            return [float(value) for value in values]

    def read_modbus_long(self, request: ModbusReadRequest) -> list[int]:
        with self._lock:
            if not self.connected:
                raise ZMotionSdkError("ZMotion controller is not connected.")
            ret, values = self._device.ZAux_Modbus_Get4x_Long(request.start_vr, request.count)
            self._ensure_ok(ret, "ZAux_Modbus_Get4x_Long")
            return [int(value) for value in values]

    def write_modbus_float(
        self,
        request: ModbusWriteRequest,
        *,
        allow_real_motion_writes: bool = False,
        confirmed_real_motion: bool = False,
    ) -> None:
        with self._lock:
            self._ensure_write_allowed(
                allow_real_motion_writes=allow_real_motion_writes,
                confirmed_real_motion=confirmed_real_motion,
            )
            ret = self._device.ZAux_Modbus_Set4x_Float(
                request.start_vr,
                request.count,
                [float(value) for value in request.values],
            )
            self._ensure_ok(ret, "ZAux_Modbus_Set4x_Float")

    @contextmanager
    def write_transaction(self):
        """Serialize one parameter/echo/trigger submission on this controller."""
        with self._lock:
            yield

    def dispatch_emergency_stop(self, claim_authority: Any) -> int:
        """Atomically claim safety authority and submit the minimum Func104 stop."""
        with self._lock:
            if not self.connected:
                raise ZMotionSdkError("ZMotion controller is not connected.")
            if not callable(claim_authority) or claim_authority() is not True:
                raise ZMotionSdkError("Emergency-stop authority is unavailable.")
            submitted = 0
            for vr, value in (
                (0, 104.0), (2, 1.0), (4, 0.0),
                (6, 0.0), (8, 0.0), (32, 1.0),
            ):
                ret = self._device.ZAux_Modbus_Set4x_Float(vr, 1, [value])
                self._ensure_ok(ret, "ZAux_Modbus_Set4x_Float")
                submitted += 1
            return submitted

    def write_modbus_long(
        self,
        request: ModbusWriteRequest,
        *,
        allow_real_motion_writes: bool = False,
        confirmed_real_motion: bool = False,
    ) -> None:
        with self._lock:
            self._ensure_write_allowed(
                allow_real_motion_writes=allow_real_motion_writes,
                confirmed_real_motion=confirmed_real_motion,
            )
            ret = self._device.ZAux_Modbus_Set4x_Long(
                request.start_vr,
                request.count,
                [int(value) for value in request.values],
            )
            self._ensure_ok(ret, "ZAux_Modbus_Set4x_Long")

    def _ensure_write_allowed(
        self,
        *,
        allow_real_motion_writes: bool,
        confirmed_real_motion: bool,
    ) -> None:
        if not allow_real_motion_writes:
            raise ZMotionSdkError("Real ZMotion writes are disabled in this build path.")
        if not confirmed_real_motion:
            raise ZMotionSdkError("Operator confirmation is required before real ZMotion writes.")
        if not self.connected:
            raise ZMotionSdkError("ZMotion controller is not connected.")

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
