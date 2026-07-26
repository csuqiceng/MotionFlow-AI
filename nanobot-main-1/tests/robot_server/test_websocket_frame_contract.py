"""Fixture-backed compatibility contract for retained WebUI runtime events."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_runtime import RuntimeEvent
from robot_server.webui_compat import legacy_webui_frame_for_runtime_event


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "webui-runtime-frame-contract.json"


@pytest.mark.parametrize("case", json.loads(FIXTURE_PATH.read_text(encoding="utf-8")))
def test_retained_webui_runtime_frames_remain_compatible(case: dict[str, object]) -> None:
    source = case["event"]
    assert isinstance(source, dict)
    conversation_id = source["conversation_id"]
    kind = source["kind"]
    payload = source["payload"]
    assert isinstance(conversation_id, str)
    assert isinstance(kind, str)
    assert isinstance(payload, dict)

    streamed = {conversation_id} if case.get("streamed_before") else set()
    frame = legacy_webui_frame_for_runtime_event(
        RuntimeEvent(conversation_id, kind, payload), streamed
    )

    assert frame == case["expected"]
