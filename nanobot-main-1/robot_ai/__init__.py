"""Deprecated import compatibility for :mod:`robot_platform`.

New code must import ``robot_platform``.  This finder maps old submodule
imports to the already-canonical module object, preventing duplicate runtime
singletons during the deployment migration window.
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import sys

import robot_platform as _platform

__all__ = _platform.__all__


def __getattr__(name: str):
    return getattr(_platform, name)


class _LegacyModuleLoader(importlib.abc.Loader):
    def __init__(self, target: str) -> None:
        self._target = target
        self._canonical_metadata: dict[str, object] = {}

    def create_module(self, spec):
        module = importlib.import_module(self._target)
        self._canonical_metadata = {
            key: getattr(module, key)
            for key in ("__name__", "__package__", "__spec__", "__loader__", "__file__", "__path__")
            if hasattr(module, key)
        }
        sys.modules[spec.name] = module
        return module

    def exec_module(self, module) -> None:
        # Import machinery assigns the legacy spec before this hook. Restore
        # the canonical metadata so importlib.resources continues to locate
        # packaged platform assets through ``robot_platform``.
        for key, value in self._canonical_metadata.items():
            setattr(module, key, value)
        return None


class _LegacyModuleFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path=None, target=None):
        if not fullname.startswith("robot_ai."):
            return None
        canonical = "robot_platform." + fullname.removeprefix("robot_ai.")
        return importlib.machinery.ModuleSpec(fullname, _LegacyModuleLoader(canonical))


if not any(isinstance(finder, _LegacyModuleFinder) for finder in sys.meta_path):
    sys.meta_path.insert(0, _LegacyModuleFinder())
