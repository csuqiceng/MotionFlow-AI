from __future__ import annotations

from importlib.util import find_spec as _find_spec
from typing import Any, Callable


FindSpec = Callable[[str], Any]

_REQUIRED_DESKTOP_MODULES: tuple[str, ...] = ("pydantic", "loguru", "webview")
_OPTIONAL_VOICE_MODULES: tuple[str, ...] = ("edge_tts",)
_INSTALL_EXTRA = "robot-desktop"


def desktop_runtime_dependency_status(
    *,
    find_spec: FindSpec = _find_spec,
) -> dict[str, Any]:
    missing_required = [
        module for module in _REQUIRED_DESKTOP_MODULES if find_spec(module) is None
    ]
    missing_optional = [
        module for module in _OPTIONAL_VOICE_MODULES if find_spec(module) is None
    ]
    return {
        "ready": not missing_required,
        "missing_required": missing_required,
        "missing_optional": missing_optional,
        "install_extra": _INSTALL_EXTRA,
    }


def format_desktop_dependency_help(status: dict[str, Any]) -> str:
    missing_required = list(status.get("missing_required") or [])
    missing_optional = list(status.get("missing_optional") or [])
    if not missing_required and not missing_optional:
        raise RuntimeError("Desktop runtime dependencies are ready.")

    lines: list[str] = []
    if missing_required:
        lines.append(
            "Missing required desktop dependencies: " + ", ".join(missing_required)
        )
    if missing_optional:
        lines.append(
            "Missing optional voice dependencies: " + ", ".join(missing_optional)
        )
    install_extra = status.get("install_extra") or _INSTALL_EXTRA
    lines.append(f'Install them with: python -m pip install -e ".[{install_extra}]"')
    return "\n".join(lines)
