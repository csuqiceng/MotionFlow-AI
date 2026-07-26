"""Construct the temporary AI runtime from the existing provider configuration."""

from __future__ import annotations

import re
from pathlib import Path

from ai_runtime.engine_contract import AgentEngine, AgentRequest
from ai_runtime.nanobot_engine import NanobotEngine
from ai_runtime.provider_config import load_ai_runtime_config
from ai_runtime.providers.nanobot_provider import NanobotProvider
from ai_runtime.robot_prompt import ROBOT_RUNTIME_PROMPT
from ai_runtime.tool_loader import RobotToolLoader
from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.config.loader import load_config
from nanobot.config.paths import get_cron_dir
from nanobot.cron.service import CronService
from nanobot.session.manager import SessionManager


_LEGACY_LOCAL_MESSAGE_DELIVERY = re.compile(
    r'^\s*Send a message to the user in channel robot-server '
    r'\(chat_id: [^)]+\):\s*["“](?P<content>.*)["”]\s*$',
    re.DOTALL,
)


def _local_reminder_content(message: str) -> str:
    """Unwrap legacy channel-delivery prompts into a local reminder.

    Earlier desktop jobs were stored as instructions to invoke Nanobot's
    removed ``message`` tool.  The robot server owns one local conversation,
    so the embedded reminder is the only content an automation turn needs.
    """
    matched = _LEGACY_LOCAL_MESSAGE_DELIVERY.match(message)
    if not matched:
        return message
    content = matched.group("content").strip()
    return content or message


def create_agent_runtime(config_path: Path | None = None) -> AgentEngine:
    """Create the deployment-configured AI engine without exposing it to UI."""
    provider_config = load_ai_runtime_config(config_path)
    return NanobotProvider(_create_nanobot_runtime).create_engine(
        provider_config,
        config_path=config_path,
    )


def _create_nanobot_runtime(config_path: Path | None = None) -> AgentEngine:
    """Build the Nanobot-backed AgentEngine without a channel or gateway server."""
    config = load_config(config_path)
    bus = MessageBus()
    runtime_ref: dict[str, AgentEngine] = {}

    async def run_scheduled_turn(job) -> str | None:
        """Deliver a scheduler job straight to the owning local conversation."""
        runtime = runtime_ref["runtime"]
        session_key = job.payload.session_key or ""
        prefix = "robot-server:"
        if not session_key.startswith(prefix):
            raise RuntimeError("scheduled job is not bound to a robot-server conversation")
        await runtime.submit(AgentRequest(
            conversation_id=session_key[len(prefix):],
            actor_id="automation",
            content=_local_reminder_content(job.payload.message),
            stream=True,
            request_id=f"automation:{job.id}",
        ))
        return None

    cron_service = CronService(get_cron_dir() / "jobs.json", on_job=run_scheduled_turn)
    loop = AgentLoop.from_config(
        config,
        bus,
        session_manager=SessionManager(config.workspace_path),
        cron_service=cron_service,
        tool_loader=RobotToolLoader(),
        enable_builtin_commands=False,
        system_prompt_addendum=ROBOT_RUNTIME_PROMPT,
    )
    runtime = NanobotEngine(loop)
    runtime_ref["runtime"] = runtime
    return runtime
