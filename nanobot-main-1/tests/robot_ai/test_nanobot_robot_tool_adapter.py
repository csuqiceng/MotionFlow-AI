import asyncio
import json
from unittest.mock import MagicMock

import pytest


def _load_robot_tool():
    pytest.importorskip("loguru")
    pytest.importorskip("pydantic")
    from nanobot.agent.tools.robot_arm import RobotArmTool

    return RobotArmTool


def _run_tool(tool, **kwargs) -> dict:
    raw = asyncio.run(tool.execute(**kwargs))
    return json.loads(str(raw))


def test_robot_arm_tool_is_loaded_by_the_explicit_robot_product_loader(tmp_path) -> None:
    pytest.importorskip("loguru")
    pytest.importorskip("pydantic")
    from types import SimpleNamespace

    from ai_runtime.tool_loader import RobotToolLoader
    from nanobot.agent.tools.context import ToolContext
    from nanobot.agent.tools.registry import ToolRegistry

    RobotArmTool = _load_robot_tool()
    registry = ToolRegistry()
    context = ToolContext(
        config=SimpleNamespace(enabled_tools=["robot_arm"]),
        workspace=str(tmp_path),
    )
    RobotToolLoader().load(context, registry)

    from ai_runtime.robot_tools.loader import NanobotToolRuntimeAdapter

    registered = registry.get("robot_arm")
    assert isinstance(registered, NanobotToolRuntimeAdapter)
    assert isinstance(registered._legacy_tool, RobotArmTool)


def test_product_loader_injects_one_shared_platform_into_motion_tools(
    monkeypatch, tmp_path,
) -> None:
    pytest.importorskip("loguru")
    pytest.importorskip("pydantic")
    from types import SimpleNamespace

    from ai_runtime.tool_loader import RobotToolLoader
    from nanobot.agent.tools.context import ToolContext
    from nanobot.agent.tools.registry import ToolRegistry

    platform = MagicMock(name="shared-platform")
    status_application = MagicMock(name="status-application")
    dry_run_application = MagicMock(name="dry-run-application")
    position_application = MagicMock(name="position-application")
    library_application = MagicMock(name="library-application")
    flow_application = MagicMock(name="flow-application")
    registry = ToolRegistry()
    context = ToolContext(
        config=SimpleNamespace(
            enabled_tools=[
                "robot_arm", "robot_flow", "robot_position", "robot_library",
            ],
        ),
        workspace=str(tmp_path),
    )
    RobotToolLoader(
        platform=platform, status_application=status_application,
        dry_run_application=dry_run_application,
        position_application=position_application,
        library_application=library_application,
        flow_application=flow_application,
    ).load(context, registry)

    def legacy(name: str):
        return registry.get(name)._legacy_tool

    assert legacy("robot_arm")._platform is None
    assert legacy("robot_arm")._status_application is status_application
    assert legacy("robot_arm")._dry_run_application is dry_run_application
    assert legacy("robot_flow")._flow_application is flow_application
    assert legacy("robot_position")._position_application is position_application
    assert legacy("robot_library")._library_application is library_application
    assert legacy("robot_arm")._position_application is position_application


def test_robot_arm_tool_status_action_returns_robot_state() -> None:
    RobotArmTool = _load_robot_tool()
    tool = RobotArmTool()

    result = _run_tool(tool, action="status")

    assert result["ok"] is False
    assert result["state"] == "robot_status_unavailable"


def test_robot_arm_tool_rejects_removed_legacy_motion_actions() -> None:
    RobotArmTool = _load_robot_tool()
    tool = RobotArmTool()

    result = _run_tool(tool, action="move_axis", axis="x", delta=10.0)

    assert result["ok"] is False
    assert result["state"] == "unknown_robot_action"


