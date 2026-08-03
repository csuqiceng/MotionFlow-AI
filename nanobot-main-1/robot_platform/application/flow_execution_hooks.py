"""In-process progress and cancellation hooks for trusted Flow callers.

These hooks are intentionally not part of the HTTP request schema. They allow
the library execution registry to reflect the same real Flow dispatch rather
than starting a second, unsynchronised timeline.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, Callable, Iterator


@dataclass(frozen=True)
class FlowExecutionHooks:
    before_step: Callable[[int], bool] | None = None
    on_step: Callable[[int, str, dict[str, Any] | None], None] | None = None


_hooks: ContextVar[FlowExecutionHooks | None] = ContextVar(
    "flow_execution_hooks", default=None,
)


def current_flow_execution_hooks() -> FlowExecutionHooks | None:
    return _hooks.get()


@contextmanager
def bind_flow_execution_hooks(
    *,
    before_step: Callable[[int], bool] | None = None,
    on_step: Callable[[int, str, dict[str, Any] | None], None] | None = None,
) -> Iterator[None]:
    token: Token[FlowExecutionHooks | None] = _hooks.set(FlowExecutionHooks(
        before_step=before_step, on_step=on_step,
    ))
    try:
        yield
    finally:
        _hooks.reset(token)
