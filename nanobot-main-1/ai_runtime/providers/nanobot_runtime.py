"""Nanobot-specific AgentEngine composition adapter."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ai_runtime.engine_contract import AgentEngine, AgentRequest
from ai_runtime.identity import issue_verified_principal
from ai_runtime.providers.nanobot_engine import NanobotEngine
from ai_runtime.robot_prompt import ROBOT_RUNTIME_PROMPT
from ai_runtime.tool_loader import RobotToolLoader
from ai_runtime.tool_runtime import ToolAuditPort
from ai_runtime.tool_operation_store import ToolOperationStorePort
from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.config.loader import load_config
from nanobot.config.paths import get_cron_dir
from nanobot.cron.service import CronService
from nanobot.cron.application import CronMutationPolicyPort
from nanobot.cron.application_adapter import NanobotCronApplicationAdapter
from nanobot.session.manager import SessionManager

_LEGACY_LOCAL_MESSAGE_DELIVERY = re.compile(
    r'^\s*Send a message to the user in channel robot-server '
    r'\(chat_id: [^)]+\):\s*["“](?P<content>.*)["”]\s*$',
    re.DOTALL,
)


def local_reminder_content(message: str) -> str:
    matched = _LEGACY_LOCAL_MESSAGE_DELIVERY.match(message)
    if not matched:
        return message
    content = matched.group("content").strip()
    return content or message


def create_nanobot_engine(
    config_path: Path | None = None,
    *,
    enabled_tools: list[str] | None = None,
    platform: Any = None,
    status_application: Any = None,
    dry_run_application: Any = None,
    knowledge_application: Any = None,
    position_application: Any = None,
    library_application: Any = None,
    flow_application: Any = None,
    cron_mutation_policy: CronMutationPolicyPort | None = None,
    tool_audit: ToolAuditPort | None = None,
    tool_operation_store: ToolOperationStorePort | None = None,
) -> AgentEngine:
    config = load_config(config_path)
    bus = MessageBus()
    runtime_ref: dict[str, AgentEngine] = {}
    cron_enabled = (
        enabled_tools is None
        or "*" in enabled_tools
        or "cron" in enabled_tools
    )

    async def run_scheduled_turn(job: Any) -> str | None:
        if not cron_enabled:
            raise PermissionError("Cron product feature is disabled")
        runtime = runtime_ref["runtime"]
        session_key = job.payload.session_key or ""
        prefix = "robot-server:"
        if not session_key.startswith(prefix):
            raise RuntimeError("scheduled job is not bound to a robot-server conversation")
        automation_principal = issue_verified_principal(
            actor_id="automation",
            role="system",
            session_id=session_key,
            auth_source="local-scheduler",
        )
        await runtime.submit(AgentRequest(
            conversation_id=session_key[len(prefix):],
            actor_id=automation_principal.actor,
            content=local_reminder_content(job.payload.message),
            stream=True,
            request_id=f"automation:{job.id}",
            principal=automation_principal,
        ))
        return None

    cron_service = (
        CronService(get_cron_dir() / "jobs.json", on_job=run_scheduled_turn)
        if cron_enabled else None
    )
    cron_application = (
        NanobotCronApplicationAdapter(cron_service)
        if cron_service is not None else None
    )
    loop = AgentLoop.from_config(
        config,
        bus,
        session_manager=SessionManager(config.workspace_path),
        cron_service=cron_service,
        tool_loader=RobotToolLoader(
            enabled_tools=enabled_tools,
            platform=platform,
            status_application=status_application,
            dry_run_application=dry_run_application,
            knowledge_application=knowledge_application,
            position_application=position_application,
            library_application=library_application,
            flow_application=flow_application,
            cron_application=cron_application,
            cron_mutation_policy=cron_mutation_policy,
            tool_audit=tool_audit,
            tool_operation_store=tool_operation_store,
        ),
        enable_builtin_commands=False,
        system_prompt_addendum=ROBOT_RUNTIME_PROMPT,
    )
    runtime = NanobotEngine(loop)
    runtime_ref["runtime"] = runtime
    return runtime
