# Agent Instructions

## Workspace Guidance

Use this file for project-specific preferences, recurring workflow conventions, and instructions you want the agent to remember for this workspace. Keep durable facts about the user in `USER.md`, personality/style guidance in `SOUL.md`, and long-term memory in `memory/MEMORY.md`.

## Scheduled Tasks

- Before scheduling reminders, check available skills and follow skill guidance first.
- Use the built-in `cron` tool to create/list/remove jobs (do not call `nanobot cron` via `exec`).
- Cron jobs run inside the local robot service. Do not use cron for background checks that should stay quiet unless there is something useful to report; use `HEARTBEAT.md` instead.

**Do NOT just write reminders to MEMORY.md** — that won't trigger actual notifications.

## Heartbeat Tasks

`HEARTBEAT.md` is checked periodically by the local scheduler when `scheduler.heartbeat.enabled` is true. Do not create a duplicate heartbeat job unless the user has disabled the built-in task and explicitly wants a custom schedule.

- Use `apply_patch` for normal task-list updates, especially when adding, removing, or changing multiple lines.
- Use `edit_file` only for small exact replacements copied from the current `HEARTBEAT.md`.
- Use `write_file` for first creation or intentional full-file rewrites.

When the user asks for a recurring/periodic heartbeat task, or for a periodic background check that should only notify on actionable changes, update `HEARTBEAT.md` instead of creating a one-time reminder. Use the built-in `cron` tool for explicit reminders, scheduled tasks that should report every run, or custom schedules that should not be part of the heartbeat task list.
