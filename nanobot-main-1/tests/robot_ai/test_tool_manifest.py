"""Tool manifests define eligibility independently from an agent SDK."""

from __future__ import annotations

import importlib.util

import pytest

from ai_runtime.tool_manifest import ToolManifest


def test_tool_manifest_module_exists_for_product_tool_metadata() -> None:
    assert importlib.util.find_spec("ai_runtime.tool_manifest") is not None


def test_tool_manifest_rejects_empty_roles_and_unknown_risk_level() -> None:
    with pytest.raises(ValueError, match="at least one allowed role"):
        ToolManifest(tool_id="robot_status", version="1.0.0", allowed_roles=())
    with pytest.raises(ValueError, match="Unknown tool risk level"):
        ToolManifest(tool_id="robot_status", version="1.0.0", risk_level="unsafe")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"timeout_seconds": 0}, "timeout"),
        ({"concurrency": "unsafe"}, "concurrency"),
        ({"resources": ("controller", "controller")}, "resources"),
        ({"idempotency": "unsafe"}, "idempotency"),
        ({"audit_policy": "unsafe"}, "audit"),
    ],
)
def test_tool_manifest_rejects_invalid_runtime_policy(kwargs, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        ToolManifest("demo", "2", **kwargs)


def test_side_effecting_manifest_requires_request_idempotency() -> None:
    with pytest.raises(ValueError, match="request idempotency"):
        ToolManifest("motion", "2", risk_level="motion", idempotency="none")
