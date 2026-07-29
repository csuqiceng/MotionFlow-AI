"""Server-side Tool eligibility is independent of the Nanobot registry."""

from __future__ import annotations

import importlib.util

from ai_runtime.tool_manifest import ToolManifest
from robot_server.tool_registry import ToolRegistry

def test_product_tool_registry_module_exists() -> None:
    assert importlib.util.find_spec("robot_server.tool_registry") is not None


def test_tool_is_hidden_when_required_robot_capability_is_missing() -> None:
    registry = ToolRegistry()
    manifest = ToolManifest(
        tool_id="vision-grasp",
        version="1.0.0",
        required_capabilities=("cartesian_motion",),
        allowed_roles=("engineer",),
        risk_level="motion",
        idempotency="request",
    )
    registry.register(manifest)

    eligibility = registry.evaluate(
        manifest,
        capabilities={"supports_state_read": True, "motion_primitives": ["axis_move"]},
        role="engineer",
        enabled_tool_ids={"vision-grasp"},
    )

    assert eligibility.eligible is False
    assert eligibility.code == "capability_missing"
    assert registry.eligible_manifests(
        capabilities={"supports_state_read": True, "motion_primitives": ["axis_move"]},
        role="engineer",
        enabled_tool_ids={"vision-grasp"},
    ) == ()


def test_tool_requires_role_and_explicit_enablement_before_ai_exposure() -> None:
    registry = ToolRegistry()
    manifest = ToolManifest(
        tool_id="robot-axis-move",
        version="1.0.0",
        required_capabilities=("axis_move",),
        allowed_roles=("engineer",),
        risk_level="motion",
        idempotency="request",
    )
    registry.register(manifest)
    capabilities = {"motion_primitives": ["axis_move"]}

    assert registry.evaluate(
        manifest, capabilities=capabilities, role="operator", enabled_tool_ids={"robot-axis-move"}
    ).code == "role_forbidden"
    assert registry.evaluate(
        manifest, capabilities=capabilities, role="engineer", enabled_tool_ids=set()
    ).code == "tool_disabled"
    assert registry.eligible_manifests(
        capabilities=capabilities, role="engineer", enabled_tool_ids={"robot-axis-move"}
    ) == (manifest,)
