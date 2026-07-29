"""Versioned discriminated Flow node schema and vendor-neutral executor."""

from __future__ import annotations

import asyncio
import inspect
import operator
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Mapping

from robot_platform.operation_control import (
    OperationCancelledError, OperationControl, bind_operation_control,
    current_operation_control,
)


class FlowNodeKind(str, Enum):
    ACTION = "action"
    CONDITION = "condition"
    SEQUENCE = "sequence"
    PARALLEL = "parallel"
    RETRY = "retry"
    TIMEOUT = "timeout"
    COMPENSATION = "compensation"
    HUMAN_APPROVAL = "human_approval"


@dataclass(frozen=True)
class NodeContract:
    capabilities: tuple[str, ...] = ()
    timeout_seconds: float | None = None
    cancellable: bool = True
    idempotency: str = "none"
    side_effect: str = "none"
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.timeout_seconds is not None and not 0 < self.timeout_seconds <= 300:
            raise ValueError("Node timeout must be within 0-300 seconds")
        if self.idempotency not in {"none", "request", "intrinsic"}:
            raise ValueError("Node idempotency declaration is invalid")
        if self.side_effect not in {"none", "read", "io", "motion", "system"}:
            raise ValueError("Node side-effect declaration is invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "capabilities": list(self.capabilities),
            "timeout_seconds": self.timeout_seconds,
            "cancellable": self.cancellable,
            "idempotency": self.idempotency,
            "side_effect": self.side_effect,
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "NodeContract":
        raw = dict(value or {})
        timeout = raw.get("timeout_seconds")
        if timeout is not None and (
            isinstance(timeout, bool) or not isinstance(timeout, (int, float))
        ):
            raise ValueError("Node timeout_seconds must be numeric")
        cancellable = raw.get("cancellable", True)
        if not isinstance(cancellable, bool):
            raise ValueError("Node cancellable must be boolean")
        return cls(
            capabilities=_strings(raw.get("capabilities", ()), "capabilities"),
            timeout_seconds=None if timeout is None else float(timeout),
            cancellable=cancellable,
            idempotency=str(raw.get("idempotency", "none")),
            side_effect=str(raw.get("side_effect", "none")),
            inputs=_strings(raw.get("inputs", ()), "inputs"),
            outputs=_strings(raw.get("outputs", ()), "outputs"),
        )


@dataclass(frozen=True)
class FlowNode:
    node_id: str
    contract: NodeContract = field(default_factory=NodeContract)
    kind: FlowNodeKind = field(init=False)

    def __post_init__(self) -> None:
        if not str(self.node_id).strip():
            raise ValueError("Flow node_id is required")


@dataclass(frozen=True)
class ActionNode(FlowNode):
    command: str = ""
    parameters: Mapping[str, Any] = field(default_factory=dict)
    step_index: int | None = None
    step_id: int | None = None
    kind: FlowNodeKind = field(default=FlowNodeKind.ACTION, init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.command not in {"linear_move", "system", "delay", "io"}:
            raise ValueError("ActionNode command is unsupported")
        if not isinstance(self.parameters, Mapping):
            raise ValueError("ActionNode parameters must be a mapping")
        if self.step_index is not None and (
            isinstance(self.step_index, bool) or self.step_index < 1
        ):
            raise ValueError("ActionNode step_index must be a positive integer")
        from robot_platform.flow.schema import validate_legacy_step_payload

        func_id = {"linear_move": 108, "system": 104, "delay": 110, "io": 120}[self.command]
        errors = validate_legacy_step_payload({
            "step_id": 1,
            "func_id": func_id,
            "params": dict(self.parameters),
            "spd_pct": self.parameters.get("speed_pct", 50),
        })
        if errors:
            raise ValueError("Invalid ActionNode parameters: " + " ".join(errors))


@dataclass(frozen=True)
class ConditionNode(FlowNode):
    input_name: str = ""
    comparison: str = "eq"
    expected: Any = None
    if_true: FlowNode | None = None
    if_false: FlowNode | None = None
    kind: FlowNodeKind = field(default=FlowNodeKind.CONDITION, init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.input_name or self.comparison not in {"eq", "ne", "lt", "le", "gt", "ge"}:
            raise ValueError("ConditionNode declaration is invalid")
        if not isinstance(self.if_true, FlowNode) or (
            self.if_false is not None and not isinstance(self.if_false, FlowNode)
        ):
            raise ValueError("ConditionNode requires if_true")


@dataclass(frozen=True)
class SequenceNode(FlowNode):
    children: tuple[FlowNode, ...] = ()
    kind: FlowNodeKind = field(default=FlowNodeKind.SEQUENCE, init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.children or any(not isinstance(child, FlowNode) for child in self.children):
            raise ValueError("SequenceNode requires children")


@dataclass(frozen=True)
class ParallelNode(FlowNode):
    children: tuple[FlowNode, ...] = ()
    kind: FlowNodeKind = field(default=FlowNodeKind.PARALLEL, init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.children or any(not isinstance(child, FlowNode) for child in self.children):
            raise ValueError("ParallelNode requires children")
        if any(_has_physical_effect(child) for child in self.children):
            raise ValueError("ParallelNode cannot contain hardware side effects")


@dataclass(frozen=True)
class RetryNode(FlowNode):
    child: FlowNode | None = None
    max_attempts: int = 1
    kind: FlowNodeKind = field(default=FlowNodeKind.RETRY, init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        if (
            not isinstance(self.child, FlowNode)
            or isinstance(self.max_attempts, bool)
            or not isinstance(self.max_attempts, int)
            or not 1 <= self.max_attempts <= 10
        ):
            raise ValueError("RetryNode requires child and 1-10 attempts")
        if self.child.contract.idempotency == "none":
            raise ValueError("RetryNode child must declare idempotency")
        if _has_physical_effect(self.child):
            raise ValueError("RetryNode cannot retry hardware side effects")


@dataclass(frozen=True)
class TimeoutNode(FlowNode):
    child: FlowNode | None = None
    kind: FlowNodeKind = field(default=FlowNodeKind.TIMEOUT, init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.child, FlowNode) or self.contract.timeout_seconds is None:
            raise ValueError("TimeoutNode requires child and timeout_seconds")


@dataclass(frozen=True)
class CompensationNode(FlowNode):
    child: FlowNode | None = None
    compensation: ActionNode | None = None
    automatic: bool = False
    kind: FlowNodeKind = field(default=FlowNodeKind.COMPENSATION, init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.child, FlowNode) or not isinstance(self.compensation, ActionNode):
            raise ValueError("CompensationNode requires child and compensation")
        if not isinstance(self.automatic, bool):
            raise ValueError("CompensationNode automatic must be boolean")
        if self.automatic and (
            self.compensation.command != "io"
            or self.compensation.contract.side_effect != "io"
        ):
            raise ValueError("Only reviewed IO compensation may run automatically")


@dataclass(frozen=True)
class HumanApprovalNode(FlowNode):
    prompt: str = ""
    approval_key: str = ""
    child: FlowNode | None = None
    kind: FlowNodeKind = field(default=FlowNodeKind.HUMAN_APPROVAL, init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        if (
            not isinstance(self.prompt, str)
            or not isinstance(self.approval_key, str)
            or not self.prompt.strip()
            or not self.approval_key.strip()
            or not isinstance(self.child, FlowNode)
        ):
            raise ValueError("HumanApprovalNode requires prompt, approval_key and child")


ActionRunner = Callable[[ActionNode], Any | Awaitable[Any]]
ApprovalChecker = Callable[[HumanApprovalNode], bool | Awaitable[bool]]
TransitionSink = Callable[[str, str], None]


@dataclass
class FlowNodeExecutionContext:
    action_runner: ActionRunner
    inputs: dict[str, Any] = field(default_factory=dict)
    approval_checker: ApprovalChecker | None = None
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)
    idempotency_results: dict[str, Any] = field(default_factory=dict)
    on_transition: TransitionSink | None = None


class FlowOutcomeUnknown(RuntimeError):
    """A physical action may have happened and must not be retried."""


class FlowStopped(OperationCancelledError):
    """Execution was stopped before a step and must never be compensated."""

    def __init__(self, index: int) -> None:
        super().__init__(f"Flow stopped before step {index}")
        self.index = index


async def execute_node(node: FlowNode, context: FlowNodeExecutionContext) -> Any:
    if context.cancelled.is_set() and node.contract.cancellable:
        raise asyncio.CancelledError
    _transition(context, node, "running")
    try:
        operation = _execute_node_inner(node, context)
        if node.contract.timeout_seconds is not None and not isinstance(node, TimeoutNode):
            result = await asyncio.wait_for(operation, node.contract.timeout_seconds)
        else:
            result = await operation
    except BaseException:
        _transition(context, node, "failed")
        raise
    _transition(context, node, "succeeded")
    return result


async def _execute_node_inner(node: FlowNode, context: FlowNodeExecutionContext) -> Any:
    if isinstance(node, ActionNode):
        if node.contract.idempotency != "none" and node.node_id in context.idempotency_results:
            return context.idempotency_results[node.node_id]
        result = context.action_runner(node)
        if inspect.isawaitable(result):
            result = await result
        if _is_unknown_outcome(result):
            raise FlowOutcomeUnknown("Flow action outcome is unknown")
        if node.contract.idempotency != "none":
            context.idempotency_results[node.node_id] = result
        return result
    if isinstance(node, SequenceNode):
        result = None
        for child in node.children:
            result = await execute_node(child, context)
        return result
    if isinstance(node, ParallelNode):
        return await asyncio.gather(*(execute_node(child, context) for child in node.children))
    if isinstance(node, ConditionNode):
        actual = context.inputs.get(node.input_name)
        matched = _COMPARISONS[node.comparison](actual, node.expected)
        branch = node.if_true if matched else node.if_false
        return None if branch is None else await execute_node(branch, context)
    if isinstance(node, RetryNode):
        assert node.child is not None
        for attempt in range(1, node.max_attempts + 1):
            try:
                result = await execute_node(node.child, context)
                if _is_unknown_outcome(result):
                    raise FlowOutcomeUnknown("Flow action outcome is unknown")
                return result
            except asyncio.CancelledError:
                raise
            except Exception:
                if attempt == node.max_attempts:
                    raise
        raise AssertionError("unreachable")
    if isinstance(node, TimeoutNode):
        assert node.child is not None and node.contract.timeout_seconds is not None
        return await asyncio.wait_for(
            execute_node(node.child, context), node.contract.timeout_seconds,
        )
    if isinstance(node, CompensationNode):
        assert node.child is not None and node.compensation is not None
        try:
            return await execute_node(node.child, context)
        except asyncio.CancelledError:
            raise
        except (
            FlowOutcomeUnknown, OperationCancelledError, TimeoutError,
            PermissionError,
        ):
            raise
        except Exception:
            if node.automatic:
                await execute_node(node.compensation, context)
            raise
    if isinstance(node, HumanApprovalNode):
        assert node.child is not None
        if context.approval_checker is None:
            raise PermissionError("Human approval is unavailable")
        approved = context.approval_checker(node)
        if inspect.isawaitable(approved):
            approved = await approved
        if not approved:
            raise PermissionError("Human approval was denied")
        return await execute_node(node.child, context)
    raise TypeError(f"Unsupported Flow node: {type(node).__name__}")


def node_to_dict(node: FlowNode) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": 2,
        "node_type": node.kind.value,
        "node_id": node.node_id,
        "contract": node.contract.to_dict(),
    }
    if isinstance(node, ActionNode):
        result.update(command=node.command, parameters=dict(node.parameters))
        if node.step_index is not None:
            result["step_index"] = node.step_index
        if node.step_id is not None:
            result["step_id"] = node.step_id
    elif isinstance(node, (SequenceNode, ParallelNode)):
        result["children"] = [node_to_dict(child) for child in node.children]
    elif isinstance(node, ConditionNode):
        result.update(
            input_name=node.input_name, comparison=node.comparison, expected=node.expected,
            if_true=node_to_dict(node.if_true) if node.if_true else None,
            if_false=node_to_dict(node.if_false) if node.if_false else None,
        )
    elif isinstance(node, RetryNode):
        result.update(child=node_to_dict(node.child), max_attempts=node.max_attempts)
    elif isinstance(node, TimeoutNode):
        result["child"] = node_to_dict(node.child)
    elif isinstance(node, CompensationNode):
        result.update(
            child=node_to_dict(node.child),
            compensation=node_to_dict(node.compensation),
            automatic=node.automatic,
        )
    elif isinstance(node, HumanApprovalNode):
        result.update(
            prompt=node.prompt, approval_key=node.approval_key,
            child=node_to_dict(node.child),
        )
    return result


def node_from_dict(value: Mapping[str, Any]) -> FlowNode:
    raw = dict(value)
    if raw.get("schema_version") != 2:
        raise ValueError("Flow node schema_version must be 2")
    kind = FlowNodeKind(str(raw.get("node_type", "")))
    common = {
        "node_id": str(raw.get("node_id", "")),
        "contract": NodeContract.from_dict(raw.get("contract")),
    }
    if kind is FlowNodeKind.ACTION:
        return ActionNode(**common, command=str(raw.get("command", "")),
                          parameters=dict(raw.get("parameters", {})),
                          step_index=raw.get("step_index"), step_id=raw.get("step_id"))
    if kind in {FlowNodeKind.SEQUENCE, FlowNodeKind.PARALLEL}:
        children = raw.get("children")
        if not isinstance(children, list):
            raise ValueError("Composite Flow node children must be a list")
        cls = SequenceNode if kind is FlowNodeKind.SEQUENCE else ParallelNode
        return cls(**common, children=tuple(node_from_dict(item) for item in children))
    if kind is FlowNodeKind.CONDITION:
        return ConditionNode(
            **common, input_name=str(raw.get("input_name", "")),
            comparison=str(raw.get("comparison", "")), expected=raw.get("expected"),
            if_true=node_from_dict(raw["if_true"]),
            if_false=node_from_dict(raw["if_false"]) if raw.get("if_false") else None,
        )
    if kind is FlowNodeKind.RETRY:
        return RetryNode(**common, child=node_from_dict(raw["child"]),
                         max_attempts=raw.get("max_attempts", 1))
    if kind is FlowNodeKind.TIMEOUT:
        return TimeoutNode(**common, child=node_from_dict(raw["child"]))
    if kind is FlowNodeKind.COMPENSATION:
        compensation = node_from_dict(raw["compensation"])
        if not isinstance(compensation, ActionNode):
            raise ValueError("Compensation must be an ActionNode")
        return CompensationNode(
            **common, child=node_from_dict(raw["child"]), compensation=compensation,
            automatic=raw.get("automatic", False),
        )
    if kind is FlowNodeKind.HUMAN_APPROVAL:
        return HumanApprovalNode(
            **common, prompt=str(raw.get("prompt", "")),
            approval_key=str(raw.get("approval_key", "")),
            child=node_from_dict(raw["child"]),
        )
    raise AssertionError("unreachable")


def _strings(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        if value in ((), []):
            return ()
        raise ValueError(f"Node {name} must contain non-empty strings")
    return tuple(value)


def _transition(context: FlowNodeExecutionContext, node: FlowNode, state: str) -> None:
    if context.on_transition is not None:
        context.on_transition(node.node_id, state)


def execute_node_sync(node: FlowNode, context: FlowNodeExecutionContext) -> Any:
    """Execute a v2 graph on the synchronous production operation boundary.

    Hardware calls stay in the current supervised worker so cancellation and
    deadlines reach the backend through ``OperationControl``. Parallel nodes
    are deliberately limited to effect-free/read children by schema and are
    serialized here to avoid sharing mutable execution context.
    """
    _transition(context, node, "running")
    try:
        result = _execute_node_sync_inner(node, context)
    except BaseException:
        _transition(context, node, "failed")
        raise
    _transition(context, node, "succeeded")
    return result


def _execute_node_sync_inner(node: FlowNode, context: FlowNodeExecutionContext) -> Any:
    if isinstance(node, ActionNode):
        if node.contract.idempotency != "none" and node.node_id in context.idempotency_results:
            return context.idempotency_results[node.node_id]
        deadline = (
            time.monotonic() + node.contract.timeout_seconds
            if node.contract.timeout_seconds is not None else None
        )
        control = _nested_control(deadline)
        with bind_operation_control(control):
            result = context.action_runner(node)
            if inspect.isawaitable(result):
                raise TypeError("Production Flow action_runner must be synchronous")
            control.check()
        if _is_unknown_outcome(result):
            raise FlowOutcomeUnknown("Flow action outcome is unknown")
        if node.contract.idempotency != "none":
            context.idempotency_results[node.node_id] = result
        return result
    if isinstance(node, (SequenceNode, ParallelNode)):
        values = [execute_node_sync(child, context) for child in node.children]
        return values if isinstance(node, ParallelNode) else values[-1]
    if isinstance(node, ConditionNode):
        branch = node.if_true if _COMPARISONS[node.comparison](
            context.inputs.get(node.input_name), node.expected,
        ) else node.if_false
        return None if branch is None else execute_node_sync(branch, context)
    if isinstance(node, RetryNode):
        assert node.child is not None
        for attempt in range(1, node.max_attempts + 1):
            try:
                result = execute_node_sync(node.child, context)
                if _is_unknown_outcome(result):
                    raise FlowOutcomeUnknown("Flow action outcome is unknown")
                return result
            except FlowOutcomeUnknown:
                raise
            except Exception:
                if attempt == node.max_attempts:
                    raise
        raise AssertionError("unreachable")
    if isinstance(node, TimeoutNode):
        assert node.child is not None and node.contract.timeout_seconds is not None
        control = _nested_control(time.monotonic() + node.contract.timeout_seconds)
        with bind_operation_control(control):
            result = execute_node_sync(node.child, context)
            control.check()
            return result
    if isinstance(node, CompensationNode):
        assert node.child is not None and node.compensation is not None
        try:
            return execute_node_sync(node.child, context)
        except (
            FlowOutcomeUnknown, OperationCancelledError, TimeoutError,
            PermissionError,
        ):
            raise
        except Exception:
            if node.automatic:
                execute_node_sync(node.compensation, context)
            raise
    if isinstance(node, HumanApprovalNode):
        assert node.child is not None
        if context.approval_checker is None or not context.approval_checker(node):
            raise PermissionError("Human approval was denied or unavailable")
        return execute_node_sync(node.child, context)
    raise TypeError(f"Unsupported Flow node: {type(node).__name__}")


def iter_action_nodes(node: FlowNode):
    if isinstance(node, ActionNode):
        yield node
    elif isinstance(node, (SequenceNode, ParallelNode)):
        for child in node.children:
            yield from iter_action_nodes(child)
    elif isinstance(node, ConditionNode):
        if node.if_true is not None:
            yield from iter_action_nodes(node.if_true)
        if node.if_false is not None:
            yield from iter_action_nodes(node.if_false)
    elif isinstance(node, (RetryNode, TimeoutNode, HumanApprovalNode)):
        if node.child is not None:
            yield from iter_action_nodes(node.child)
    elif isinstance(node, CompensationNode):
        if node.child is not None:
            yield from iter_action_nodes(node.child)
        if node.compensation is not None:
            yield node.compensation


def iter_nodes(node: FlowNode):
    yield node
    if isinstance(node, (SequenceNode, ParallelNode)):
        for child in node.children:
            yield from iter_nodes(child)
    elif isinstance(node, ConditionNode):
        if node.if_true is not None:
            yield from iter_nodes(node.if_true)
        if node.if_false is not None:
            yield from iter_nodes(node.if_false)
    elif isinstance(node, (RetryNode, TimeoutNode, HumanApprovalNode)):
        if node.child is not None:
            yield from iter_nodes(node.child)
    elif isinstance(node, CompensationNode):
        if node.child is not None:
            yield from iter_nodes(node.child)
        if node.compensation is not None:
            yield from iter_nodes(node.compensation)


def _has_physical_effect(node: FlowNode) -> bool:
    return any(
        action.contract.side_effect in {"io", "motion", "system"}
        for action in iter_action_nodes(node)
    )


def _is_unknown_outcome(result: Any) -> bool:
    return isinstance(result, Mapping) and str(result.get("state", "")) in {
        "tool_outcome_unknown", "operation_outcome_unknown", "real_motion_completion_timeout",
    }


def _nested_control(deadline: float | None) -> OperationControl:
    parent = current_operation_control()
    if parent is not None and parent.deadline_monotonic is not None:
        deadline = parent.deadline_monotonic if deadline is None else min(
            deadline, parent.deadline_monotonic,
        )
    return OperationControl(
        deadline_monotonic=deadline,
        cancel_event=parent.cancel_event if parent is not None else None,
    )


_COMPARISONS = {
    "eq": operator.eq, "ne": operator.ne, "lt": operator.lt,
    "le": operator.le, "gt": operator.gt, "ge": operator.ge,
}
