from __future__ import annotations

from pathlib import Path

import pytest

from ai_runtime.engine_contract import AgentEngine
from ai_runtime.provider_config import AiProviderConfig
from ai_runtime.provider_contract import AiProvider
from ai_runtime.providers.scripted_provider import ScriptedAgentEngine, ScriptedProvider
from tests.contract.agent_engine_contract_kit import assert_agent_engine_contract


class FakeProvider:
    engine_id = "fake"

    def create_engine(
        self,
        config: AiProviderConfig,
        *,
        config_path: Path | None = None,
    ) -> AgentEngine:
        del config_path
        if config.engine_id != self.engine_id:
            raise ValueError("wrong engine")
        return ScriptedAgentEngine()


@pytest.mark.parametrize("factory", [ScriptedAgentEngine], ids=["scripted"])
@pytest.mark.asyncio
async def test_agent_engine_implements_shared_contract(factory) -> None:
    await assert_agent_engine_contract(factory)


def test_fake_and_scripted_providers_implement_provider_contract() -> None:
    assert isinstance(FakeProvider(), AiProvider)
    assert isinstance(ScriptedProvider(), AiProvider)
    fake = FakeProvider().create_engine(AiProviderConfig(
        engine_id="fake", provider="none", model="fake", credential_ref="none",
    ))
    scripted = ScriptedProvider().create_engine(AiProviderConfig(
        engine_id="scripted", provider="none", model="scripted", credential_ref="none",
    ))
    assert isinstance(fake, AgentEngine)
    assert isinstance(scripted, AgentEngine)
