"""Vendor-neutral requests sent from robot use cases to an operation adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from robot_platform.execution.permit import ExecutionScope


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
    execution_permit_handle: str = ""
    execution_scope: ExecutionScope | None = None
    execution_operation_type: str = ""
    execution_payload: dict[str, Any] | None = None
    execution_dispatch_id: str = ""
    emergency_stop_token: str = ""
