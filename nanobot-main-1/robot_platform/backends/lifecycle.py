"""Vendor-neutral Backend port bundles and lifecycle supervision."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from threading import Event, RLock, Thread
from time import monotonic
from typing import Any, Protocol, TypeVar, runtime_checkable

from robot_platform.models import ControllerCapabilities, RobotModel, RobotState, ToolResult

from .plugin_contract import BackendManifest

_ResultT = TypeVar("_ResultT")


class BackendLifecycleState(str, Enum):
    CREATED = "created"
    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
    ERROR = "error"
    STOPPING = "stopping"
    STOPPED = "stopped"


@dataclass(frozen=True)
class BackendHealth:
    state: BackendLifecycleState
    message: str = ""


@dataclass(frozen=True)
class BackendCallContext:
    deadline_monotonic: float | None = None
    cancel_event: Event | None = None
    effect_operation_id: str = ""
    operation_fingerprint: str = ""
    target_device_id: str = ""

    def check(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise RuntimeError("Backend call was cancelled before dispatch")
        if self.deadline_monotonic is not None and monotonic() >= self.deadline_monotonic:
            raise TimeoutError("Backend call deadline expired before dispatch")

    @classmethod
    def from_current_operation(cls) -> "BackendCallContext | None":
        from robot_platform.operation_control import current_operation_control

        control = current_operation_control()
        if control is None:
            return None
        return cls(
            deadline_monotonic=control.deadline_monotonic,
            cancel_event=control.cancel_event,
            effect_operation_id=control.effect_operation_id,
            operation_fingerprint=control.operation_fingerprint,
            target_device_id=control.target_device_id,
        )


@runtime_checkable
class BackendLifecyclePort(Protocol):
    def start(self) -> None: ...
    def shutdown(self) -> None: ...


@runtime_checkable
class BackendDiagnosticsPort(Protocol):
    @property
    def model(self) -> RobotModel: ...
    @property
    def capabilities(self) -> ControllerCapabilities: ...
    def get_state(self) -> RobotState: ...


@runtime_checkable
class BackendMotionPort(Protocol):
    def move_axis(self, axis: str, delta: float) -> ToolResult: ...
    def home(self) -> ToolResult: ...
    def stop(self) -> ToolResult: ...


@runtime_checkable
class BackendSystemControlPort(Protocol):
    def execute_system_action(self, request: Any) -> dict[str, Any]: ...


@runtime_checkable
class BackendIOPort(Protocol):
    def execute_io(self, request: Any) -> dict[str, Any]: ...


@runtime_checkable
class BackendOperationPort(Protocol):
    """Optional structured-operation port for non-controller backends."""
    def execute_operation(self, request: Any) -> dict[str, Any]: ...


@dataclass(frozen=True)
class BackendPortBundle:
    lifecycle: BackendLifecyclePort
    diagnostics: BackendDiagnosticsPort
    motion: BackendMotionPort | None = None
    system_control: BackendSystemControlPort | None = None
    io: BackendIOPort | None = None
    operation: BackendOperationPort | None = None


class _LegacyLifecycle:
    def __init__(self, backend: Any) -> None:
        self._backend = backend

    def start(self) -> None:
        return None

    def shutdown(self) -> None:
        close = getattr(self._backend, "close", None)
        if callable(close):
            close()


def bundle_legacy_backend(backend: Any) -> BackendPortBundle:
    """Adapt one existing backend without leaking its concrete type upward."""
    if not isinstance(backend, BackendDiagnosticsPort):
        raise TypeError("Backend must implement diagnostics port")
    return BackendPortBundle(
        lifecycle=(
            backend if isinstance(backend, BackendLifecyclePort)
            else _LegacyLifecycle(backend)
        ),
        diagnostics=backend,
        motion=backend if isinstance(backend, BackendMotionPort) else None,
        system_control=(
            backend if isinstance(backend, BackendSystemControlPort) else None
        ),
        io=backend if isinstance(backend, BackendIOPort) else None,
        operation=backend if isinstance(backend, BackendOperationPort) else None,
    )


class BackendManager:
    """Own one Backend bundle and expose deterministic lifecycle transitions."""

    def __init__(
        self,
        manifest: BackendManifest,
        bundle: BackendPortBundle,
    ) -> None:
        self.manifest = manifest
        self._bundle = bundle
        self._lock = RLock()
        self._state = BackendLifecycleState.CREATED
        self._message = ""
        self._start_attempt: _StartAttempt | None = None
        self._validate_bundle()

    @property
    def lifecycle_state(self) -> BackendLifecycleState:
        with self._lock:
            return self._state

    @property
    def health(self) -> BackendHealth:
        with self._lock:
            return BackendHealth(self._state, self._message)

    @property
    def model(self) -> RobotModel:
        return self._bundle.diagnostics.model

    @property
    def capabilities(self) -> ControllerCapabilities:
        return self._bundle.diagnostics.capabilities

    def start(self, *, timeout: float = 5.0) -> BackendHealth:
        with self._lock:
            if self._state in {BackendLifecycleState.READY, BackendLifecycleState.DEGRADED}:
                return BackendHealth(self._state, self._message)
            if self._state is BackendLifecycleState.STOPPED:
                raise RuntimeError("Stopped Backend cannot be restarted")
            if self._state is BackendLifecycleState.STARTING:
                raise RuntimeError("Backend is already starting")
            self._state = BackendLifecycleState.STARTING
            self._message = ""
        try:
            attempt = _StartAttempt(
                self._bundle.lifecycle.start,
                self._bundle.lifecycle.shutdown,
            )
            with self._lock:
                self._start_attempt = attempt
            attempt.run(timeout)
            state = self._bundle.diagnostics.get_state()
            degraded = str(getattr(state, "mode", "")).casefold() == "disconnected"
            with self._lock:
                if self._state is not BackendLifecycleState.STARTING:
                    raise RuntimeError("Backend start was interrupted")
                self._state = (
                    BackendLifecycleState.DEGRADED
                    if degraded else BackendLifecycleState.READY
                )
                self._message = (
                    "Backend diagnostics are disconnected." if degraded else ""
                )
                return BackendHealth(self._state, self._message)
        except Exception:
            with self._lock:
                if self._state is not BackendLifecycleState.STOPPED:
                    self._state = BackendLifecycleState.ERROR
                    self._message = "Backend failed to start."
            raise
        finally:
            with self._lock:
                if self._start_attempt is attempt and attempt.finished:
                    self._start_attempt = None

    def refresh_health(self) -> BackendHealth:
        self.get_state()
        return self.health

    def get_state(self) -> RobotState:
        self._require_active(allow_degraded=True)
        try:
            state = self._bundle.diagnostics.get_state()
        except Exception:
            with self._lock:
                self._state = BackendLifecycleState.ERROR
                self._message = "Backend diagnostics failed."
            raise
        disconnected = str(getattr(state, "mode", "")).casefold() == "disconnected"
        with self._lock:
            self._state = (
                BackendLifecycleState.DEGRADED
                if disconnected else BackendLifecycleState.READY
            )
            self._message = (
                "Backend diagnostics are disconnected." if disconnected else ""
            )
        return state

    def move_axis(
        self, axis: str, delta: float, *, context: BackendCallContext | None = None,
    ) -> ToolResult:
        _check_call_context(context)
        port = self._required_port("motion", self._bundle.motion)
        result = self._invoke(lambda: port.move_axis(axis, delta), "Backend motion failed.")
        self._check_after_dispatch(context)
        return result

    def home(self, *, context: BackendCallContext | None = None) -> ToolResult:
        _check_call_context(context)
        port = self._required_port("motion", self._bundle.motion)
        result = self._invoke(port.home, "Backend motion failed.")
        self._check_after_dispatch(context)
        return result

    def stop(self, *, context: BackendCallContext | None = None) -> ToolResult:
        _check_call_context(context)
        port = self._required_port("motion", self._bundle.motion)
        result = self._invoke(port.stop, "Backend stop failed.")
        self._check_after_dispatch(context)
        return result

    def _check_after_dispatch(self, context: BackendCallContext | None) -> None:
        try:
            _check_call_context(context)
        except Exception:
            with self._lock:
                self._state = BackendLifecycleState.ERROR
                self._message = "Backend call outcome is unknown after its deadline."
            raise

    def execute_system_action(
        self, request: Any, *, context: BackendCallContext | None = None,
    ) -> dict[str, Any]:
        _check_call_context(context)
        port = self._required_port("system_control", self._bundle.system_control)
        result = self._invoke(
            lambda: port.execute_system_action(request),
            "Backend system control failed.",
        )
        self._check_after_dispatch(context)
        return result

    def execute_io(
        self, request: Any, *, context: BackendCallContext | None = None,
    ) -> dict[str, Any]:
        _check_call_context(context)
        port = self._required_port("io", self._bundle.io)
        result = self._invoke(
            lambda: port.execute_io(request),
            "Backend IO failed.",
        )
        self._check_after_dispatch(context)
        return result

    def execute_operation(
        self, request: Any, *, context: BackendCallContext | None = None,
    ) -> dict[str, Any]:
        _check_call_context(context)
        port = self._required_port("operation", self._bundle.operation)
        result = self._invoke(
            lambda: port.execute_operation(request), "Backend operation failed.",
        )
        self._check_after_dispatch(context)
        return result

    def close(self, *, timeout: float = 5.0) -> None:
        with self._lock:
            if self._state is BackendLifecycleState.STOPPED:
                return
            self._state = BackendLifecycleState.STOPPING
            self._message = ""
            attempt = self._start_attempt
        if attempt is not None:
            attempt.cancel()
            start_cleaned = attempt.wait_for_cleanup(min(float(timeout), 0.25))
        else:
            start_cleaned = False
        try:
            if not start_cleaned:
                _run_with_timeout(
                    self._bundle.lifecycle.shutdown, timeout, "Backend shutdown",
                )
        finally:
            with self._lock:
                self._state = BackendLifecycleState.STOPPED
                self._message = ""

    def _required_port(self, name: str, port: Any) -> Any:
        self._require_active()
        if port is None:
            raise RuntimeError(f"Backend does not provide required {name} port")
        return port

    def _invoke(self, operation: Callable[[], _ResultT], message: str) -> _ResultT:
        try:
            return operation()
        except Exception:
            with self._lock:
                self._state = BackendLifecycleState.ERROR
                self._message = message
            raise

    def _require_active(self, *, allow_degraded: bool = False) -> None:
        allowed = {BackendLifecycleState.READY}
        if allow_degraded:
            allowed.add(BackendLifecycleState.DEGRADED)
        with self._lock:
            if self._state not in allowed:
                raise RuntimeError(f"Backend is not ready: {self._state.value}")

    def _validate_bundle(self) -> None:
        required = set(self.manifest.required_ports)
        available = {
            "diagnostics": self._bundle.diagnostics,
            "motion": self._bundle.motion,
            "system_control": self._bundle.system_control,
            "io": self._bundle.io,
            "operation": self._bundle.operation,
            "lifecycle": self._bundle.lifecycle,
        }
        missing = sorted(name for name in required if available.get(name) is None)
        if missing:
            raise ValueError(
                f"Backend bundle is missing declared ports: {', '.join(missing)}",
            )


def _run_with_timeout(
    callback: Callable[[], None], timeout: float, operation: str,
) -> None:
    seconds = float(timeout)
    if not 0 < seconds <= 300:
        raise ValueError("Backend lifecycle timeout must be within 0-300 seconds")
    completed = Event()
    failure: list[BaseException] = []

    def run() -> None:
        try:
            callback()
        except BaseException as exc:
            failure.append(exc)
        finally:
            completed.set()

    Thread(target=run, daemon=True, name=f"motionflow-{operation}").start()
    if not completed.wait(seconds):
        raise TimeoutError(f"{operation} timed out")
    if failure:
        raise RuntimeError(f"{operation} failed") from failure[0]


class _StartAttempt:
    """Own a start generation and tear down any completion after cancellation."""

    def __init__(self, start: Callable[[], None], shutdown: Callable[[], None]) -> None:
        self._start = start
        self._shutdown = shutdown
        self._completed = Event()
        self._guard = RLock()
        self._cancelled = False
        self._failure: BaseException | None = None
        self._cleanup_completed = Event()

    def run(self, timeout: float) -> None:
        seconds = float(timeout)
        if not 0 < seconds <= 300:
            raise ValueError("Backend lifecycle timeout must be within 0-300 seconds")

        def worker() -> None:
            failure: BaseException | None = None
            try:
                self._start()
            except BaseException as exc:
                failure = exc
            with self._guard:
                cancelled = self._cancelled
                self._failure = failure
                self._completed.set()
            if cancelled:
                try:
                    self._shutdown()
                except BaseException:
                    pass
                finally:
                    self._cleanup_completed.set()

        Thread(
            target=worker, daemon=True, name="motionflow-Backend start",
        ).start()
        if not self._completed.wait(seconds):
            with self._guard:
                if not self._completed.is_set():
                    self._cancelled = True
                    raise TimeoutError("Backend start timed out")
        if self._failure is not None:
            raise RuntimeError("Backend start failed") from self._failure

    def cancel(self) -> None:
        with self._guard:
            self._cancelled = True

    @property
    def finished(self) -> bool:
        return self._completed.is_set()

    def wait_for_cleanup(self, timeout: float) -> bool:
        return self._cleanup_completed.wait(max(0.0, timeout))


def _check_call_context(context: BackendCallContext | None) -> None:
    if context is not None:
        context.check()
