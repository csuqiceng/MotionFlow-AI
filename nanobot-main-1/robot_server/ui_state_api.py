"""Local WebUI state services independent of gateway and chat channels."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from ai_runtime import AgentRuntime
from nanobot.agent.skills import SkillsLoader
from nanobot.config.loader import load_config
from robot_platform.library.storage import atomic_write_json
from robot_server.identity_api import RobotIdentityService


class LocalUiStateService:
    """Serve sidebar, session replay, skills and workspace state for this app."""

    def __init__(self, data_dir: Path, identity: RobotIdentityService, runtime: AgentRuntime | None) -> None:
        self._data_dir = data_dir
        self._identity = identity
        self._runtime = runtime

    def list_sessions(self, token: str) -> tuple[int, dict[str, Any]]:
        _session, error = self._identity.require_session(token)
        if error is not None:
            return error
        if self._runtime is None:
            return _unavailable("agent runtime is unavailable")
        rows = []
        for item in self._runtime.list_sessions():
            key = str(item.get("key", ""))
            if not key.startswith("robot-server:"):
                continue
            rows.append({
                "key": key,
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
                "title": item.get("title", ""),
                "preview": item.get("preview", ""),
            })
        rows.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return 200, {"sessions": rows}

    def thread(self, token: str, key: str) -> tuple[int, dict[str, Any]]:
        _session, error = self._identity.require_session(token)
        if error is not None:
            return error
        runtime, conversation_id, unavailable = self._conversation(key)
        if unavailable is not None:
            return unavailable
        source = runtime.read_session(conversation_id)
        if source is None:
            return 404, {"error": {"code": "not_found", "message": "session not found"}}
        messages = [
            message
            for index, item in enumerate(source.get("messages", []))
            if (message := _ui_message(item, index)) is not None
        ]
        return 200, {
            "schemaVersion": 1,
            "sessionKey": f"robot-server:{conversation_id}",
            "savedAt": source.get("updated_at"),
            "messages": messages,
            "page": {"has_more_before": False, "loaded_message_count": len(messages), "total_known_message_count": len(messages)},
        }

    async def delete_session(self, token: str, key: str) -> tuple[int, dict[str, Any]]:
        _session, error = self._identity.require_session(token)
        if error is not None:
            return error
        runtime, conversation_id, unavailable = self._conversation(key)
        if unavailable is not None:
            return unavailable
        result = await runtime.delete_conversation(conversation_id)
        result["sidebar_state_deleted"] = self._remove_sidebar_session_state(conversation_id)
        return 200, result

    def sidebar_state(self, token: str) -> tuple[int, dict[str, Any]]:
        return 200, self._read_sidebar()

    def update_sidebar_state(self, token: str, state: Any) -> tuple[int, dict[str, Any]]:
        if not isinstance(state, dict):
            return 400, {"error": {"code": "invalid_request", "message": "state must be an object"}}
        payload = _normalise_sidebar(state)
        payload["updated_at"] = datetime.now().isoformat()
        self._data_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self._data_dir / "sidebar_state.json", payload)
        return 200, payload

    def skills(self, token: str, name: str | None = None) -> tuple[int, dict[str, Any]]:
        config = load_config()
        loader = SkillsLoader(config.workspace_path, disabled_skills=set(config.agents.defaults.disabled_skills))
        available = {item["name"]: item for item in loader.list_skills(filter_unavailable=False)}
        if name is not None:
            item = available.get(name)
            raw = loader.load_skill(name) if item else None
            if item is None or raw is None:
                return 404, {"error": {"code": "not_found", "message": "skill not found"}}
            is_available, reason = loader.get_skill_availability(name)
            requirements = loader.get_skill_requirements(name)
            return 200, {
                "name": name,
                "description": _skill_description(raw),
                "source": item["source"],
                "available": is_available,
                "unavailable_reason": "" if is_available else reason,
                "requirements": requirements,
                "raw_markdown": raw,
            }
        rows = []
        for skill_name, item in available.items():
            raw = loader.load_skill(skill_name) or ""
            is_available, reason = loader.get_skill_availability(skill_name)
            row: dict[str, Any] = {
                "name": skill_name, "description": _skill_description(raw),
                "source": item["source"], "available": is_available,
            }
            if not is_available:
                row["unavailable_reason"] = reason
            rows.append(row)
        return 200, {"skills": sorted(rows, key=lambda item: item["name"])}

    def workspaces(self, token: str) -> tuple[int, dict[str, Any]]:
        config = load_config()
        workspace = config.workspace_path.resolve()
        restricted = bool(config.tools.restrict_to_workspace)
        return 200, {
            "schema_version": 1,
            "default_access_mode": "default" if restricted else "full",
            "default_scope": {
                "project_path": str(workspace), "project_name": workspace.name,
                "access_mode": "restricted" if restricted else "full",
                "restrict_to_workspace": restricted,
            },
            "controls": {"can_change_project": False, "can_use_full_access": not restricted},
        }

    def commands(self, token: str) -> tuple[int, dict[str, Any]]:
        return 200, {"commands": [
            {"command": "/status", "title": "机械手状态", "description": "查看机械手当前安全状态", "icon": "activity"},
            {"command": "/help", "title": "帮助", "description": "显示可用的机械手助手能力", "icon": "circle-help"},
        ]}

    def _conversation(self, key: str) -> tuple[AgentRuntime, str, tuple[int, dict[str, Any]] | None]:
        if self._runtime is None:
            return None, "", _unavailable("agent runtime is unavailable")  # type: ignore[return-value]
        if not isinstance(key, str):
            return self._runtime, "", (400, {"error": {"code": "invalid_session", "message": "invalid local session key"}})
        # ``websocket:`` was used only by the retained front-end's optimistic
        # rows.  Read/delete it as the same local conversation while clients
        # migrate to the canonical ``robot-server:`` key.
        for prefix in ("robot-server:", "websocket:"):
            conversation_id = key.removeprefix(prefix)
            if conversation_id != key and conversation_id.strip():
                return self._runtime, conversation_id, None
        return self._runtime, "", (400, {"error": {"code": "invalid_session", "message": "invalid local session key"}})

    def _read_sidebar(self) -> dict[str, Any]:
        path = self._data_dir / "sidebar_state.json"
        try:
            import json
            raw = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except Exception:
            raw = {}
        return _normalise_sidebar(raw)

    def _remove_sidebar_session_state(self, conversation_id: str) -> bool:
        """Purge saved UI metadata for both canonical and legacy local keys."""
        keys = {f"robot-server:{conversation_id}", f"websocket:{conversation_id}"}
        state = self._read_sidebar()
        changed = False
        for field in ("pinned_keys", "archived_keys"):
            original = state[field]
            retained = [key for key in original if key not in keys]
            if len(retained) != len(original):
                state[field] = retained
                changed = True
        for field in (
            "title_overrides",
            "project_name_overrides",
            "tags_by_key",
            "collapsed_groups",
        ):
            original = state[field]
            retained = {key: value for key, value in original.items() if key not in keys}
            if len(retained) != len(original):
                state[field] = retained
                changed = True
        if changed:
            state["updated_at"] = datetime.now().isoformat()
            self._data_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_json(self._data_dir / "sidebar_state.json", state)
        return changed


def _normalise_sidebar(value: Any) -> dict[str, Any]:
    value = value if isinstance(value, dict) else {}
    view = value.get("view") if isinstance(value.get("view"), dict) else {}
    return {
        "schema_version": 1,
        "pinned_keys": _string_list(value.get("pinned_keys")),
        "archived_keys": _string_list(value.get("archived_keys")),
        "title_overrides": _string_map(value.get("title_overrides")),
        "project_name_overrides": _string_map(value.get("project_name_overrides")),
        "tags_by_key": {key: _string_list(items) for key, items in _string_map_of_lists(value.get("tags_by_key")).items()},
        "collapsed_groups": {key: bool(item) for key, item in _bool_map(value.get("collapsed_groups")).items()},
        "view": {
            "density": view.get("density") if view.get("density") in {"comfortable", "compact"} else "comfortable",
            "show_previews": bool(view.get("show_previews", True)),
            "show_timestamps": bool(view.get("show_timestamps", True)),
            "show_archived": bool(view.get("show_archived", False)),
            "sort": view.get("sort") if view.get("sort") in {"updated_desc", "created_desc", "title_asc"} else "updated_desc",
        },
        "updated_at": value.get("updated_at") if isinstance(value.get("updated_at"), str) else None,
    }


def _ui_message(value: Any, index: int) -> dict[str, Any] | None:
    """Map persisted transcript messages to user-visible history rows.

    Tool calls/results and reasoning are execution internals.  During a live
    turn they are rendered as transient activity, never assistant prose; the
    replay path must apply the same boundary instead of exposing raw JSON.
    """
    value = value if isinstance(value, dict) else {}
    timestamp = value.get("timestamp")
    try:
        created_at = int(datetime.fromisoformat(str(timestamp)).timestamp() * 1000)
    except (TypeError, ValueError):
        created_at = 0
    role = value.get("role") if value.get("role") in {"user", "assistant"} else None
    if role is None:
        return None
    # The agent runner persists its brief pre-tool draft in the same assistant
    # record as the pending tool calls. It is execution scaffolding, not a
    # completed reply, so replay must hide it just like the tool result that
    # follows. Otherwise reopening a session reintroduces one assistant card
    # for every tool iteration of a single user request.
    if role == "assistant" and isinstance(value.get("tool_calls"), list) and value["tool_calls"]:
        return None
    content = value.get("content", "")
    content = content if isinstance(content, str) else str(content)
    if not content.strip():
        return None
    return {"id": f"replay-{index}", "role": role, "content": content, "createdAt": created_at}


def _skill_description(markdown: str) -> str:
    for line in markdown.splitlines():
        line = line.strip()
        if line and not line.startswith(("#", "---", "name:", "description:")):
            return line[:300]
    return ""


def _string_list(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _string_map(value: Any) -> dict[str, str]:
    return {key: item for key, item in value.items() if isinstance(key, str) and isinstance(item, str)} if isinstance(value, dict) else {}


def _string_map_of_lists(value: Any) -> dict[str, Any]:
    return {key: item for key, item in value.items() if isinstance(key, str)} if isinstance(value, dict) else {}


def _bool_map(value: Any) -> dict[str, bool]:
    return {key: item for key, item in value.items() if isinstance(key, str) and isinstance(item, bool)} if isinstance(value, dict) else {}


def _unavailable(message: str) -> tuple[int, dict[str, Any]]:
    return 503, {"error": {"code": "runtime_unavailable", "message": message}}
