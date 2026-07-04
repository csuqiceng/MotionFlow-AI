from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from robot_ai.models import AXIS_NAMES, RobotState, ToolResult


@dataclass(frozen=True)
class ModbusReadRequest:
    start_vr: int
    count: int


class ZMotionReadableClient(Protocol):
    connected: bool

    def connect(self) -> None:
        ...

    def read_modbus_float(self, request: ModbusReadRequest) -> list[float]:
        ...

    def read_modbus_long(self, request: ModbusReadRequest) -> list[int]:
        ...


POSE_FEEDBACK_START = 1612
MOTION_STATE_START = 56
STATUS_LONG_START = 34
ALARM_DETAIL_START = 38

STATUS_ALARM_BIT = 24
STATUS_ESTOP_BIT = 25
STATUS_PAUSED_BIT = 26
STATUS_READY_BIT = 28


class ZMotionReadOnlyBackend:
    """Read-only ZMotion backend used before real motion writes are enabled."""

    def __init__(
        self,
        *,
        client_factory: Callable[[str], ZMotionReadableClient],
        host: str,
    ) -> None:
        self._client_factory = client_factory
        self._host = host
        self._client: ZMotionReadableClient | None = None

    def get_state(self) -> RobotState:
        try:
            client = self._get_client()
            pose = self._read_floats(client, POSE_FEEDBACK_START, len(AXIS_NAMES))
            status_raw = self._read_longs(client, STATUS_LONG_START, 1)[0]
            alarm_detail = self._read_longs(client, ALARM_DETAIL_START, 1)[0]
            motion_state = self._read_floats(client, MOTION_STATE_START, 1)[0]
        except Exception as exc:
            return RobotState(
                mode="disconnected",
                connected_real_device=False,
                alarms=[f"controller_read_failed: {type(exc).__name__}: {exc}"],
            )

        axes = {axis: float(pose[index]) for index, axis in enumerate(AXIS_NAMES)}
        return RobotState(
            mode=self._mode_from_status(status_raw=status_raw, alarm_detail=alarm_detail, motion_state=motion_state),
            axes_mm=axes,
            alarms=self._alarms_from_status(status_raw=status_raw, alarm_detail=alarm_detail),
            connected_real_device=True,
        )

    def move_axis(self, axis: str, delta: float) -> ToolResult:
        return self._readonly_rejection("move_axis", {"axis": axis, "delta": float(delta)})

    def home(self) -> ToolResult:
        return self._readonly_rejection("home")

    def stop(self) -> ToolResult:
        return self._readonly_rejection("stop")

    def _get_client(self) -> ZMotionReadableClient:
        if self._client is not None and getattr(self._client, "connected", False):
            return self._client

        client = self._client_factory(self._host)
        client.connect()
        self._client = client
        return client

    @staticmethod
    def _read_floats(client: ZMotionReadableClient, start_vr: int, count: int) -> list[float]:
        values = list(client.read_modbus_float(ModbusReadRequest(start_vr=start_vr, count=count)))
        return [float(value) for value in values[:count]] + [0.0] * max(0, count - len(values))

    @staticmethod
    def _read_longs(client: ZMotionReadableClient, start_vr: int, count: int) -> list[int]:
        values = list(client.read_modbus_long(ModbusReadRequest(start_vr=start_vr, count=count)))
        return [int(value) for value in values[:count]] + [0] * max(0, count - len(values))

    @staticmethod
    def _status_bit(status_raw: int, bit: int) -> bool:
        return (int(status_raw) & (1 << bit)) != 0

    @classmethod
    def _mode_from_status(cls, *, status_raw: int, alarm_detail: int, motion_state: float) -> str:
        if cls._status_bit(status_raw, STATUS_ALARM_BIT) or int(alarm_detail) != 0:
            return "alarm"
        if cls._status_bit(status_raw, STATUS_ESTOP_BIT):
            return "stopped"
        if cls._status_bit(status_raw, STATUS_PAUSED_BIT):
            return "paused"
        if int(float(motion_state)) == 1:
            return "moving"
        if cls._status_bit(status_raw, STATUS_READY_BIT):
            return "idle"
        return "initializing"

    @classmethod
    def _alarms_from_status(cls, *, status_raw: int, alarm_detail: int) -> list[str]:
        alarms: list[str] = []
        if cls._status_bit(status_raw, STATUS_ALARM_BIT):
            alarms.append("controller_alarm")
        if cls._status_bit(status_raw, STATUS_ESTOP_BIT):
            alarms.append("emergency_stop")
        if int(alarm_detail) != 0:
            alarms.append(f"alarm_detail_{int(alarm_detail)}")
        return alarms

    @staticmethod
    def _readonly_rejection(action: str, data: dict | None = None) -> ToolResult:
        return ToolResult.failure(
            state="real_control_disabled",
            message="ZMotion backend is read-only; real control writes are not enabled yet.",
            data={"action": action, **(data or {})},
            errors=[{"code": "readonly_backend"}],
        )
