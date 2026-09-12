# Heartbeat Tasks

<!--
This file is checked periodically by the local robot service. When it starts with scheduler.heartbeat.enabled=true, it automatically registers a protected heartbeat task that reads this file.

Use this file for recurring background checks that should stay quiet unless there is something useful to report. Regular cron jobs are different: they normally deliver each run's result back to the chat/session where they were created.

If this file has no tasks (only headers and comments), the agent will skip it. Completed tasks should be deleted, not kept - heartbeat only reads "Active Tasks".
-->

## Active Tasks

<!-- Add your periodic tasks below this line -->

