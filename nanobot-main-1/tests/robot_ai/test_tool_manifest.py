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
