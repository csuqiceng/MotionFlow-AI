from __future__ import annotations

import pytest

from ai_runtime.identity import bind_verified_principal, issue_verified_principal


@pytest.fixture(autouse=True)
def verified_robot_tool_turn():
    """Direct Tool unit tests run under an explicitly verified host identity."""
    principal = issue_verified_principal(
        actor_id="robot-ai-test",
        role="engineer",
        session_id="robot-ai-test-session",
        auth_source="pytest-host-adapter",
    )
    from robot_platform.backends import zmotion_shared_client

    zmotion_shared_client._reset_state_for_tests()
    try:
        with bind_verified_principal(principal):
            yield
    finally:
        zmotion_shared_client._reset_state_for_tests()
