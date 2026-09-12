from __future__ import annotations

import pytest

from robot_platform import runtime


@pytest.fixture(autouse=True)
def isolated_robot_platform_runtime(tmp_path, monkeypatch):
    """Never let server tests depend on or mutate the user's live data root."""
    isolated = tmp_path / "robot_platform"
    monkeypatch.setenv("ROBOT_PLATFORM_DATA_DIR", str(isolated))
    with runtime._runtime_lock:
        previous = runtime._runtime_data_dir
        runtime._runtime_data_dir = isolated
    try:
        yield
    finally:
        with runtime._runtime_lock:
            runtime._runtime_data_dir = previous
