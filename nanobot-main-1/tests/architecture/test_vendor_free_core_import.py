"""Importing the core must not eagerly load a controller vendor adapter."""

from __future__ import annotations

import subprocess
import sys


def test_importing_robot_platform_does_not_load_zmotion_modules() -> None:
    probe = """
import sys
import robot_platform
print(','.join(sorted(name for name in sys.modules if name.startswith('robot_platform.zmotion'))))
"""

    completed = subprocess.run(
        [sys.executable, "-c", probe],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout.strip() == ""
