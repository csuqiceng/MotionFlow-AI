"""The legacy ZMotion import path must remain a true module alias."""

from __future__ import annotations

import importlib


def test_legacy_operator_module_aliases_the_backend_adapter() -> None:
    legacy = importlib.import_module("robot_platform.zmotion_operator_control")
    adapter = importlib.import_module("robot_platform.backends.zmotion_adapter")

    assert legacy is adapter


def test_legacy_readonly_diagnostics_module_aliases_the_backend_adapter() -> None:
    legacy = importlib.import_module("robot_platform.zmotion_readonly_smoke")
    adapter = importlib.import_module("robot_platform.backends.zmotion_readonly_diagnostics")

    assert legacy is adapter
