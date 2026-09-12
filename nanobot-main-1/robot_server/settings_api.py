"""Direct, local settings API for the retained WebUI."""

from __future__ import annotations

from typing import Any
from contextlib import suppress

from nanobot.agent.tools.web import SEARCH_PROVIDER_OPTIONS
from nanobot import __version__
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import ModelPresetConfig
from nanobot.providers.registry import find_by_name


class LocalSettingsService:
    """Read and update the existing nanobot-compatible local configuration.

    Secrets are accepted on write but never returned in payloads.
    """

    def payload(self) -> dict[str, Any]:
        config = load_config()
        defaults = config.agents.defaults
        # AI provider, model, endpoint and credential configuration belongs to
        # deployment-only configuration.  No user-facing HTTP payload may
        # disclose or edit those values, even as redacted labels.
        providers: list[dict[str, Any]] = []
        presets: list[dict[str, Any]] = []
        web = config.tools.web
        image = config.tools.image_generation
        transcription = config.transcription
        return {
            "surface": "native", "runtime_surface": "native",
            "runtime_capabilities": {"can_restart_engine": True, "can_pick_folder": False, "can_open_logs": False, "can_export_diagnostics": False},
            "agent": {"configured": True,
                "bot_name": defaults.bot_name, "bot_icon": defaults.bot_icon,
                "tool_hint_max_length": defaults.tool_hint_max_length},
            "model_presets": presets, "providers": providers,
            "web_search": {"provider": web.search.provider, "api_key_hint": _hint(web.search.api_key),
                "base_url": web.search.base_url or None, "max_results": web.search.max_results, "timeout": web.search.timeout,
                "providers": list(SEARCH_PROVIDER_OPTIONS)},
            "web": {"enable": web.enable, "proxy": web.proxy, "user_agent": web.user_agent,
                "search": {"max_results": web.search.max_results, "timeout": web.search.timeout},
                "fetch": {"use_jina_reader": web.fetch.use_jina_reader}},
            "image_generation": {"enabled": image.enabled, "provider": image.provider,
                "provider_configured": any(item["name"] == image.provider and item["configured"] for item in providers),
                "model": image.model, "default_aspect_ratio": image.default_aspect_ratio,
                "default_image_size": image.default_image_size, "max_images_per_turn": image.max_images_per_turn,
                "save_dir": image.save_dir, "providers": providers},
            "transcription": {"enabled": transcription.enabled, "provider": transcription.provider or "",
                "provider_configured": bool(transcription.provider), "model": transcription.model or "",
                "language": transcription.language, "max_duration_sec": transcription.max_duration_sec,
                "max_upload_mb": transcription.max_upload_mb, "providers": providers},
            "runtime": {"config_path": "local configuration", "workspace_path": "local workspace", "gateway_host": "127.0.0.1", "gateway_port": 0,
                "heartbeat": {"enabled": False, "interval_s": 0, "keep_recent_messages": 0}, "dream": {"schedule": defaults.dream.describe_schedule()}, "unified_session": defaults.unified_session},
            "advanced": {"restrict_to_workspace": config.tools.restrict_to_workspace, "ssrf_whitelist_count": len(config.tools.ssrf_whitelist),
                "webui_allow_local_service_access": config.tools.webui_allow_local_service_access,
                "webui_default_access_mode": "default" if config.tools.restrict_to_workspace else "full",
                "private_service_protection_enabled": True, "mcp_server_count": len(config.tools.mcp_servers),
                "exec_enabled": config.tools.exec.enable, "exec_sandbox": config.tools.exec.sandbox,
                "exec_path_prepend_set": bool(config.tools.exec.path_prepend), "exec_path_append_set": bool(config.tools.exec.path_append)},
            "requires_restart": False,
        }

    def update_agent(self, values: dict[str, str]) -> tuple[int, dict[str, Any]]:
        config = load_config(); defaults = config.agents.defaults
        _set_if(values, "model", defaults, "model"); _set_if(values, "provider", defaults, "provider")
        _set_if(values, "model_preset", defaults, "model_preset")
        _set_if(values, "bot_name", defaults, "bot_name"); _set_if(values, "bot_icon", defaults, "bot_icon")
        _set_int(values, "context_window_tokens", defaults, "context_window_tokens"); _set_int(values, "tool_hint_max_length", defaults, "tool_hint_max_length")
        save_config(config); return 200, self.payload()

    def update_provider(self, values: dict[str, str]) -> tuple[int, dict[str, Any]]:
        config = load_config(); name = values.get("provider", "").replace("-", "_")
        provider = getattr(config.providers, name, None)
        if provider is None: return 400, _error("unknown provider")
        _set_if(values, "api_key", provider, "api_key"); _set_if(values, "api_base", provider, "api_base"); _set_if(values, "api_type", provider, "api_type")
        save_config(config); return 200, self.payload()

    def update_web_search(self, values: dict[str, str]) -> tuple[int, dict[str, Any]]:
        config = load_config(); search = config.tools.web.search
        _set_if(values, "provider", search, "provider"); _set_if(values, "api_key", search, "api_key"); _set_if(values, "base_url", search, "base_url")
        _set_int(values, "max_results", search, "max_results"); _set_int(values, "timeout", search, "timeout")
        if "use_jina_reader" in values: config.tools.web.fetch.use_jina_reader = values["use_jina_reader"].lower() == "true"
        save_config(config); return 200, self.payload()

    def create_model_configuration(self, values: dict[str, str]) -> tuple[int, dict[str, Any]]:
        config = load_config()
        label = values.get("label", "").strip()
        model = values.get("model", "").strip()
        provider = values.get("provider", "").strip()
        name = values.get("name", "").strip() or _preset_name(label)
        if not label or not model or not provider or not name:
            return 400, _error("name, label, provider and model are required")
        if name == "default" or name in config.model_presets:
            return 409, _error("model configuration already exists")
        try:
            config.model_presets[name] = ModelPresetConfig(label=label, model=model, provider=provider)
            save_config(config)
        except (TypeError, ValueError) as exc:
            return 400, _error(str(exc))
        return 200, self.payload()

    def update_model_configuration(self, values: dict[str, str]) -> tuple[int, dict[str, Any]]:
        config = load_config(); name = values.get("name", "").strip()
        preset = config.model_presets.get(name)
        if preset is None:
            return 404, _error("model configuration not found")
        _set_if(values, "label", preset, "label"); _set_if(values, "provider", preset, "provider")
        _set_if(values, "model", preset, "model"); _set_int(values, "context_window_tokens", preset, "context_window_tokens")
        try:
            save_config(config)
        except (TypeError, ValueError) as exc:
            return 400, _error(str(exc))
        return 200, self.payload()

    def provider_models(self, values: dict[str, str]) -> tuple[int, dict[str, Any]]:
        config = load_config(); name = values.get("provider", "").replace("-", "_")
        provider = getattr(config.providers, name, None)
        if provider is None:
            return 404, _error("unknown provider")
        configured = bool(getattr(provider, "api_key", None) or getattr(provider, "api_base", None))
        active = config.agents.defaults
        models = ([{"id": active.model, "label": active.model, "owned_by": name}]
                  if active.provider.replace("-", "_") == name and active.model else [])
        return 200, {"provider": name, "label": name.replace("_", " ").title(),
                     "status": "available" if configured else "not_configured",
                     "catalog_kind": "custom", "models": models, "model_count": len(models),
                     "message": None if configured else "Configure this provider before loading its model catalog."}

    def update_network_safety(self, values: dict[str, str]) -> tuple[int, dict[str, Any]]:
        config = load_config()
        if "webui_allow_local_service_access" in values:
            config.tools.webui_allow_local_service_access = _bool(values["webui_allow_local_service_access"])
        # The desktop server is intentionally a single local process.  Access
        # mode remains a UI/workspace preference and cannot loosen the server's
        # loopback-only authentication boundary.
        save_config(config); return 200, self.payload()

    def update_image_generation(self, values: dict[str, str]) -> tuple[int, dict[str, Any]]:
        config = load_config(); image = config.tools.image_generation
        if "enabled" in values: image.enabled = _bool(values["enabled"])
        _set_if(values, "provider", image, "provider"); _set_if(values, "model", image, "model")
        _set_if(values, "default_aspect_ratio", image, "default_aspect_ratio")
        _set_if(values, "default_image_size", image, "default_image_size")
        _set_int(values, "max_images_per_turn", image, "max_images_per_turn")
        try:
            save_config(config)
        except (TypeError, ValueError) as exc:
            return 400, _error(str(exc))
        return 200, self.payload()

    def update_transcription(self, values: dict[str, str]) -> tuple[int, dict[str, Any]]:
        config = load_config(); transcription = config.transcription
        if "enabled" in values: transcription.enabled = _bool(values["enabled"])
        _set_if(values, "provider", transcription, "provider"); _set_if(values, "model", transcription, "model")
        if "language" in values: transcription.language = values["language"].strip() or None
        _set_int(values, "max_duration_sec", transcription, "max_duration_sec")
        _set_int(values, "max_upload_mb", transcription, "max_upload_mb")
        try:
            save_config(config)
        except (TypeError, ValueError) as exc:
            return 400, _error(str(exc))
        return 200, self.payload()

    def oauth(self, values: dict[str, str], *, login: bool) -> tuple[int, dict[str, Any]]:
        name = values.get("provider", "").strip()
        spec = find_by_name(name)
        if spec is None or not spec.is_oauth:
            return 400, _error("unknown OAuth provider")
        try:
            if name == "openai_codex":
                if login:
                    from oauth_cli_kit import get_token, login_oauth_interactive
                    config = load_config(); proxy = config.providers.openai_codex.proxy or None
                    token = get_token(proxy=proxy)
                    if not (token and token.access):
                        token = login_oauth_interactive(print_fn=lambda _message: None, prompt_fn=lambda _prompt: "", proxy=proxy)
                    if not (token and token.access): return 401, _error("OAuth login failed")
                else:
                    from oauth_cli_kit.providers import OPENAI_CODEX_PROVIDER
                    from oauth_cli_kit.storage import FileTokenStorage
                    token_path = FileTokenStorage(token_filename=OPENAI_CODEX_PROVIDER.token_filename).get_token_path()
                    for path in (token_path, token_path.with_suffix(".lock")):
                        with suppress(FileNotFoundError): path.unlink()
            elif name == "github_copilot":
                from nanobot.providers.github_copilot_provider import get_github_copilot_login_status, get_storage, login_github_copilot
                if login:
                    token = get_github_copilot_login_status() or login_github_copilot(print_fn=lambda _message: None)
                    if not (token and token.access): return 401, _error("OAuth login failed")
                else:
                    token_path = get_storage().get_token_path()
                    for path in (token_path, token_path.with_suffix(".lock")):
                        with suppress(FileNotFoundError): path.unlink()
            else:
                return 400, _error("OAuth provider is not supported")
        except ImportError:
            return 501, _error("OAuth support is not installed in this desktop runtime")
        except Exception:
            return 500, _error("OAuth action failed")
        return 200, self.payload()

    @staticmethod
    def usage() -> dict[str, Any]:
        # Direct runtime does not yet keep a gateway token-usage ledger.  Keep
        # the original Settings page functional with an explicit empty ledger.
        return {"days": [], "total_tokens": 0, "total_tokens_30d": 0,
                "total_tokens_365d": 0, "peak_day_tokens": 0,
                "current_streak_days": 0, "longest_streak_days": 0,
                "active_days_30d": 0, "requests_30d": 0, "updated_at": None}

    @staticmethod
    def version_check() -> dict[str, Any]:
        """Check on demand only; a network failure must not break Settings."""
        try:
            import httpx
            latest = httpx.get("https://pypi.org/pypi/nanobot-ai/json", timeout=5.0).json().get("info", {}).get("version")
        except Exception:
            latest = None
        update = ({"currentVersion": __version__, "latestVersion": latest,
                   "pypiUrl": "https://pypi.org/project/nanobot-ai/"}
                  if isinstance(latest, str) and latest and latest != __version__ else None)
        return {"updateAvailable": update}


def _hint(value: Any) -> str | None:
    return "已配置" if isinstance(value, str) and value else None

def _oauth_configured(name: str) -> bool:
    try:
        if name == "openai_codex":
            from oauth_cli_kit.providers import OPENAI_CODEX_PROVIDER
            from oauth_cli_kit.storage import FileTokenStorage
            token = FileTokenStorage(token_filename=OPENAI_CODEX_PROVIDER.token_filename).load()
        elif name == "github_copilot":
            from nanobot.providers.github_copilot_provider import get_github_copilot_login_status
            token = get_github_copilot_login_status()
        else: return False
        return bool(token and token.access)
    except Exception:
        return False

def _set_if(values: dict[str, str], key: str, target: Any, field: str) -> None:
    if key in values: setattr(target, field, values[key])

def _set_int(values: dict[str, str], key: str, target: Any, field: str) -> None:
    if key in values:
        try: setattr(target, field, int(values[key]))
        except ValueError: pass

def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}

def _preset_name(label: str) -> str:
    normalized = "".join(char.lower() if char.isalnum() else "-" for char in label)
    return normalized.strip("-")[:64]

def _error(message: str) -> dict[str, Any]:
    return {"error": {"code": "invalid_request", "message": message}}
