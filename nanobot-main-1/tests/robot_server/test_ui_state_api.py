from __future__ import annotations

from robot_server.ui_state_api import _ui_message


def test_history_replay_hides_tool_results_and_empty_tool_call_placeholders() -> None:
    assert _ui_message({
        "role": "tool",
        "name": "robot_arm",
        "content": '{"state": "status_report"}',
    }, 1) is None
    assert _ui_message({
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": "robot_arm"}}],
    }, 2) is None


def test_history_replay_keeps_user_and_final_assistant_messages() -> None:
    user = _ui_message({"role": "user", "content": "状态"}, 0)
    assistant = _ui_message({"role": "assistant", "content": "控制器未连接。"}, 3)

    assert user is not None
    assert user["role"] == "user"
    assert assistant is not None
    assert assistant["content"] == "控制器未连接。"
