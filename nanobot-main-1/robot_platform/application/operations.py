"""Vendor-neutral requests sent from robot use cases to an operation adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RobotOperationRequest:
    """A validated operation intent, independent of a controller SDK."""

    command: str
    parameters: dict[str, Any]
    execute_real: bool = False
    confirm_work_area_clear: bool = False
    confirm_estop_ready: bool = False
    confirmation_code: str = ""
    pending_plan_id: str = ""
    confirm_code: str = ""
