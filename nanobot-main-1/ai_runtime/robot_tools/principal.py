"""Translate the host-bound Agent turn identity into an Application principal."""

from robot_platform.application import AuthenticatedPrincipal
from robot_platform.runtime import (
    current_robot_request_session_key,
)
from ai_runtime.identity import current_verified_principal


def current_application_principal() -> AuthenticatedPrincipal:
    verified = current_verified_principal()
    if verified is None:
        return AuthenticatedPrincipal(
            actor_id="unknown", role="untrusted",
            session_id=current_robot_request_session_key() or "agent:untrusted",
            auth_source="agent-runtime-unverified",
        )
    return AuthenticatedPrincipal(
        actor_id=verified.actor_id,
        role=verified.role,
        session_id=verified.session_id,
        auth_source=verified.auth_source,
    )
