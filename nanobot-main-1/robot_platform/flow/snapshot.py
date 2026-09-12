"""Immutable, fully expanded Flow execution snapshots."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

from robot_platform.flow.models import FlowEntry, FlowStep
from robot_platform.flow.schema import require_strict_io_parameters, validate_legacy_step_payload
from robot_platform.flow.nodes import (
    ActionNode,
    FlowNode,
    NodeContract,
    SequenceNode,
    iter_action_nodes,
    iter_nodes,
    ConditionNode,
    node_from_dict,
    node_to_dict,
)
from robot_platform.safety.config import (
    DEFAULT_WORKSPACE_R_MAX, DEFAULT_WORKSPACE_R_MIN,
    DEFAULT_WORKSPACE_Z_MAX, DEFAULT_WORKSPACE_Z_MIN,
)

_FUNC_TO_COMMAND = {108: "linear_move", 104: "system", 110: "delay", 120: "io"}


class FlowNodeType(str, Enum):
    LINEAR_MOVE = "linear_move"
    SYSTEM = "system"
    DELAY = "delay"
    IO = "io"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class FlowSnapshotStep:
    index: int
    step_id: int
    func_id: int
    command: str
    parameters_json: str
    description: str = ""

    @property
    def node_type(self) -> FlowNodeType:
        return FlowNodeType(self.command)

    @property
    def parameters(self) -> dict[str, Any]:
        return json.loads(self.parameters_json)

    def to_dict(self) -> dict[str, Any]:
        return {"index": self.index, "step_id": self.step_id, "func_id": self.func_id,
                "command": self.command, "parameters": self.parameters,
                "description": self.description}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FlowSnapshotStep":
        for name in ("index", "step_id", "func_id"):
            value = payload.get(name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"Flow snapshot {name} must be an integer")
        command = payload.get("command")
        parameters = payload.get("parameters")
        if command not in {item.value for item in FlowNodeType}:
            raise ValueError("Flow snapshot command is unsupported")
        if not isinstance(parameters, dict):
            raise ValueError("Flow snapshot parameters must be a mapping")
        # Re-run the action schema at the trust boundary; a valid hash must not
        # make malformed or coercive values executable.
        errors = validate_legacy_step_payload({
            "step_id": payload["step_id"],
            "func_id": payload["func_id"],
            "params": parameters,
            "spd_pct": parameters.get("speed_pct", 50),
        })
        if errors:
            raise ValueError("Invalid Flow snapshot step: " + " ".join(errors))
        if command == "io":
            require_strict_io_parameters(parameters)
        return cls(index=payload["index"], step_id=payload["step_id"],
                   func_id=payload["func_id"], command=command,
                   parameters_json=_canonical(parameters),
                   description=str(payload.get("description", "")))


@dataclass(frozen=True)
class FlowExecutionSnapshot:
    flow_id: str
    flow_name: str
    published_version: str
    content_hash: str
    steps: tuple[FlowSnapshotStep, ...]
    product_profile_version: str
    capability_version: str
    core_version: str
    node_graph_json: str = ""
    inputs_json: str = "{}"
    inputs_bound: bool = True
    resolved_alias: str = ""
    schema_version: str = "2"

    @property
    def root_node(self) -> FlowNode:
        if not self.node_graph_json:
            raise ValueError("Flow snapshot does not contain a v2 node graph")
        return node_from_dict(json.loads(self.node_graph_json))

    @property
    def inputs(self) -> dict[str, Any]:
        value = json.loads(self.inputs_json)
        if not isinstance(value, dict):
            raise ValueError("Flow snapshot inputs must be an object")
        return value

    @classmethod
    def create(cls, flow: FlowEntry, *, product_profile_version: str,
               capability_version: str, core_version: str,
               resolved_alias: str = "", root_node: FlowNode | None = None,
               execution_inputs: dict[str, Any] | None = None) -> "FlowExecutionSnapshot":
        steps = tuple(FlowSnapshotStep(
            index=index, step_id=int(step.step_id), func_id=int(step.func_id),
            command=_FUNC_TO_COMMAND.get(int(step.func_id), "unsupported"),
            parameters_json=_canonical(_expand_parameters(step)),
            description=str(step.description),
        ) for index, step in enumerate(flow.steps, start=1))
        if root_node is None and flow.node_graph is not None:
            root_node = node_from_dict(flow.node_graph)
        if root_node is None:
            root_node = SequenceNode(
                node_id="root",
                children=tuple(_action_node(step) for step in steps),
                contract=NodeContract(cancellable=True),
            )
        executable = {
            "schema_version": "2",
            "flow_id": str(flow.flow_id or flow.name), "flow_name": str(flow.name),
            "published_version": str(flow.version),
            "steps": [step.to_dict() for step in steps],
            "product_profile_version": str(product_profile_version),
            "capability_version": str(capability_version), "core_version": str(core_version),
            "resolved_alias": str(resolved_alias or ""),
            "node_graph": node_to_dict(root_node),
            "inputs": dict(execution_inputs or {}),
        }
        snapshot = cls(
            flow_id=executable["flow_id"], flow_name=executable["flow_name"],
            published_version=executable["published_version"],
            content_hash=hashlib.sha256(_canonical(executable).encode("utf-8")).hexdigest(),
            steps=steps, product_profile_version=executable["product_profile_version"],
            capability_version=executable["capability_version"],
            core_version=executable["core_version"],
            node_graph_json=_canonical(executable["node_graph"]),
            inputs_json=_canonical(executable["inputs"]),
            resolved_alias=str(resolved_alias or ""),
        )
        snapshot.validate()
        return snapshot

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "flow_id": self.flow_id,
            "flow_name": self.flow_name, "published_version": self.published_version,
            "content_hash": self.content_hash, "steps": [step.to_dict() for step in self.steps],
            "dependencies": {"product_profile_version": self.product_profile_version,
                             "capability_version": self.capability_version,
                             "core_version": self.core_version},
            "resolved_alias": self.resolved_alias,
            **({"inputs": self.inputs} if self.inputs_bound else {}),
            **(
                {"node_graph": json.loads(self.node_graph_json)}
                if self.node_graph_json else {}
            ),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FlowExecutionSnapshot":
        dependencies = dict(payload["dependencies"])
        snapshot = cls(
            schema_version=str(payload["schema_version"]), flow_id=str(payload["flow_id"]),
            flow_name=str(payload["flow_name"]), published_version=str(payload["published_version"]),
            content_hash=str(payload["content_hash"]),
            steps=tuple(FlowSnapshotStep.from_dict(dict(step)) for step in payload["steps"]),
            product_profile_version=str(dependencies["product_profile_version"]),
            capability_version=str(dependencies["capability_version"]),
            core_version=str(dependencies["core_version"]),
            node_graph_json=(
                _canonical(payload["node_graph"]) if "node_graph" in payload else ""
            ),
            inputs_json=_canonical(payload.get("inputs", {})),
            inputs_bound="inputs" in payload,
            resolved_alias=str(payload.get("resolved_alias", "")),
        )
        snapshot.validate()
        return snapshot

    def validate(self) -> None:
        rebuilt = {
            "schema_version": self.schema_version,
            "flow_id": self.flow_id, "flow_name": self.flow_name,
            "published_version": self.published_version,
            "steps": [step.to_dict() for step in self.steps],
            "product_profile_version": self.product_profile_version,
            "capability_version": self.capability_version, "core_version": self.core_version,
            "resolved_alias": self.resolved_alias,
        }
        if self.inputs_bound:
            rebuilt["inputs"] = self.inputs
        if self.node_graph_json:
            rebuilt["node_graph"] = json.loads(self.node_graph_json)
        expected = hashlib.sha256(_canonical(rebuilt).encode("utf-8")).hexdigest()
        if expected != self.content_hash:
            raise ValueError("Flow execution snapshot content hash mismatch")
        if not self.steps or any(step.index != index for index, step in enumerate(self.steps, 1)):
            raise ValueError("Flow execution snapshot steps must be non-empty and contiguous")
        if any(step.command == "unsupported" for step in self.steps):
            raise ValueError("Flow execution snapshot contains an unsupported step")
        if any(
            step.command == "system"
            and step.parameters.get("action") == "emergency_stop"
            for step in self.steps
        ):
            raise ValueError(
                "Flow execution snapshot cannot contain dedicated emergency stop"
            )
        if self.schema_version == "2":
            root = self.root_node
            node_ids = [node.node_id for node in iter_nodes(root)]
            if len(node_ids) != len(set(node_ids)):
                raise ValueError("Flow v2 node_id values must be globally unique")
            required_inputs = {
                node.input_name for node in iter_nodes(root)
                if isinstance(node, ConditionNode)
            }
            if not required_inputs.issubset(self.inputs):
                raise ValueError("Flow v2 snapshot is missing frozen condition inputs")
            actions = tuple(iter_action_nodes(root))
            by_index = {action.step_index: action for action in actions}
            if (
                len(actions) != len(self.steps)
                or len(by_index) != len(actions)
                or any(
                    (action := by_index.get(step.index)) is None
                    or action.step_id != step.step_id
                    or action.command != step.command
                    or dict(action.parameters) != step.parameters
                    for step in self.steps
                )
            ):
                raise ValueError("Flow v2 node graph does not match expanded steps")


def _expand_parameters(step: FlowStep) -> dict[str, Any]:
    params = dict(step.params or {})
    command = _FUNC_TO_COMMAND.get(int(step.func_id), "unsupported")
    errors = validate_legacy_step_payload(step.to_dict())
    if errors:
        raise ValueError("Invalid Flow step: " + " ".join(errors))
    if command == "linear_move":
        target = params.get("target_pose")
        if not isinstance(target, dict):
            target = {axis: float(params.get(f"target_{axis}", params.get(axis, 0.0)) or 0.0)
                      for axis in ("x", "y", "z", "rx", "ry", "rz")}
        speed = float(params.get("speed_pct", step.spd_pct))
        return {"target_pose": dict(target), "speed_pct": speed,
                "acceleration_pct": float(params.get("acceleration_pct", speed)),
                "deceleration_pct": float(params.get("deceleration_pct", speed)),
                "r_min": float(params.get("r_min", DEFAULT_WORKSPACE_R_MIN)),
                "r_max": float(params.get("r_max", DEFAULT_WORKSPACE_R_MAX)),
                "z_min": float(params.get("z_min", DEFAULT_WORKSPACE_Z_MIN)),
                "z_max": float(params.get("z_max", DEFAULT_WORKSPACE_Z_MAX))}
    if command == "system": return {"action": str(params.get("action", ""))}
    if command == "delay": return {"seconds": float(params.get("seconds", params.get("delay_sec", 0)) or 0)}
    if command == "io":
        return require_strict_io_parameters(params)
    return {"func_id": int(step.func_id)}


def _action_node(step: FlowSnapshotStep) -> ActionNode:
    side_effect = {
        "linear_move": "motion",
        "system": "system",
        "delay": "none",
        "io": "io",
    }[step.command]
    timeout = {"linear_move": 120.0, "system": 30.0, "delay": 300.0, "io": 30.0}[step.command]
    return ActionNode(
        node_id=f"step-{step.index}-{step.step_id}",
        command=step.command,
        parameters=step.parameters,
        step_index=step.index,
        step_id=step.step_id,
        contract=NodeContract(
            capabilities=(step.command,),
            timeout_seconds=timeout,
            cancellable=True,
            idempotency="intrinsic" if step.command == "delay" else "request",
            side_effect=side_effect,
            inputs=tuple(sorted(step.parameters)),
            outputs=("operation_result",),
        ),
    )