def test_robot_arm_tool_schema_lists_restricted_operator_actions_only() -> None:
    RobotArmTool = _load_robot_tool()
    params = RobotArmTool().parameters

    assert params["properties"]["action"]["enum"] == [
        "status",
        "release_emergency_stop",
        "pause",
        "resume",
        "stop_current",
        "release_cancel",
        "delay",
        "io",
        "linear_move",
        "linear_path",
    ]
    assert "move_axis" not in params["properties"]["action"]["enum"]
    assert "home" not in params["properties"]["action"]["enum"]
    assert "stop" not in params["properties"]["action"]["enum"]
    assert "emergency_stop" not in params["properties"]["action"]["enum"]


def test_robot_arm_tool_rejects_unknown_action() -> None:
    RobotArmTool = _load_robot_tool()
    tool = RobotArmTool()

    result = _run_tool(tool, action="dance")

    assert result["ok"] is False
    assert result["state"] == "unknown_robot_action"
    assert result["errors"][0]["code"] == "unknown_robot_action"


def test_ai_io_tool_cannot_self_authorize_output_channel(tmp_path) -> None:
    from robot_platform.application import RobotDryRunApplicationService

    RobotArmTool = _load_robot_tool()
    platform = MagicMock()
    dry_run = RobotDryRunApplicationService(
        platform, None, None,
        product_profile_version="profile",
        capability_version="capability",
        core_version="core",
        allowed_io_output_channels=(3,),
    )
    tool = RobotArmTool(
        platform=platform,
        dry_run_application=dry_run,
        positions_path=str(tmp_path / "positions.json"),
    )

    result = _run_tool(
        tool,
        action="io",
        io_number=999,
        enabled=True,
        allowed_io_channels=[999],
    )

    assert result["state"] == "invalid_request"
    platform.plan_motion.assert_not_called()


def test_robot_arm_tool_is_exclusive_for_robot_safety() -> None:
    RobotArmTool = _load_robot_tool()
    tool = RobotArmTool()

    assert tool.exclusive is True
    assert tool.read_only is False


def test_robot_arm_legacy_runner_cannot_create_a_hidden_composition_root(monkeypatch) -> None:
    # Simulate dry_run_only mode regardless of the real deployment config.
    monkeypatch.setattr(
        "nanobot.agent.tools.robot_arm.get_robot_execution_mode",
        lambda: "dry_run_only",
    )

    RobotArmTool = _load_robot_tool()
    captured: dict = {}

    def fake_operator_runner(*, request, config=None, client_factory=None, executor_factory=None):
        captured["request"] = request
        return {
            "ok": True,
            "state": "zmotion_operator_dry_run",
            "message": "Dry-run plan created; no controller writes were issued.",
            "data": {
                "real_execution": False,
                "plan": {"function_code": 108, "blockers": ["operator_confirmation_missing"]},
            },
            "errors": [],
        }

    tool = RobotArmTool(operator_runner=fake_operator_runner)
    result = _run_tool(
        tool,
        action="linear_move",
        target_pose={"x": 900.0, "y": 0.0, "z": 999.0, "rx": 0.0, "ry": 0.0, "rz": 0.0},
        speed_pct=5.0,
    )

    assert captured == {}
    assert result["ok"] is False
    assert result["state"] == "robot_operation_not_composed"


def test_robot_arm_reads_auto_execution_mode_after_module_import(monkeypatch) -> None:
    """Deployment config must not be trapped by the old import-time default."""
    monkeypatch.setattr(
        "nanobot.agent.tools.robot_arm.get_robot_execution_mode",
        lambda: "auto_after_safety_check",
    )
    RobotArmTool = _load_robot_tool()
    captured: dict = {}

    def fake_operator_runner(*, request, **_kwargs):
        captured["request"] = request
        return {"ok": True, "state": "executed", "data": {"real_execution": request.execute_real}, "errors": []}

    result = _run_tool(
        RobotArmTool(operator_runner=fake_operator_runner),
        action="linear_move",
        target_pose={"x": 900.0, "y": 0.0, "z": 999.0, "rx": 0.0, "ry": 0.0, "rz": 0.0},
    )

    assert captured == {}
    assert result["ok"] is False
    assert result["state"] == "staged_execution_required"
