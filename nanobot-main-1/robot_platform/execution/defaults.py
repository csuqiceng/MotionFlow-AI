"""Process-local default stores shared by application and adapter layers."""

from __future__ import annotations

from robot_platform.execution.pending_plan import PendingPlanStore
from robot_platform.execution.session_gate import SessionGateStore


PENDING_PLAN_STORE = PendingPlanStore()
SESSION_GATE_STORE = SessionGateStore()
