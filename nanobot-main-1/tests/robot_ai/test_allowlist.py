from __future__ import annotations

from nanobot.agent.tools.allowlist import tool_allowed


def test_wildcard_allows_everything() -> None:
    assert tool_allowed("exec", ["*"]) is True
    assert tool_allowed("robot_arm", ["*"]) is True


def test_restrict_list_allows_only_listed() -> None:
    allowed = ["robot_arm", "robot_flow", "robot_knowledge", "robot_position"]
    assert tool_allowed("robot_arm", allowed) is True
    assert tool_allowed("exec", allowed) is False
    assert tool_allowed("web_search", allowed) is False


def test_empty_list_blocks_all() -> None:
    assert tool_allowed("robot_arm", []) is False
