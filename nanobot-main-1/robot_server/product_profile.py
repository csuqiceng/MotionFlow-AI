"""Engineer-only persisted selection of robot backend and enabled Tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ai_runtime.tool_catalog import PRODUCT_TOOL_MANIFESTS
from ai_runtime.tool_registry import ToolRegistry
from robot_platform import _audit_append
from robot_platform.io_policy import normalize_io_output_channels
from robot_platform.library.storage import atomic_write_json
from robot_platform.models import ControllerCapabilities
from robot_server.identity_api import RobotIdentityService

_FIXED_BACKEND_MODE = "zmotion_readonly"
_BACKEND_MODES = (_FIXED_BACKEND_MODE,)
_BACKEND_CAPABILITIES = {
    "simulation": ControllerCapabilities(
        vendor="simulation", supports_real_writes=False,
        motion_primitives=("axis_move", "home", "stop"),
    ),
    "zmotion_readonly": ControllerCapabilities(
        vendor="zmotion", supports_real_writes=True,
        motion_primitives=("state_read", "system_action"),
    ),
}
_TOOL_MANIFESTS = PRODUCT_TOOL_MANIFESTS
_ALL_TOOL_IDS = tuple(manifest.tool_id for manifest in _TOOL_MANIFESTS)

# The packaged product always targets the real ZMotion controller and exposes
# every reviewed product Tool.  Execution safety is enforced by identity,
# precheck, confirmation, and one-shot permit layers rather than by a mutable
# UI allow-list.
_DEFAULT_PROFILE = {
    "backend_mode": _FIXED_BACKEND_MODE,
    "enabled_tools": list(_ALL_TOOL_IDS),
    "allowed_io_output_channels": [],
}


def load_product_profile(data_dir: Path) -> dict[str, Any]:
    """Load the restart-applied, non-secret robot product profile.

    A missing profile follows the packaged ZMotion connection. Legacy backend
    and Tool selections are migrated to the fixed product policy; malformed
    JSON and invalid IO policy remain fail-closed.
    """
    profile_path = data_dir / "product_profile.json"
    if not profile_path.is_file():
        return _default_profile()
    import json

    try:
        raw = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("product profile is unreadable") from exc
    if not isinstance(raw, dict):
        raise ValueError("product profile must be an object")
    canonical = {
        "backend_mode": _FIXED_BACKEND_MODE,
        "enabled_tools": list(_ALL_TOOL_IDS),
        "allowed_io_output_channels": list(normalize_io_output_channels(
            raw.get(
                "allowed_io_output_channels",
                _DEFAULT_PROFILE["allowed_io_output_channels"],
            )
        )),
    }
    if raw != canonical:
        atomic_write_json(profile_path, canonical)
    return canonical


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
            requested_backend = str(
                body.get("backend_mode", _FIXED_BACKEND_MODE) or ""
            ).strip().lower()
            requested_backend = {
                "zreadonly": _FIXED_BACKEND_MODE,
                "real_readonly": _FIXED_BACKEND_MODE,
            }.get(requested_backend, requested_backend)
            if requested_backend != _FIXED_BACKEND_MODE:
                return 409, _error(
                    "product_profile_fixed",
                    "The packaged product backend is fixed to zmotion_readonly.",
                )
            requested_tools = body.get("enabled_tools", list(_ALL_TOOL_IDS))
            normalized_tools = _normalize_enabled_tools(requested_tools)
            if (
                len(normalized_tools) != len(_ALL_TOOL_IDS)
                or set(normalized_tools) != set(_ALL_TOOL_IDS)
            ):
                return 409, _error(
                    "product_profile_fixed",
                    "All reviewed product Tools are always enabled.",
                )
            candidate = {
                "backend_mode": _FIXED_BACKEND_MODE,
                "enabled_tools": list(_ALL_TOOL_IDS),
                "allowed_io_output_channels": list(normalize_io_output_channels(
                    body.get(
                        "allowed_io_output_channels",
                        current["allowed_io_output_channels"],
                    )
                )),
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
                "allowed_io_output_channels": candidate["allowed_io_output_channels"],
            },
        )
        return 200, {"ok": True, "data": payload}

    def _read_profile(self) -> dict[str, Any]:
        return load_product_profile(self._data_dir)

    def _payload(self, profile: dict[str, Any]) -> dict[str, Any]:
        capabilities = _BACKEND_CAPABILITIES[profile["backend_mode"]].to_public_dict()
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
            "allowed_io_output_channels": list(
                profile["allowed_io_output_channels"]
            ),
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


def _default_profile() -> dict[str, Any]:
    return {
        "backend_mode": _FIXED_BACKEND_MODE,
        "enabled_tools": list(_ALL_TOOL_IDS),
        "allowed_io_output_channels": list(
            _DEFAULT_PROFILE["allowed_io_output_channels"]
        ),
    }


def _error(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}
