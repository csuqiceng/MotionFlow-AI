"""SDK-neutral Application contracts for scheduled desktop work."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class CronScheduleSpec:
    kind: str
    every_ms: int | None = None
    expr: str | None = None
    tz: str | None = None
    at_ms: int | None = None


@dataclass(frozen=True)
class CronJobStateView:
    last_run_at_ms: int | None = None
    last_status: str | None = None
    last_error: str | None = None
    next_run_at_ms: int | None = None


@dataclass(frozen=True)
class CronJobView:
    job_id: str
    name: str
    schedule: CronScheduleSpec
    state: CronJobStateView = field(default_factory=CronJobStateView)
    payload_kind: str = "agent_turn"


@dataclass(frozen=True)
class CronRemovalResult:
    status: str
    job_name: str = ""


class CronApplicationPort(Protocol):
    def add_job(
        self, *, name: str, schedule: CronScheduleSpec, message: str,
        delete_after_run: bool, session_key: str, origin_channel: str,
        origin_chat_id: str, origin_metadata: dict[str, Any],
    ) -> CronJobView: ...
    def list_jobs(self) -> tuple[CronJobView, ...]: ...
    def remove_job(self, job_id: str) -> CronRemovalResult: ...
