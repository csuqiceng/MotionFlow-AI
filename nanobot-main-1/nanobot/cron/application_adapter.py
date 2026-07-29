"""Scheduler service adapter behind the neutral Cron Application port."""

from __future__ import annotations

from typing import Any

from nanobot.cron.application import (
    CronApplicationPort, CronJobStateView, CronJobView, CronRemovalResult,
    CronScheduleSpec,
)
from nanobot.cron.types import CronSchedule


class NanobotCronApplicationAdapter(CronApplicationPort):
    def __init__(self, service: Any) -> None:
        self._service = service

    def add_job(self, **kwargs: Any) -> CronJobView:
        spec = kwargs.pop("schedule")
        job = self._service.add_job(
            schedule=CronSchedule(
                kind=spec.kind, every_ms=spec.every_ms, expr=spec.expr,
                tz=spec.tz, at_ms=spec.at_ms,
            ),
            **kwargs,
        )
        return _view(job)

    def list_jobs(self) -> tuple[CronJobView, ...]:
        return tuple(_view(job) for job in self._service.list_jobs())

    def remove_job(self, job_id: str) -> CronRemovalResult:
        status = str(self._service.remove_job(job_id))
        name = ""
        if status == "protected":
            job = self._service.get_job(job_id)
            name = str(getattr(job, "name", "")) if job is not None else ""
        return CronRemovalResult(status, name)


def _view(job: Any) -> CronJobView:
    schedule = job.schedule
    state = job.state
    return CronJobView(
        job_id=str(job.id), name=str(job.name),
        schedule=CronScheduleSpec(
            kind=str(schedule.kind), every_ms=schedule.every_ms,
            expr=schedule.expr, tz=schedule.tz, at_ms=schedule.at_ms,
        ),
        state=CronJobStateView(
            last_run_at_ms=state.last_run_at_ms,
            last_status=state.last_status, last_error=state.last_error,
            next_run_at_ms=state.next_run_at_ms,
        ),
        payload_kind=str(job.payload.kind),
    )
