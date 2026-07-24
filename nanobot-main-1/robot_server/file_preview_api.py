"""Workspace-bound file preview for the retained WebUI."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlparse

from nanobot.config.loader import load_config
from nanobot.security.workspace_policy import WorkspaceBoundaryError, resolve_allowed_path

MAX_FILE_PREVIEW_BYTES = 384 * 1024


def file_preview(raw_path: str | None) -> tuple[int, dict[str, object]]:
    path = _clean_path(raw_path)
    if not path: return 400, _error("missing path")
    if len(path) > 4096: return 400, _error("path is too long")
    workspace = Path(load_config().workspace_path).expanduser().resolve(strict=False)
    try:
        resolved = resolve_allowed_path(path, workspace=workspace, allowed_root=workspace, strict=True)
    except FileNotFoundError: return 404, _error("file not found")
    except WorkspaceBoundaryError: return 403, _error("file is outside the current workspace")
    except OSError: return 400, _error("invalid path")
    if not resolved.is_file(): return 404, _error("file not found")
    try:
        with resolved.open("rb") as handle: raw = handle.read(MAX_FILE_PREVIEW_BYTES + 1)
    except OSError: return 500, _error("failed to read file")
    if b"\0" in raw[:4096]: return 415, _error("binary files cannot be previewed")
    relative = resolved.relative_to(workspace).as_posix()
    return 200, {"path": relative, "display_path": relative, "project_path": "workspace",
                 "language": _language(resolved), "content": raw[:MAX_FILE_PREVIEW_BYTES].decode("utf-8", errors="replace"),
                 "size": resolved.stat().st_size, "truncated": len(raw) > MAX_FILE_PREVIEW_BYTES}


def _clean_path(raw_path: str | None) -> str:
    value = unquote((raw_path or "").strip())
    if value.startswith("file://"):
        value = unquote(urlparse(value).path)
        if re.match(r"^/[A-Za-z]:[\\/]", value): value = value[1:]
    value = value.split("?", 1)[0].split("#", 1)[0].strip()
    return re.sub(r":\d+(?::\d+)?$", "", value) if not re.match(r"^[A-Za-z]:[\\/]", value) else value


def _language(path: Path) -> str:
    return {"py": "python", "ts": "typescript", "tsx": "typescript", "js": "javascript", "jsx": "jsx",
            "json": "json", "md": "markdown", "yaml": "yaml", "yml": "yaml", "toml": "toml",
            "sh": "bash", "css": "css", "html": "html"}.get(path.suffix.lower().lstrip("."), path.suffix.lstrip(".") or "text")


def _error(message: str) -> dict[str, object]:
    return {"error": {"code": "file_preview", "message": message}}
