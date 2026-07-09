"""Execution mode configuration — replaces the ROBOT_AI_LLM_DIRECT_EXECUTE env var.

Reads ``robot_ai.execution_mode`` from ``~/.nanobot/config.json`` at import time.
Three modes:
  - ``dry_run_only``         — LLM tools never write to the controller (default).
  - ``auto_after_safety_check`` — safety check passes → execute directly (no manual confirm).
  ``manual_confirm``         — LLM tools dry-run; real execution via /api/robot/* confirm chain.

In ``auto_after_safety_check`` mode, the L1 safety gate (bounds / alarm / estop /
limits) still applies — only the human-confirmation step is bypassed. If safety
fails, the command is rejected with a reason; the controller is never written.
"""

from __future__ import annotations

import json
from pathlib import Path

VALID_MODES = frozenset({"dry_run_only", "auto_after_safety_check", "manual_confirm"})


def _load_execution_mode() -> str:
    config_path = Path.home() / ".nanobot" / "config.json"
    if not config_path.exists():
        return "dry_run_only"
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        mode = str(cfg.get("robot_ai", {}).get("execution_mode", "dry_run_only"))
        return mode if mode in VALID_MODES else "dry_run_only"
    except Exception:
        return "dry_run_only"


EXECUTION_MODE: str = _load_execution_mode()

# Convenience flags for the tool layer.
AUTO_EXECUTE: bool = EXECUTION_MODE == "auto_after_safety_check"
MANUAL_CONFIRM: bool = EXECUTION_MODE == "manual_confirm"
