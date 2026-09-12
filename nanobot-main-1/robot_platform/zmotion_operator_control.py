"""Deprecated compatibility alias for the ZMotion backend adapter.

New product wiring must import :mod:`robot_platform.backends.zmotion_adapter`.
Replacing this module object (rather than re-exporting names) preserves the
legacy test and extension behaviour that monkeypatches adapter-level stores.
"""

from __future__ import annotations

import sys

from robot_platform.backends import zmotion_adapter as _adapter


sys.modules[__name__] = _adapter
