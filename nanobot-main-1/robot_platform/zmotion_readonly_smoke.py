"""Deprecated compatibility alias for the ZMotion readonly diagnostics adapter."""

from __future__ import annotations

import sys

from robot_platform.backends import zmotion_readonly_diagnostics as _adapter


sys.modules[__name__] = _adapter
