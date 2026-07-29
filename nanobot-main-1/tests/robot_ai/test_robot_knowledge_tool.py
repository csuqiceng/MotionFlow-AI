from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("loguru")
pytest.importorskip("pydantic")

from nanobot.agent.tools.robot_knowledge import RobotKnowledgeTool
from robot_ai.knowledge.loader import KnowledgeStore
from robot_ai.knowledge.models import KnowledgeEntry
from robot_platform.adapters import FileRobotKnowledgeAdapter
from robot_platform.application import RobotKnowledgeApplicationService


def _run(tool, **kw):
    return json.loads(asyncio.run(tool.execute(**kw)))


def test_list_and_query(tmp_path) -> None:
    p = tmp_path / "k.json"
    KnowledgeStore(p).replace(
        [
            KnowledgeEntry(category="safety", title="E-stop", content="press red", source="t"),
            KnowledgeEntry(category="error_code", title="Z_LIMIT", content="z over", source="t"),
        ]
    )
    tool = RobotKnowledgeTool(
        knowledge_application=RobotKnowledgeApplicationService(
            FileRobotKnowledgeAdapter(p),
        )
    )
    listed = _run(tool, action="list")
    assert listed["data"]["count"] == 2
    q = _run(tool, action="query", category="error_code")
    assert q["data"]["entries"][0]["title"] == "Z_LIMIT"
    kw = _run(tool, action="query", keyword="red")
    assert kw["data"]["entries"][0]["category"] == "safety"


def test_no_write_marker(tmp_path) -> None:
    tool = RobotKnowledgeTool(
        knowledge_application=RobotKnowledgeApplicationService(
            FileRobotKnowledgeAdapter(tmp_path / "k.json"),
        )
    )
    r = _run(tool, action="list")
    assert r["ok"] is True
    assert r["data"].get("writes") is None
