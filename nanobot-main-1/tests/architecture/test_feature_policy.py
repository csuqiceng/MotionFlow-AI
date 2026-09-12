from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer

from robot_platform.feature_policy import FeatureDisabledError, ProductFeaturePolicy
from robot_platform.platform import RobotPlatform
from robot_server.app import RobotServerConfig, create_robot_server_app
from robot_platform.flow import FlowEntry, FlowStep


def test_disabled_arm_and_flow_are_enforced_below_every_transport() -> None:
    dispatches: list[object] = []
    platform = RobotPlatform(
        operator_runner=lambda **kwargs: dispatches.append(kwargs) or {"ok": True},
        feature_policy=ProductFeaturePolicy.from_enabled_tools(["robot_knowledge"]),
    )

    with pytest.raises(FeatureDisabledError):
        platform.plan_motion("delay", {"seconds": 0})
    with pytest.raises(FeatureDisabledError):
        platform.resolve_flow("any")
    assert dispatches == []


def test_real_flow_requires_both_flow_and_arm_features() -> None:
    calls: list[object] = []
    platform = RobotPlatform(
        flow_runner=lambda *args, **kwargs: calls.append((args, kwargs)) or {"ok": True},
        feature_policy=ProductFeaturePolicy.from_enabled_tools(["robot_flow"]),
    )
    with pytest.raises(FeatureDisabledError):
        platform.run_flow_entry(
            FlowEntry(name="f", steps=[FlowStep(1, "delay", 110, {"seconds": 0})]),
            execute_real=True,
        )
    assert calls == []


def test_application_port_decorator_blocks_direct_component_bypass() -> None:
    calls: list[str] = []

    class KnowledgeApplication:
        def query(self) -> str:
            calls.append("query")
            return "secret"

    guarded = ProductFeaturePolicy.from_enabled_tools(["robot_arm"]).protect(
        "robot_knowledge", KnowledgeApplication(),
    )
    with pytest.raises(FeatureDisabledError):
        guarded.query()
    assert calls == []


@pytest.mark.asyncio
async def test_http_feature_catalog_blocks_disabled_component(tmp_path) -> None:
    (tmp_path / "product_profile.json").write_text(
        '{"backend_mode":"simulation","enabled_tools":["robot_knowledge"]}',
        encoding="utf-8",
    )
    app = create_robot_server_app(
        config=RobotServerConfig(robot_data_dir=tmp_path),
    )
    async with TestClient(TestServer(app)) as client:
        response = await client.get("/api/robot/status")
        assert response.status == 404
        assert (await response.json())["error"] == "feature_disabled"


@pytest.mark.asyncio
async def test_legacy_principal_flag_never_bypasses_user_authentication(tmp_path) -> None:
    app = create_robot_server_app(config=RobotServerConfig(
        robot_data_dir=tmp_path, trusted_principal_v1=False,
    ))
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/api/robot/flow-pending-plan", json={"flow_name": "anything"},
        )
        assert response.status == 401
