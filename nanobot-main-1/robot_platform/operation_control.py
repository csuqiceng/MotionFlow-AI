"""Cooperative deadline/cancellation propagated into synchronous robot work."""

from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from threading import Event
from typing import Iterator


class OperationCancelledError(RuntimeError):
    """Cooperative operation cancellation distinct from execution failure."""


@dataclass(frozen=True)
class OperationControl:
    deadline_monotonic: float | None = None
    cancel_event: Event | None = None
    effect_operation_id: str = ""
    operation_fingerprint: str = ""
    target_device_id: str = ""

    def check(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise OperationCancelledError("Robot operation was cancelled")
        if self.deadline_monotonic is not None and time.monotonic() >= self.deadline_monotonic:
            raise TimeoutError("Robot operation deadline expired")


_current: ContextVar[OperationControl | None] = ContextVar(
    "robot_operation_control", default=None,
)


def current_operation_control() -> OperationControl | None:
    return _current.get()


@contextmanager
def bind_operation_control(control: OperationControl) -> Iterator[None]:
    token: Token[OperationControl | None] = _current.set(control)
    try:
        yield
    finally:
        _current.reset(token)
