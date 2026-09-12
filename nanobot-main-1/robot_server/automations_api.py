"""Direct WebUI automation API backed by the local scheduler."""

from __future__ import annotations

import json
import urllib.parse
from typing import Any


class LocalAutomationService:
    """Expose existing local cron jobs without any gateway delivery context."""

    def __init__(self, runtime: Any | None) -> None:
        self._runtime = runtime

    def payload(self, session_key: str | None = None) -> tuple[int, dict[str, Any]]:
        cron = self._cron()
        if cron is None:
            return 200, {"jobs": []}
        jobs = cron.list_jobs(include_disabled=True)
        if session_key is not None:
            jobs = [job for job in jobs if job.payload.session_key == session_key]
        return 200, {"jobs": [_serialize(job) for job in jobs]}

    def action(self, action: str, job_id: str) -> tuple[int, dict[str, Any]]:
        cron = self._cron()
        if cron is None:
            return 503, _error("automation runtime is unavailable")
        if action == "enable": result = cron.enable_job(job_id, True)
        elif action == "disable": result = cron.enable_job(job_id, False)
        elif action == "delete":
            removed = cron.remove_job(job_id)
            if removed == "not_found": return 404, _error("automation not found")
            if removed == "protected": return 403, _error("system automation cannot be deleted")
            return self.payload()
        else: return 404, _error("unknown automation action")
        if result is None: return 404, _error("automation not found")
        return self.payload()

    async def run(self, job_id: str) -> tuple[int, dict[str, Any]]:
        cron = self._cron()
        if cron is None: return 503, _error("automation runtime is unavailable")
        if not await cron.run_job(job_id, force=True): return 404, _error("automation not found or cannot run")
        return self.payload()

    def update(self, job_id: str, values: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        cron = self._cron()
        if cron is None: return 503, _error("automation runtime is unavailable")
        job = next((row for row in cron.list_jobs(include_disabled=True) if row.id == job_id), None)
        if job is None: return 404, _error("automation not found")
        from nanobot.cron.types import CronSchedule
        schedule_data = values.get("schedule")
        schedule = None
        if isinstance(schedule_data, dict):
            try:
                schedule = CronSchedule(
                    kind=str(schedule_data.get("kind", job.schedule.kind)),
                    at_ms=_int_or_none(schedule_data.get("at_ms")),
                    every_ms=_int_or_none(schedule_data.get("every_ms")),
                    expr=_text_or_none(schedule_data.get("expr")),
                    tz=_text_or_none(schedule_data.get("tz")),
                )
            except (TypeError, ValueError) as exc:
                return 400, _error(str(exc))
        try:
            result = cron.update_job(job_id, name=_text_or_none(values.get("name")),
                                     message=_text_or_none(values.get("message")), schedule=schedule)
        except ValueError as exc:
            return 400, _error(str(exc))
        if isinstance(result, str): return (404 if result == "not_found" else 403), _error("automation cannot be updated")
        return self.payload()

    @staticmethod
    def values(header: str | None) -> dict[str, Any]:
        if not header: return {}
        try:
            result = json.loads(urllib.parse.unquote(header))
        except (json.JSONDecodeError, ValueError):
            return {}
        return result if isinstance(result, dict) else {}

    def _cron(self) -> Any | None:
        return getattr(self._runtime, "cron_service", None) if self._runtime is not None else None


def _serialize(job: Any) -> dict[str, Any]:
    return {"id": job.id, "name": job.name, "enabled": job.enabled,
            "schedule": {"kind": job.schedule.kind, "at_ms": job.schedule.at_ms,
                         "every_ms": job.schedule.every_ms, "expr": job.schedule.expr, "tz": job.schedule.tz},
            "payload": {"message": job.payload.message},
            "state": {"next_run_at_ms": job.state.next_run_at_ms,
                      "last_run_at_ms": job.state.last_run_at_ms, "last_status": job.state.last_status,
                      "last_error": job.state.last_error, "pending": False,
                      "run_history": [{"run_at_ms": item.run_at_ms, "status": item.status,
                                       "duration_ms": item.duration_ms, "error": item.error}
                                      for item in job.state.run_history[-5:]]},
            "protected": job.payload.kind == "system_event", "delete_after_run": job.delete_after_run,
            "created_at_ms": job.created_at_ms, "updated_at_ms": job.updated_at_ms,
            "origin": None}


def _text_or_none(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None

def _int_or_none(value: Any) -> int | None:
    try: return int(value) if value is not None else None
    except (TypeError, ValueError): return None

def _error(message: str) -> dict[str, Any]:
    return {"error": {"code": "invalid_request", "message": message}}
