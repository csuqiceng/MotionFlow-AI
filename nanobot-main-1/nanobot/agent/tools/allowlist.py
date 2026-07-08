"""Pure tool-allowlist check, free of nanobot runtime deps so it unit-tests cleanly."""
from __future__ import annotations


def tool_allowed(tool_name: str, enabled_tools: list[str]) -> bool:
    """True if the tool may register under the given enabled_tools list.

    ["*"] (or list containing "*") = allow all; otherwise only listed names.
    """
    if not enabled_tools:
        return False
    if "*" in enabled_tools:
        return True
    return tool_name in enabled_tools
