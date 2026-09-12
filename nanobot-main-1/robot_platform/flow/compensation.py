"""Explicit planning for the narrow subset of safely compensatable Flow effects."""

from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from types import MappingProxyType
from typing import Any, Mapping

from robot_platform.flow.snapshot import FlowExecutionSnapshot


@dataclass(frozen=True)
class FlowCompensationAction:
    step_index: int
    command: str
    parameters: Mapping[str, Any]
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "parameters", MappingProxyType(deepcopy(dict(self.parameters))),
        )


@dataclass(frozen=True)
class FlowCompensationPlan:
    snapshot_hash: str
    requested_by: str
    actions: tuple[FlowCompensationAction, ...]


def plan_controlled_compensation(
    snapshot: FlowExecutionSnapshot,
    completed_results: list[dict[str, Any]],
    *,
    requested_by: str,
    authorized: bool,
) -> FlowCompensationPlan:
    """Plan only explicit IO reversals; motion/system actions never auto-rollback."""
    if not authorized or not str(requested_by).strip():
        raise PermissionError("Compensation requires explicit trusted authorization")
    actions: list[FlowCompensationAction] = []
    for item in reversed(completed_results):
        if not isinstance(item, dict):
            continue
        index = item.get("step_index")
        if not isinstance(index, int) or not 1 <= index <= len(snapshot.steps):
            continue
        step = snapshot.steps[index - 1]
        result = item.get("result")
        data = result.get("data") if isinstance(result, dict) else None
        compensation = data.get("compensation") if isinstance(data, dict) else None
        if step.command != "io" or not isinstance(compensation, dict):
            continue
        io_number = compensation.get("io_number")
        previous_enabled = compensation.get("previous_enabled")
        if isinstance(io_number, bool) or not isinstance(io_number, int):
            continue
        if not isinstance(previous_enabled, bool):
            continue
        actions.append(FlowCompensationAction(
            step_index=index,
            command="io",
            parameters={"io_number": io_number, "enabled": previous_enabled},
            reason="restore_explicitly_observed_io_state",
        ))
    return FlowCompensationPlan(
        snapshot_hash=snapshot.content_hash,
        requested_by=str(requested_by),
        actions=tuple(actions),
    )
