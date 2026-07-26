"""Adapter that binds the retained Nanobot loop to the stable AgentEngine API."""

from __future__ import annotations

from ai_runtime.agent_runtime import AgentRuntime


class NanobotEngine(AgentRuntime):
    """Named composition adapter; only this layer needs the retained loop runtime."""
