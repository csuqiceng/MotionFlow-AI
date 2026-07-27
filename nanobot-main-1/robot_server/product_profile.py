"""Engineer-only persisted selection of robot backend and enabled Tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ai_runtime.tool_manifest import ToolManifest
from robot_platform import _audit_append
from robot_platform.backends.factory import RobotBackendConfig
from robot_platform.backends.product_wiring import create_product_robot_backend
from robot_platform.library.storage import atomic_write_json
from robot_server.identity_api import RobotIdentityService
from robot_server.tool_registry import ToolRegistry


# Keep the server status endpoint on the same local ZMotion controller as the
# packaged Agent.  The previous simulation default caused the right panel to
# show zeroes/offline while chat independently reported real-device feedback.
_DEFAULT_PROFILE = {"backend_mode": "zmotion_readonly", "enabled_tools": ["robot_arm", "robot_flow", "robot_knowledge", "robot_position", "robot_library", "cron"]}
_BACKEND_MODES = ("simulation", "zmotion_readonly")
_TOOL_MANIFESTS = (
    ToolManifest("robot_arm", "1.0.0", required_capabilities=("state_read",), risk_level="motion"),
    ToolManifest("robot_flow", "1.0.0", required_capabilities=("state_read",), risk_level="motion"),
    ToolManifest("robot_knowledge", "1.0.0"),
    ToolManifest("robot_position", "1.0.0"),
    ToolManifest("robot_library", "1.0.0", risk_level="system"),
    ToolManifest("cron", "1.0.0", risk_level="system"),
)


def load_product_profile(data_dir: Path) -> dict[str, Any]:
    """Load the restart-applied, non-secret robot product profile.

    A missing profile follows the packaged ZMotion read-only connection. A malformed existing
    profile is deliberately rejected by callers so a failed edit cannot
    silently select a different controller on the next process start.
    """
    profile_path = data_dir / "product_profile.json"
    if not profile_path.is_file():
        return {
            "backend_mode": _DEFAULT_PROFILE["backend_mode"],
            "enabled_tools": list(_DEFAULT_PROFILE["enabled_tools"]),
        }
    import json

    try:
        raw = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("product profile is unreadable") from exc
    if not isinstance(raw, dict):
        raise ValueError("product profile must be an object")
    return {
        "backend_mode": _normalize_backend_mode(raw.get("backend_mode", _DEFAULT_PROFILE["backend_mode"])),
        "enabled_tools": _normalize_enabled_tools(raw.get("enabled_tools", _DEFAULT_PROFILE["enabled_tools"])),
    }


class ProductProfileService:
    """Own non-secret robot/Tool configuration for one product runtime."""

    def __init__(self, data_dir: Path, identity: RobotIdentityService) -> None:
        self._data_dir = data_dir
        self._profile_path = data_dir / "product_profile.json"
        self._audit_path = data_dir / "audit.jsonl"
        self._identity = identity
        self._tools = ToolRegistry()
        for manifest in _TOOL_MANIFESTS:
            self._tools.register(manifest)

    def get(self, token: str) -> tuple[int, dict[str, Any]]:
        session, error = self._identity.require_engineer_session(token)
        if error is not None:
            return error
        try:
            return 200, {"ok": True, "data": self._payload(self._read_profile())}
        except ValueError as exc:
            return 400, _error("invalid_profile", str(exc))

    def update(self, token: str, body: Any) -> tuple[int, dict[str, Any]]:
        session, error = self._identity.require_engineer_session(token)
        if error is not None:
            return error
        if not isinstance(body, dict):
            return 400, _error("invalid_profile", "request body must be an object")
        current = self._read_profile()
        try:
            candidate = {
                "backend_mode": _normalize_backend_mode(body.get("backend_mode", current["backend_mode"])),
                "enabled_tools": _normalize_enabled_tools(body.get("enabled_tools", current["enabled_tools"])),
            }
            payload = self._payload(candidate)
        except ValueError as exc:
            return 400, _error("invalid_profile", str(exc))
        self._data_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self._profile_path, candidate)
        _audit_append(
            self._audit_path,
            {
                "action": "product_profile_updated",
                "actor": f"user:{session['user_id']}",
                "actor_user_id": session["user_id"],
                "actor_username": session["username"],
                "actor_role": session["role"],
                "result": "success",
                "backend_mode": candidate["backend_mode"],
                "enabled_tools": candidate["enabled_tools"],
            },
        )
        return 200, {"ok": True, "data": payload}

    def _read_profile(self) -> dict[str, Any]:
        return load_product_profile(self._data_dir)

    def _payload(self, profile: dict[str, Any]) -> dict[str, Any]:
        backend = create_product_robot_backend(RobotBackendConfig(mode=profile["backend_mode"]))
        capabilities = backend.capabilities.to_public_dict()
        enabled_tools = set(profile["enabled_tools"])
        tools = []
        for manifest in self._tools.manifests:
            eligibility = self._tools.evaluate(
                manifest,
                capabilities=capabilities,
                role="engineer",
                enabled_tool_ids=enabled_tools,
            )
            tools.append(
                {
                    "tool_id": manifest.tool_id,
                    "version": manifest.version,
                    "risk_level": manifest.risk_level,
                    "required_capabilities": list(manifest.required_capabilities),
                    "enabled": manifest.tool_id in enabled_tools,
                    "eligible": eligibility.eligible,
                    "reason": eligibility.code or None,
                }
            )
        return {
            "protocol_version": 1,
            "backend_mode": profile["backend_mode"],
            "available_backend_modes": list(_BACKEND_MODES),
            "capabilities": capabilities,
            "tools": tools,
        }


def _normalize_backend_mode(value: Any) -> str:
    mode = str(value or "").strip().lower()
    aliases = {"sim": "simulation", "zreadonly": "zmotion_readonly", "real_readonly": "zmotion_readonly"}
    mode = aliases.get(mode, mode)
    if mode not in _BACKEND_MODES:
        raise ValueError(f"unsupported backend_mode: {mode}")
    return mode


def _normalize_enabled_tools(value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("enabled_tools must be a list of Tool IDs")
    known = {manifest.tool_id for manifest in _TOOL_MANIFESTS}
    selected = [item.strip() for item in value]
    unknown = sorted({item for item in selected if item not in known})
    if unknown:
        raise ValueError(f"unknown Tool IDs: {', '.join(unknown)}")
    return list(dict.fromkeys(selected))


def _error(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}
