"""Adapter for the retained Nanobot AgentEngine implementation."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ai_runtime.engine_contract import AgentEngine
from ai_runtime.provider_config import AiProviderConfig


class NanobotProvider:
    """Construct the retained engine from a deployment-selected runtime config."""

    engine_id = "nanobot"

    def __init__(self, engine_factory: Callable[[Path | None], AgentEngine]) -> None:
        self._engine_factory = engine_factory

    def create_engine(
        self,
        config: AiProviderConfig,
        *,
        config_path: Path | None = None,
    ) -> AgentEngine:
        if config.engine_id != self.engine_id:
            raise ValueError(f"Unsupported AI engine: {config.engine_id}")
        return self._engine_factory(config_path)
