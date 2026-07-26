"""Deprecated compatibility alias for the robot runtime tool."""

from __future__ import annotations

import sys

from ai_runtime.robot_tools import robot_arm as _runtime


sys.modules[__name__] = _runtime
