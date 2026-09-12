from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

from robot_platform.models import (
    AXIS_NAMES,
    ControllerCapabilities,
    DEFAULT_SIX_AXIS_MODEL,
    RobotModel,
    RobotState,
    ToolResult,
)


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


JOINT_FEEDBACK_START = 1600
POSE_FEEDBACK_START = 1612
MOTION_STATE_START = 56
STATUS_LONG_START = 34
ALARM_DETAIL_START = 38
SYSTEM_STATE_START = 36

STATUS_ALARM_BIT = 24
STATUS_ESTOP_BIT = 25
STATUS_PAUSED_BIT = 26
STATUS_READY_BIT = 28
CANCEL_LATCH_BIT = 5


class ZMotionReadOnlyBackend:
    """Read-only ZMotion backend used before real motion writes are enabled."""

    def __init__(
        self,
        *,
        client_factory: Callable[[str], ZMotionReadableClient] | None = None,
        host: str,
        use_shared: bool = False,
    ) -> None:
        self._client_factory = client_factory
        self._host = host
        self._use_shared = use_shared
        self._client: ZMotionReadableClient | None = None

    @property
    def model(self) -> RobotModel:
        return DEFAULT_SIX_AXIS_MODEL

    @property
    def capabilities(self) -> ControllerCapabilities:
        return ControllerCapabilities(
            vendor="zmotion",
            supports_real_writes=False,
            motion_primitives=("state_read",),
        )

    def get_state(self) -> RobotState:
        try:
            client = self._get_client()
            joints = self._read_floats(client, JOINT_FEEDBACK_START, len(AXIS_NAMES))
            pose = self._read_floats(client, POSE_FEEDBACK_START, len(AXIS_NAMES))
            status_raw = self._read_longs(client, STATUS_LONG_START, 1)[0]
            alarm_detail = self._read_longs(client, ALARM_DETAIL_START, 1)[0]
            system_state = self._read_longs(client, SYSTEM_STATE_START, 1)[0]
            motion_state = self._read_floats(client, MOTION_STATE_START, 1)[0]
        except Exception as exc:
            self._reset_client()
            return RobotState(
                mode="disconnected",
                connected_real_device=False,
                alarms=[f"controller_read_failed: {type(exc).__name__}: {exc}"],
            )

        axes = {axis: float(pose[index]) for index, axis in enumerate(AXIS_NAMES)}
        return RobotState(
            mode=self._mode_from_status(status_raw=status_raw, alarm_detail=alarm_detail, motion_state=motion_state),
            axes_mm=axes,
            joints_deg=[float(value) for value in joints],
            alarms=self._alarms_from_status(status_raw=status_raw, alarm_detail=alarm_detail),
            connected_real_device=True,
            cancel_latch=bool((int(system_state) >> CANCEL_LATCH_BIT) & 1),
        )

    def move_axis(self, axis: str, delta: float) -> ToolResult:
        return self._readonly_rejection("move_axis", {"axis": axis, "delta": float(delta)})

    def home(self) -> ToolResult:
        return self._readonly_rejection("home")

    def stop(self) -> ToolResult:
        return self._readonly_rejection("stop")

    def execute_system_action(self, request: Any) -> dict[str, Any]:
        return self._readonly_rejection(
            "system_action",
            {"action": str(getattr(request, "parameters", {}).get("action", ""))},
        ).to_dict()

    def close(self) -> None:
        """Release a short-lived diagnostic connection when one was opened."""
        self._reset_client()

    def _get_client(self) -> ZMotionReadableClient:
        if self._use_shared:
            from robot_platform.backends import zmotion_shared_client as shared

            return shared.get()
        if self._client is not None and getattr(self._client, "connected", False):
            return self._client

        client = self._client_factory(self._host)
        client.connect()
        self._client = client
        return client

    def _reset_client(self) -> None:
        """Drop the cached client so the next read opens a fresh connection.

        Called when a read fails (dead ZAux handle, controller reboot, or the
        connection was kicked by another client). Without this, a stale
        ``connected=True`` flag makes _get_client reuse the dead handle forever.
        Best-effort disconnect first so the dead session doesn't linger on the
        controller.
        """
        if self._use_shared:
            from robot_platform.backends import zmotion_shared_client as shared

            shared.reset()
            return
        client = self._client
        self._client = None
        if client is None:
            return
        try:
            client.disconnect()
        except Exception:
            client.connected = False

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

    def execute_io(self, request: Any) -> dict[str, Any]:
        del request
        return self._readonly_rejection("io").to_dict()


class ZMotionSafetyActionBackend(ZMotionReadOnlyBackend):
    """ZMotion status backend with one guarded Func104 safety-action port.

    Point moves and raw SDK access remain unavailable to upper layers.  The
    product operation runner supplies the only controller-write path and still
    verifies the execution proof, parameter echoes and post-action state.
    """

    def __init__(
        self,
        *,
        system_action_runner: Callable[[Any], dict[str, Any]],
        io_runner: Callable[[Any], dict[str, Any]] | None = None,
        client_factory: Callable[[str], ZMotionReadableClient] | None = None,
        host: str,
        use_shared: bool = False,
    ) -> None:
        super().__init__(client_factory=client_factory, host=host, use_shared=use_shared)
        self._system_action_runner = system_action_runner
        self._io_runner = io_runner

    @property
    def capabilities(self) -> ControllerCapabilities:
        return ControllerCapabilities(
            vendor="zmotion",
            # Func104 changes controller state, so the public capability must
            # not falsely advertise this selected backend as read-only.
            supports_real_writes=True,
            motion_primitives=("state_read", "system_action"),
        )

    def execute_system_action(self, request: Any) -> dict[str, Any]:
        if getattr(request, "command", "") != "system":
            return ToolResult.failure(
                state="system_action_unsupported",
                message="ZMotion safety backend accepts only system actions.",
                errors=[{"code": "system_action_unsupported"}],
            ).to_dict()
        return self._system_action_runner(request)

    def execute_io(self, request: Any) -> dict[str, Any]:
        if getattr(request, "command", "") != "io" or self._io_runner is None:
            return ToolResult.failure(
                state="io_unsupported",
                message="ZMotion backend IO operation is unavailable.",
                errors=[{"code": "io_unsupported"}],
            ).to_dict()
        return self._io_runner(request)
