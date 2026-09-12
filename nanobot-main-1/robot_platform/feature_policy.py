"""Product-wide capability policy shared by every execution entry point."""

from __future__ import annotations

from dataclasses import dataclass
from functools import wraps
from typing import Any


class FeatureDisabledError(PermissionError):
    pass


@dataclass(frozen=True)
class ProductFeaturePolicy:
    enabled_features: frozenset[str] | None = None

    @classmethod
    def from_enabled_tools(cls, tool_ids: list[str] | tuple[str, ...]) -> "ProductFeaturePolicy":
        return cls(frozenset(str(item).strip() for item in tool_ids if str(item).strip()))

    def require(self, feature_id: str) -> None:
        if self.enabled_features is not None and feature_id not in self.enabled_features:
            raise FeatureDisabledError(f"Product feature '{feature_id}' is disabled")

    def enabled(self, feature_id: str) -> bool:
        return self.enabled_features is None or feature_id in self.enabled_features

    def protect(self, feature_id: str, target: Any) -> "FeatureGatedPort":
        return FeatureGatedPort(self, feature_id, target)


class FeatureGatedPort:
    """Application-port decorator enforcing the product feature policy."""

    def __init__(self, policy: ProductFeaturePolicy, feature_id: str, target: Any) -> None:
        self._policy = policy
        self._feature_id = feature_id
        self._target = target

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._target, name)
        if not callable(attribute):
            return attribute

        @wraps(attribute)
        def guarded(*args: Any, **kwargs: Any) -> Any:
            self._policy.require(self._feature_id)
            return attribute(*args, **kwargs)

        return guarded
