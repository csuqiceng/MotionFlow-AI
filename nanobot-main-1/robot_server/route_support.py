"""Shared protocol helpers for feature-owned aiohttp handlers."""

from __future__ import annotations

from typing import Any

from aiohttp import web

from robot_platform.application import AuthenticatedPrincipal
from robot_server.app_keys import (
    ROBOT_IDENTITY_SERVICE_KEY,
)


async def json_body(request: web.Request) -> Any:
    try:
        return await request.json()
    except Exception:
        return None


def robot_principal(
    request: web.Request,
) -> tuple[AuthenticatedPrincipal, None] | tuple[None, tuple[int, dict[str, Any]]]:
    return request.app[ROBOT_IDENTITY_SERVICE_KEY].require_principal(
        identity_token(request)
    )


def service_error_response(error: tuple[int, dict[str, Any]]) -> web.Response:
    status, result = error
    return web.json_response(result, status=status)


def identity_token(request: web.Request) -> str:
    return (
        request.headers.get("X-Nanobot-User-Token", "").strip()
        or request.headers.get("X-Robot-User-Token", "").strip()
    )
