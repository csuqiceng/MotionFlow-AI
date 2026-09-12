"""Execution mode configuration — replaces the ROBOT_AI_LLM_DIRECT_EXECUTE env var.

The host injects ``tools.execution_mode`` at startup. The robot platform never
reads a nanobot configuration file itself.
Three modes:
  - ``dry_run_only``            — LLM tools never write to the controller (default).
  - ``auto_after_safety_check`` — safety check passes → execute directly (no manual confirm).
  - ``manual_confirm``          — LLM tools dry-run; real execution via /api/robot/* confirm chain.

In ``auto_after_safety_check`` mode, the L1 safety gate (bounds / alarm / estop /
limits) still applies — only the human-confirmation step is bypassed. If safety
fails, the command is rejected with a reason; the controller is never written.
"""

from __future__ import annotations

from robot_platform.runtime import get_robot_execution_mode

VALID_MODES = frozenset({"dry_run_only", "auto_after_safety_check", "manual_confirm"})


def _load_execution_mode() -> str:
    mode = get_robot_execution_mode()
    return mode if mode in VALID_MODES else "dry_run_only"


def configure_execution_mode(value: str | None) -> None:
    """Refresh compatibility constants after a host configuration reload."""
    global EXECUTION_MODE, AUTO_EXECUTE, MANUAL_CONFIRM
    EXECUTION_MODE = value if value in VALID_MODES else "dry_run_only"
    AUTO_EXECUTE = EXECUTION_MODE == "auto_after_safety_check"
    MANUAL_CONFIRM = EXECUTION_MODE == "manual_confirm"


EXECUTION_MODE: str = _load_execution_mode()

# Convenience flags for the tool layer.
AUTO_EXECUTE: bool = EXECUTION_MODE == "auto_after_safety_check"
MANUAL_CONFIRM: bool = EXECUTION_MODE == "manual_confirm"
