"""Construct the temporary AI runtime from the existing provider configuration."""

from __future__ import annotations

from pathlib import Path

from ai_runtime.agent_runtime import AgentRuntime
from ai_runtime.contracts import RuntimeRequest
from ai_runtime.tool_loader import RobotToolLoader
from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.config.loader import load_config
from nanobot.config.paths import get_cron_dir
from nanobot.cron.service import CronService
from nanobot.session.manager import SessionManager


def create_agent_runtime(config_path: Path | None = None) -> AgentRuntime:
    """Build AgentRuntime without creating a ChannelManager or gateway server."""
    config = load_config(config_path)
    bus = MessageBus()
    runtime_ref: dict[str, AgentRuntime] = {}

    async def run_scheduled_turn(job) -> str | None:
        """Deliver a scheduler job straight to the owning local conversation."""
        runtime = runtime_ref["runtime"]
        session_key = job.payload.session_key or ""
        prefix = "robot-server:"
        if not session_key.startswith(prefix):
            raise RuntimeError("scheduled job is not bound to a robot-server conversation")
        await runtime.submit(RuntimeRequest(
            conversation_id=session_key[len(prefix):],
            actor_id="automation",
            content=job.payload.message,
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
    )
    runtime = AgentRuntime(loop)
    runtime_ref["runtime"] = runtime
    return runtime
