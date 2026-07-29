"""Select an Agent Provider without importing a concrete agent SDK."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_runtime.engine_contract import AgentEngine
from ai_runtime.provider_config import load_ai_runtime_config
from ai_runtime.provider_contract import AiProvider
from ai_runtime.providers.nanobot_provider import NanobotProvider
from ai_runtime.providers.nanobot_runtime import (
    create_nanobot_engine,
    local_reminder_content,
)
from ai_runtime.providers.scripted_provider import ScriptedProvider
from ai_runtime.tool_runtime import ToolAuditPort
from ai_runtime.tool_operation_store import ToolOperationStorePort
from nanobot.cron.application import CronMutationPolicyPort
from robot_platform.runtime import get_robot_data_dir

_local_reminder_content = local_reminder_content


def _profile_enabled_tools() -> list[str] | None:
    path = get_robot_data_dir() / "product_profile.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    tools = payload.get("enabled_tools") if isinstance(payload, dict) else None
    return [item for item in tools if isinstance(item, str)] if isinstance(tools, list) else None


def create_agent_runtime(
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
    provider: AiProvider | None = None,
) -> AgentEngine:
    """Create the deployment-selected engine behind the stable Provider contract."""
    provider_config = load_ai_runtime_config(config_path)
    selected_tools = enabled_tools if enabled_tools is not None else _profile_enabled_tools()
    selected_provider = provider or _default_provider(
        provider_config.engine_id,
        enabled_tools=selected_tools,
        platform=platform,
        status_application=status_application,
        dry_run_application=dry_run_application,
        knowledge_application=knowledge_application,
        position_application=position_application,
        library_application=library_application,
        flow_application=flow_application,
        cron_mutation_policy=cron_mutation_policy,
        tool_audit=tool_audit,
        tool_operation_store=tool_operation_store,
    )
    return selected_provider.create_engine(provider_config, config_path=config_path)


def _default_provider(engine_id: str, **runtime_options: Any) -> AiProvider:
    if engine_id == "nanobot":
        return NanobotProvider(
            lambda path: create_nanobot_engine(path, **runtime_options)
        )
    if engine_id == "scripted":
        return ScriptedProvider()
    raise ValueError(f"Unknown AI engine: {engine_id}")
