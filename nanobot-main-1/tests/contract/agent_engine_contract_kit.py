"""Reusable lifecycle/event/session contract for AgentEngine implementations."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from ai_runtime.engine_contract import AgentEngine, AgentRequest
from ai_runtime.identity import issue_verified_principal


async def assert_agent_engine_contract(factory: Callable[[], AgentEngine]) -> None:
    engine = factory()
    await engine.start()
    await engine.check_ai_connectivity()
    stream = engine.subscribe()
    second_stream = engine.subscribe()
    try:
        principal = issue_verified_principal(
            actor_id="user-1", role="operator",
            session_id="contract-session", auth_source="contract-test",
        )
        first_waiters = (
            asyncio.create_task(anext(stream)),
            asyncio.create_task(anext(second_stream)),
        )
        await asyncio.sleep(0)
        await engine.submit(AgentRequest(
            conversation_id="conversation-1",
            actor_id=principal.actor,
            content="hello",
            request_id="request-1",
            principal=principal,
        ))
        first, mirrored = await asyncio.wait_for(
            asyncio.gather(*first_waiters), timeout=1,
        )
        second, mirrored_second = await asyncio.wait_for(
            asyncio.gather(anext(stream), anext(second_stream)), timeout=1,
        )
        assert [first.kind, second.kind] == ["final", "turn_end"]
        assert [mirrored.kind, mirrored_second.kind] == ["final", "turn_end"]
        assert first.request_id == second.request_id == "request-1"
        assert engine.list_sessions()
        assert engine.read_session("conversation-1") is not None
        assert await engine.cancel("conversation-1") >= 0
        deleted = await engine.delete_conversation("conversation-1")
        assert deleted["deleted"] is True
        assert engine.read_session("conversation-1") is None
    finally:
        await stream.aclose()
        await second_stream.aclose()
        await engine.stop()
