"""Test fixtures for the robot_ai test suite."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_shared_zmotion_client():
    """Reset zmotion_shared_client module globals around every test.

    The shared client holds host/sdk_config/client/override at module scope. A
    test that enters shared mode (``create_robot_backend`` with
    ``ROBOT_AI_SHARED_CLIENT`` set, or a ``use_shared`` backend) must not leak
    that state into the next test — otherwise a later unit test could attempt a
    real ``ZAux_OpenEth`` to whatever host a prior test left behind. The
    shared-mode tests still do their own try/finally, but this is the safety net.
    """
    from robot_ai.backends import zmotion_shared_client as shared

    shared._reset_state_for_tests()  # noqa: SLF001 — test-only helper
    yield
    shared._reset_state_for_tests()  # noqa: SLF001
