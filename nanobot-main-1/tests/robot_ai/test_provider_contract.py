"""Deployment-only AI provider configuration for the robot runtime."""

from __future__ import annotations

import importlib.util
import json
from dataclasses import asdict
from unittest.mock import MagicMock

from ai_runtime.provider_config import load_ai_runtime_config
from ai_runtime.provider_config import AiProviderConfig
from ai_runtime.providers.nanobot_provider import NanobotProvider


def test_provider_configuration_module_exists() -> None:
    assert importlib.util.find_spec("ai_runtime.provider_config") is not None


def test_nanobot_engine_provider_module_exists() -> None:
    assert importlib.util.find_spec("ai_runtime.providers.nanobot_provider") is not None


def test_deployment_provider_config_contains_no_secret_or_endpoint(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "agents": {"defaults": {"provider": "openai", "model": "gpt-test"}},
                "providers": {"openai": {"apiKey": "secret-value", "apiBase": "https://internal.example/v1"}},
            }
        ),
        encoding="utf-8",
    )

    provider = load_ai_runtime_config(
        config_path,
        env={"ROBOT_AI_CREDENTIAL_REF": "os-vault:robot-ai"},
    )

    assert provider.engine_id == "nanobot"
    assert provider.provider == "openai"
    assert provider.model == "gpt-test"
    assert provider.credential_ref == "os-vault:robot-ai"
    assert asdict(provider) == {
        "engine_id": "nanobot",
        "provider": "openai",
        "model": "gpt-test",
        "credential_ref": "os-vault:robot-ai",
    }


def test_nanobot_provider_uses_only_the_selected_deployment_engine(tmp_path) -> None:
    engine = MagicMock()
    factory = MagicMock(return_value=engine)
    provider = NanobotProvider(factory)
    config = AiProviderConfig(
        engine_id="nanobot",
        provider="openai",
        model="gpt-test",
        credential_ref="os-vault:robot-ai",
    )

    assert provider.create_engine(config, config_path=tmp_path / "config.json") is engine
    factory.assert_called_once_with(tmp_path / "config.json")
