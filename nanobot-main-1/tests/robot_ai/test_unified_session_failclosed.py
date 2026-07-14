import pytest


def test_unified_true_raises():
    from robot_ai.library.users import assert_unified_session_disabled
    with pytest.raises(RuntimeError, match="unified_session"):
        assert_unified_session_disabled(True)


def test_unified_false_ok():
    from robot_ai.library.users import assert_unified_session_disabled
    assert_unified_session_disabled(False)


def test_unified_none_ok():
    from robot_ai.library.users import assert_unified_session_disabled
    assert_unified_session_disabled(None)


def test_channel_init_failclosed_on_unified_true(tmp_path):
    from nanobot.bus.queue import MessageBus
    from nanobot.channels.websocket import WebSocketChannel, WebSocketConfig
    from nanobot.session.manager import SessionManager
    from nanobot.webui.gateway_services import build_gateway_services
    cfg = WebSocketConfig.model_validate({
        "enabled": True, "allowFrom": ["*"], "host": "127.0.0.1", "port": 29878,
        "path": "/ws", "websocketRequiresToken": False})
    gw = build_gateway_services(
        config=cfg, bus=MessageBus(),
        session_manager=SessionManager(tmp_path), static_dist_path=None,
        workspace_path=tmp_path, default_restrict_to_workspace=False,
        runtime_model_name=None, runtime_surface="browser",
        runtime_capabilities_overrides=None)
    with pytest.raises(RuntimeError, match="unified_session"):
        WebSocketChannel(cfg, MessageBus(), gateway=gw, unified_session=True)


def test_channel_init_requires_unified_session_kwarg(tmp_path):
    from nanobot.bus.queue import MessageBus
    from nanobot.channels.websocket import WebSocketChannel, WebSocketConfig
    from nanobot.webui.gateway_services import build_gateway_services
    cfg = WebSocketConfig.model_validate({
        "enabled": True, "allowFrom": ["*"], "host": "127.0.0.1", "port": 29879,
        "path": "/ws", "websocketRequiresToken": False})
    gw = build_gateway_services(
        config=cfg, bus=MessageBus(), session_manager=None, static_dist_path=None,
        workspace_path=tmp_path, default_restrict_to_workspace=False,
        runtime_model_name=None, runtime_surface="browser",
        runtime_capabilities_overrides=None)
    with pytest.raises(TypeError):
        WebSocketChannel(cfg, MessageBus(), gateway=gw)  # missing unified_session
