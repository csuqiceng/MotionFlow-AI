"""Local signed-media endpoint for the retained WebUI."""

from __future__ import annotations

import base64
import hashlib
import hmac
import mimetypes
import secrets
from pathlib import Path

from aiohttp import web

from nanobot.config.paths import get_media_dir

_ALLOWED = {"image/png", "image/jpeg", "image/webp", "image/gif", "image/svg+xml", "video/mp4", "video/webm", "video/quicktime"}


class LocalMediaService:
    """Issue and validate opaque media URLs rooted in the local media folder."""

    def __init__(self) -> None:
        self._secret = secrets.token_bytes(32)

    def sign(self, path: Path) -> str | None:
        try: relative = path.resolve().relative_to(get_media_dir().resolve())
        except (OSError, ValueError): return None
        payload = _b64(relative.as_posix().encode("utf-8"))
        return f"/api/media/{_b64(hmac.new(self._secret, payload.encode(), hashlib.sha256).digest()[:16])}/{payload}"

    def response(self, signature: str, payload: str, request: web.Request) -> web.Response:
        try:
            provided = _unb64(signature)
            expected = hmac.new(self._secret, payload.encode(), hashlib.sha256).digest()[:16]
            relative = _unb64(payload).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return web.json_response({"error": "invalid media URL"}, status=401)
        if not hmac.compare_digest(provided, expected):
            return web.json_response({"error": "invalid media URL"}, status=401)
        root = get_media_dir().resolve()
        try: candidate = (root / relative).resolve(); candidate.relative_to(root)
        except (OSError, ValueError): return web.json_response({"error": "media not found"}, status=404)
        if not candidate.is_file(): return web.json_response({"error": "media not found"}, status=404)
        try: data = candidate.read_bytes()
        except OSError: return web.json_response({"error": "media read failed"}, status=500)
        mime = mimetypes.guess_type(candidate.name)[0]
        mime = mime if mime in _ALLOWED else "application/octet-stream"
        headers = {"Cache-Control": "private, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"}
        if mime == "image/svg+xml": headers["Content-Security-Policy"] = "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; sandbox"
        return web.Response(body=data, content_type=mime, headers=headers)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
