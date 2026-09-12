"""The public robot-capability payload is stable and vendor-neutral."""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path

from robot_platform.backends.simulation_backend import SimulationRobotBackend
from robot_platform.models import ControllerCapabilities
from robot_platform.tools.robot_tools import RobotToolFacade


FIXTURE_PATH = Path(__file__).parents[1] / "robot_server" / "fixtures" / "capabilities-v1.json"


def test_capabilities_have_a_versioned_vendor_neutral_public_shape() -> None:
    capabilities = ControllerCapabilities(
        vendor="simulation",
        supports_state_read=True,
        supports_real_writes=False,
        motion_primitives=("axis_move", "home", "stop"),
    )

    expected = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    assert capabilities.to_public_dict() == expected
    assert "vendor" not in capabilities.to_public_dict()
    assert set(capabilities.to_public_dict()) == {
        "protocol_version",
        *(field.name for field in fields(ControllerCapabilities) if field.name != "vendor"),
    }


def test_canonical_robot_facade_emits_new_and_legacy_capability_fields() -> None:
    result = RobotToolFacade(SimulationRobotBackend()).robot_get_status()
    expected = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    assert result["data"]["capabilities"] == expected
    assert "vendor" not in result["data"]["capabilities"]
    assert result["data"]["controller_capabilities"]["vendor"] == "simulation"
