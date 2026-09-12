"""Engine providers selected only by deployment configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from ai_runtime.engine_contract import AgentEngine
from ai_runtime.provider_config import AiProviderConfig


@runtime_checkable
class AiProvider(Protocol):
    """Construct an AgentEngine without exposing configuration to a user UI."""

    engine_id: str

    def create_engine(
        self,
        config: AiProviderConfig,
        *,
        config_path: Path | None = None,
    ) -> AgentEngine:
        ...
