from ai_runtime import RuntimeEvent
from robot_server.websocket_frames import webui_frame_for_runtime_event
from robot_server.webui_compat import legacy_webui_frame_for_runtime_event


def test_runtime_events_have_a_stable_product_websocket_shape() -> None:
    frame = webui_frame_for_runtime_event(RuntimeEvent(
        conversation_id="chat-1", kind="tool_progress",
        payload={"content": "robot_get_status", "tool_hint": True, "tool_events": [{"phase": "start"}]},
    ))

    assert frame == {
        "event": "message", "session_id": "chat-1", "text": "robot_get_status",
        "kind": "tool_hint", "tool_events": [{"phase": "start"}],
    }


def test_legacy_webui_uses_one_answer_representation_per_streamed_turn() -> None:
    streamed: set[str] = set()

    assert legacy_webui_frame_for_runtime_event(
        RuntimeEvent("chat-1", "delta", {"content": "partial"}), streamed
    ) == {"event": "delta", "chat_id": "chat-1", "text": "partial"}
    assert legacy_webui_frame_for_runtime_event(
        RuntimeEvent("chat-1", "final", {"content": "partial answer"}), streamed
    ) is None
    assert legacy_webui_frame_for_runtime_event(
        RuntimeEvent("chat-1", "reasoning_delta", {"content": "checking"}), streamed
    ) == {"event": "reasoning_delta", "chat_id": "chat-1", "text": "checking"}
    assert legacy_webui_frame_for_runtime_event(
        RuntimeEvent("chat-1", "reasoning_end"), streamed
    ) == {"event": "reasoning_end", "chat_id": "chat-1"}
    assert legacy_webui_frame_for_runtime_event(
        RuntimeEvent("chat-1", "turn_end"), streamed
    ) == {"event": "turn_end", "chat_id": "chat-1"}
    assert streamed == set()


def test_legacy_webui_keeps_reasoning_and_tool_activity_in_distinct_frames() -> None:
    streamed: set[str] = set()

    assert legacy_webui_frame_for_runtime_event(
        RuntimeEvent("chat-2", "reasoning_delta", {"content": "Inspect pose."}), streamed
    ) == {"event": "reasoning_delta", "chat_id": "chat-2", "text": "Inspect pose."}
    assert legacy_webui_frame_for_runtime_event(
        RuntimeEvent("chat-2", "tool_progress", {"content": "robot_get_status", "tool_hint": True}), streamed
    ) == {"event": "message", "chat_id": "chat-2", "text": "robot_get_status", "kind": "tool_hint"}
