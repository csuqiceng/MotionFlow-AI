"""Deployment-only selection of the AI engine and provider model."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from nanobot.config.loader import load_config


@dataclass(frozen=True)
class AiProviderConfig:
    """Non-secret AI runtime selection resolved only inside the server process."""

    engine_id: str
    provider: str
    model: str
    credential_ref: str


def load_ai_runtime_config(
    config_path: Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> AiProviderConfig:
    """Read AI selection from the existing protected runtime configuration.

    This intentionally returns a credential reference, never an API key,
    endpoint URL or provider configuration object.  It is not exposed by any
    HTTP or WebSocket payload.
    """
    source = env if env is not None else os.environ
    config = load_config(config_path)
    preset = config.resolve_preset()
    provider = config.get_provider_name(model=preset.model, preset=config.agents.defaults.model_preset)
    credential_ref = source.get(
        "ROBOT_AI_CREDENTIAL_REF",
        f"config:providers.{provider}.api_key",
    ).strip()
    return AiProviderConfig(
        engine_id=(source.get("ROBOT_AI_ENGINE", "nanobot").strip() or "nanobot"),
        provider=provider,
        model=preset.model,
        credential_ref=credential_ref,
    )
