from __future__ import annotations

import pytest

from robot_ai.library.users import assert_unified_session_disabled


def test_unified_session_configuration_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="unified_session"):
        assert_unified_session_disabled(True)


def test_unified_session_configuration_is_allowed_when_disabled() -> None:
    assert_unified_session_disabled(False)


def test_unified_session_configuration_is_allowed_when_omitted() -> None:
    assert_unified_session_disabled(None)
