"""Versioned golden fixtures for cross-component public contracts."""

from __future__ import annotations

import json
from pathlib import Path

from ai_runtime.contracts import RuntimeEvent
from ai_runtime.tool_manifest import ToolManifest
from robot_platform.backends.registry import BackendRegistry
from robot_platform.backends.simulation_plugin import SimulationBackendPlugin
from robot_platform.flow.events import FlowExecutionEvent


FIXTURES = Path(__file__).parents[1] / "robot_server" / "fixtures"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_backend_manifest_v1_fixture() -> None:
    registry = BackendRegistry()
    registry.register_plugin(SimulationBackendPlugin())
    assert registry.plugin_manifests[0].to_public_dict(protocol_version=1) == _fixture(
        "backend-manifest-v1.json"
    )


def test_backend_manifest_v2_fixture() -> None:
    registry = BackendRegistry()
    registry.register_plugin(SimulationBackendPlugin())
    assert registry.plugin_manifests[0].to_public_dict(protocol_version=2) == _fixture(
        "backend-manifest-v2.json"
    )


def test_tool_manifest_v1_fixture() -> None:
    manifest = ToolManifest(
        tool_id="robot_move", version="1.0.0",
        required_capabilities=("linear_move", "real_writes"),
        allowed_roles=("operator", "engineer"), risk_level="motion",
        idempotency="request",
    )
    assert manifest.to_public_dict(protocol_version=1) == _fixture(
        "tool-manifest-v1.json"
    )


def test_tool_manifest_v2_fixture() -> None:
    manifest = ToolManifest(
        tool_id="robot_move", version="2.0.0",
        required_capabilities=("linear_move", "real_writes"),
        allowed_roles=("operator", "engineer"), risk_level="motion",
        timeout_seconds=45, concurrency="exclusive",
        resources=("robot-controller",), idempotency="request",
        audit_policy="required",
    )
    assert manifest.to_public_dict() == _fixture("tool-manifest-v2.json")


def test_agent_event_v1_fixture() -> None:
    event = RuntimeEvent(
        conversation_id="conversation-1", kind="tool_progress",
        payload={"content": "checking robot", "tool_hint": True},
        request_id="request-1",
    )
    assert event.to_contract_dict() == _fixture("agent-event-v1.json")


def test_flow_event_v1_fixture() -> None:
    event = FlowExecutionEvent(
        execution_id="execution-1",
        snapshot_hash="abc123",
        kind="node_succeeded",
        step_index=2,
        state="succeeded",
        payload={"duration_ms": 12},
        event_id="event-1",
        timestamp=123.5,
    )
    assert event.to_contract_dict() == _fixture("flow-event-v1.json")
