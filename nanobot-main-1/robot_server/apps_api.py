"""Direct Settings APIs for installed CLI apps and local MCP configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from nanobot.apps.cli import CliAppError, CliAppManager, CliAppsRuntimeConfig
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import MCPServerConfig


@dataclass(frozen=True)
class _Preset:
    name: str
    display_name: str
    category: str
    description: str
    docs_url: str
    transport: str
    requires: str
    command: str = ""
    args: tuple[str, ...] = ()
    url: str = ""
    env: tuple[tuple[str, str], ...] = ()
    fields: tuple[tuple[str, str, str, str, bool], ...] = ()
    note: str = ""
    color: str = "#64748B"


# Keep the original WebUI's built-in catalog, but make it part of the local
# robot server rather than its former gateway package.  Tuple fields are
# (name, label, target-kind, target-key, required).
_PRESETS: tuple[_Preset, ...] = (
    _Preset("browserbase", "Browserbase", "browser", "Cloud browser automation through Browserbase's hosted MCP server.", "https://docs.browserbase.com/integrations/mcp/setup", "streamableHttp", "Browserbase API key", url="https://mcp.browserbase.com/mcp", fields=(("browserbase_api_key", "Browserbase API key", "url_param", "browserbaseApiKey", True),), color="#111827"),
    _Preset("playwright", "Playwright", "browser", "Local browser inspection and automation with Playwright's MCP server.", "https://playwright.dev/docs/getting-started-mcp", "stdio", "Node.js and npx", command="npx", args=("-y", "@playwright/mcp@latest"), color="#2EAD33"),
    _Preset("context7", "Context7", "docs", "Fetch current library docs and code examples while the agent works.", "https://context7.com/docs/resources/all-clients", "stdio", "Node.js and npx; API key optional", command="npx", args=("-y", "@upstash/context7-mcp@latest"), fields=(("context7_api_key", "Context7 API key", "arg", "--api-key", False),), note="Works without a key for basic public docs; add a key for higher limits or private docs.", color="#111827"),
    _Preset("firecrawl", "Firecrawl", "web", "Scrape, crawl, search, and extract web pages through Firecrawl's MCP server.", "https://docs.firecrawl.dev/use-cases/developers-mcp", "streamableHttp", "Network access", url="https://mcp.firecrawl.dev/v2/mcp", note="Hosted endpoint supports keyless basic access.", color="#EB5E28"),
    _Preset("exa", "Exa", "web", "Search the web and fetch clean page content through Exa's hosted MCP server.", "https://exa.ai/mcp", "streamableHttp", "Network access", url="https://mcp.exa.ai/mcp", note="Hosted endpoint currently supports keyless basic access.", color="#101010"),
    _Preset("microsoft-learn", "Microsoft Learn", "docs", "Search and fetch Microsoft Learn documentation through Microsoft's hosted MCP server.", "https://learn.microsoft.com/en-us/training/support/mcp", "streamableHttp", "Network access", url="https://learn.microsoft.com/api/mcp", note="Public documentation only; no authentication required.", color="#0078D4"),
    _Preset("aws-docs", "AWS Documentation", "docs", "Search AWS documentation and service guidance through AWS Labs' documentation MCP server.", "https://awslabs.github.io/mcp/servers/aws-documentation-mcp-server/", "stdio", "uvx", command="uvx", args=("awslabs.aws-documentation-mcp-server@latest",), env=(("FASTMCP_LOG_LEVEL", "ERROR"), ("AWS_DOCUMENTATION_PARTITION", "aws")), color="#FF9900"),
    _Preset("brave-search", "Brave Search", "web", "Run web, news, image, video, and local search through Brave Search.", "https://www.npmjs.com/package/@brave/brave-search-mcp-server", "stdio", "Node.js, npx, and Brave Search API key", command="npx", args=("-y", "@brave/brave-search-mcp-server@latest", "--transport", "stdio"), fields=(("brave_api_key", "Brave Search API key", "env", "BRAVE_API_KEY", True),), color="#FB542B"),
    _Preset("postman", "Postman", "api", "Inspect and manage Postman APIs, collections, and workspaces through the local MCP server.", "https://learning.postman.com/docs/developer/postman-api/postman-mcp-server/postman-mcp-local-server", "stdio", "Node.js, npx, and Postman API key", command="npx", args=("-y", "@postman/postman-mcp-server@latest", "--full"), fields=(("postman_api_key", "Postman API key", "env", "POSTMAN_API_KEY", True),), color="#FF6C37"),
    _Preset("figma", "Figma", "design", "Read design context from Figma using the local Dev Mode MCP server.", "https://help.figma.com/hc/en-us/articles/32132100833559-Guide-to-the-Figma-MCP-server", "streamableHttp", "Figma desktop app with MCP enabled", url="http://127.0.0.1:3845/mcp", note="Requires Figma Desktop Dev Mode MCP to be running locally.", color="#F24E1E"),
    _Preset("github", "GitHub", "code", "Repository, issue, and pull request workflows via GitHub's MCP server.", "https://github.com/github/github-mcp-server", "stdio", "Docker and GitHub token", command="docker", args=("run", "-i", "--rm", "-e", "GITHUB_PERSONAL_ACCESS_TOKEN", "ghcr.io/github/github-mcp-server"), fields=(("github_token", "GitHub token", "env", "GITHUB_PERSONAL_ACCESS_TOKEN", True),), color="#24292F"),
    _Preset("supabase", "Supabase", "database", "Inspect and manage Supabase projects through the Supabase MCP server.", "https://supabase.com/docs/guides/ai-tools/mcp", "stdio", "Node.js, npx, and Supabase access token", command="npx", args=("-y", "@supabase/mcp-server-supabase@latest", "--read-only"), fields=(("supabase_access_token", "Supabase access token", "env", "SUPABASE_ACCESS_TOKEN", True),), note="MVP config starts read-only by default.", color="#3ECF8E"),
)
_PRESET_BY_NAME = {preset.name: preset for preset in _PRESETS}


class LocalAppsService:
    def cli_payload(self, *, installed_only: bool = False) -> dict[str, Any]:
        manager = _cli_manager()
        return manager.installed_payload() if installed_only else manager.payload(cache_only=True)

    def cli_action(self, action: str, name: str) -> tuple[int, dict[str, Any]]:
        if not name.strip(): return 400, _error("missing CLI app name")
        manager = _cli_manager()
        try:
            result = getattr(manager, action)(name.strip())
        except (AttributeError, CliAppError) as exc:
            return getattr(exc, "status", 400), _error(str(exc))
        return 200, result

    def mcp_payload(self) -> dict[str, Any]:
        config = load_config()
        configured = config.tools.mcp_servers
        presets = [_preset_row(preset, configured.get(preset.name)) for preset in _PRESETS]
        presets.extend(_mcp_row(name, server) for name, server in configured.items() if name not in _PRESET_BY_NAME)
        return {"presets": presets, "installed_count": len(configured), "requires_restart": False}

    def mcp_action(self, action: str, name: str, values: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        config = load_config(); servers = config.tools.mcp_servers
        if action == "remove":
            if name not in servers: return 404, _error("MCP server not found")
            del servers[name]; save_config(config)
            return 200, self.mcp_payload()
        if action == "enable":
            server = servers.get(name)
            preset = _PRESET_BY_NAME.get(name)
            if server is None and preset is None: return 404, _error("MCP server not found")
            if server is None:
                server = _server_from_preset(preset, values)
                servers[name] = server
            server.enabled_tools = ["*"]; save_config(config)
            return 200, self.mcp_payload()
        if action == "tools":
            name = str(values.get("name") or name).strip()
            server = servers.get(name)
            enabled_tools = values.get("enabled_tools")
            if server is None: return 404, _error("MCP server not found")
            if not isinstance(enabled_tools, list) or not all(isinstance(item, str) for item in enabled_tools):
                return 400, _error("enabled_tools must be a list of strings")
            server.enabled_tools = enabled_tools or ["*"]; save_config(config)
            return 200, self.mcp_payload()
        if action in {"custom", "import"}:
            return self._save_custom(config, values, import_config=action == "import")
        if action == "test":
            if name not in servers: return 404, _error("MCP server not found")
            payload = self.mcp_payload(); payload["last_action"] = {"ok": True, "message": "Configuration saved; restart the robot service to test and load MCP tools."}
            return 200, payload
        return 404, _error("unknown MCP action")

    def _save_custom(self, config: Any, values: dict[str, Any], *, import_config: bool) -> tuple[int, dict[str, Any]]:
        if import_config:
            try: raw = json.loads(str(values.get("config") or "{}"))
            except json.JSONDecodeError: return 400, _error("invalid MCP JSON")
            candidates = raw.get("mcpServers", raw) if isinstance(raw, dict) else {}
            if not isinstance(candidates, dict): return 400, _error("MCP JSON must contain an object of servers")
            for name, item in candidates.items():
                if isinstance(name, str) and isinstance(item, dict):
                    _save_server(config.tools.mcp_servers, name, item)
        else:
            name = str(values.get("name") or "").strip()
            if not name: return 400, _error("MCP server name is required")
            _save_server(config.tools.mcp_servers, name, values)
        save_config(config)
        payload = self.mcp_payload(); payload["requires_restart"] = True
        return 200, payload


def _cli_manager() -> CliAppManager:
    config = load_config(); cli = config.tools.cli_apps
    return CliAppManager(workspace=config.workspace_path, runtime=CliAppsRuntimeConfig(
        install_timeout=cli.install_timeout, run_timeout=cli.run_timeout, catalog_ttl_seconds=cli.catalog_ttl_seconds,
    ))

def _save_server(servers: dict[str, MCPServerConfig], name: str, values: dict[str, Any]) -> None:
    transport = str(values.get("transport") or values.get("type") or "stdio")
    if transport not in {"stdio", "sse", "streamableHttp"}: raise ValueError("unsupported MCP transport")
    args = values.get("args", [])
    if isinstance(args, str): args = args.split()
    servers[name] = MCPServerConfig(type=transport, command=str(values.get("command") or ""),
                                    args=[str(item) for item in args] if isinstance(args, list) else [],
                                    url=str(values.get("url") or ""), cwd=str(values.get("cwd") or ""),
                                    enabled_tools=["*"])


def _server_from_preset(preset: _Preset, values: dict[str, Any]) -> MCPServerConfig:
    args = list(preset.args)
    env = dict(preset.env)
    url = preset.url
    for field_name, _label, target_kind, target_key, required in preset.fields:
        value = str(values.get(field_name) or "").strip()
        if required and not value:
            raise ValueError(f"{field_name} is required")
        if not value:
            continue
        if target_kind == "env":
            env[target_key] = value
        elif target_kind == "arg":
            args.extend((target_key, value))
        elif target_kind == "url_param":
            parts = urlsplit(url)
            query = dict(parse_qsl(parts.query, keep_blank_values=True)); query[target_key] = value
            url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    return MCPServerConfig(type=preset.transport, command=preset.command, args=args, url=url, env=env, enabled_tools=["*"])


def _preset_row(preset: _Preset, server: MCPServerConfig | None) -> dict[str, Any]:
    configured = server is not None
    fields = []
    for name, label, target_kind, target_key, required in preset.fields:
        field_configured = False
        if server is not None:
            if target_kind == "env": field_configured = bool(server.env.get(target_key))
            elif target_kind == "arg": field_configured = target_key in server.args
            elif target_kind == "url_param": field_configured = target_key in dict(parse_qsl(urlsplit(server.url).query))
        fields.append({"name": name, "label": label, "secret": True, "required": required,
                       "configured": field_configured, "placeholder": "", "env_var": target_key if target_kind == "env" else None})
    missing = any(field["required"] and not field["configured"] for field in fields)
    return {"name": preset.name, "display_name": preset.display_name, "category": preset.category,
            "description": preset.description, "docs_url": preset.docs_url, "transport": preset.transport,
            "requires": preset.requires, "note": preset.note, "install_supported": True,
            "installed": configured, "configured": configured and not missing, "available": True,
            "status": "configured" if configured and not missing else ("missing_credentials" if configured else "not_installed"),
            "logo_url": None, "brand_color": preset.color, "required_fields": fields,
            "connection_summary": (server.url or server.command) if server else preset.url or preset.command,
            "enabled_tools": server.enabled_tools if server else ["*"], "source": "preset"}

def _mcp_row(name: str, server: MCPServerConfig) -> dict[str, Any]:
    return {"name": name, "display_name": name, "category": "custom", "description": "Local MCP server configuration.",
            "docs_url": "", "transport": server.type or "stdio", "requires": "", "note": "Restart required after changes.",
            "install_supported": False, "installed": True, "configured": True, "available": True, "status": "configured",
            "required_fields": [], "connection_summary": server.url or server.command,
            "enabled_tools": server.enabled_tools, "source": "custom"}

def _error(message: str) -> dict[str, Any]:
    return {"error": {"code": "invalid_request", "message": message}}
