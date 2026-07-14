"""Execution mode configuration — replaces the ROBOT_AI_LLM_DIRECT_EXECUTE env var.

Reads ``tools.execution_mode`` from ``~/.nanobot/config.json`` at import time.
Three modes:
  - ``dry_run_only``            — LLM tools never write to the controller (default).
  - ``auto_after_safety_check`` — safety check passes → execute directly (no manual confirm).
  - ``manual_confirm``          — LLM tools dry-run; real execution via /api/robot/* confirm chain.

In ``auto_after_safety_check`` mode, the L1 safety gate (bounds / alarm / estop /
limits) still applies — only the human-confirmation step is bypassed. If safety
fails, the command is rejected with a reason; the controller is never written.
"""

from __future__ import annotations

import json

VALID_MODES = frozenset({"dry_run_only", "auto_after_safety_check", "manual_confirm"})


def _load_execution_mode() -> str:
    from nanobot.config.loader import get_config_path

    config_path = get_config_path()
    if not config_path.exists():
        return "dry_run_only"
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        tools = cfg.get("tools", {})
        selected = tools.get("executionMode", tools.get("execution_mode", "dry_run_only"))
        mode = str(selected)
        return mode if mode in VALID_MODES else "dry_run_only"
    except Exception:
        return "dry_run_only"


EXECUTION_MODE: str = _load_execution_mode()

# Convenience flags for the tool layer.
AUTO_EXECUTE: bool = EXECUTION_MODE == "auto_after_safety_check"
MANUAL_CONFIRM: bool = EXECUTION_MODE == "manual_confirm"
