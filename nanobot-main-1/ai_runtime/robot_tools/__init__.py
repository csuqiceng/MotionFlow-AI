"""Robot product tools exposed through the SDK-neutral tool contract."""

from .loader import LegacyRobotToolAdapter, adapt_legacy_robot_tool

__all__ = ["LegacyRobotToolAdapter", "adapt_legacy_robot_tool"]
