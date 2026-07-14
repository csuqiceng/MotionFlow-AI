"""Session namespace helpers for multi-user isolation (slice ②).

namespace = "{role}:{user_id}", stored in session.metadata["namespace"].
Server-derived only; never trusted from clients.
"""
from __future__ import annotations

_VALID_ROLES = ("operator", "engineer")


class SessionNotAvailableError(Exception):
    """Session absent OR not owned by caller's namespace. Uniformly REST 404 /
    WS session_not_available (no existence leak)."""


class NamespaceAlreadyBoundError(ValueError):
    """Session already bound to a different namespace (stamp_namespace guard).
    Only a future audited claim/migration tool may reassign ownership."""


def derive_namespace(role: str, user_id: str) -> str:
    if role not in _VALID_ROLES:
        raise ValueError(f"Invalid role {role!r}; must be one of {_VALID_ROLES}.")
    if not user_id:
        raise ValueError("user_id must not be empty.")
    return f"{role}:{user_id}"
