# Engineer Backend Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** Bring the Web engineer backend to legacy Qt parity for command/flow operations, execution control, controller diagnostics, and logs, excluding system/safety configuration and AI/voice.

**Architecture:** Extend the JSON-backed command/flow registries through the existing route and WebSocket layers. Replace the ephemeral-only execution registry with persisted records and cooperative control checkpoints; build focused React panels instead of JSON editing.

**Tech Stack:** Python 3.11, aiohttp/WebSocket gateway, React, TypeScript, pytest, Vitest.

---

## Scope and acceptance criteria

Included: command/flow create-edit-publish-archive, duplicate, batch archive, import/export, read-only structured preview; flow run, single-step, pause, resume, stop, reset, live progress and history; controller connection/position/IO/task/echo diagnostics; filtered/exportable/clearable engineer logs.

Excluded: global motion/safety settings, safety middle-points/policy, AI and voice.

Completion evidence: backend pytest covers each route/state transition; Vitest covers UI and polling errors; browser uses disposable data and never issues a motion command.

## Existing implementation anchors

- \`nanobot-main-1/nanobot/api/robot_routes.py\`: library routes and handlers.
- \`nanobot-main-1/nanobot/webui/ws_http.py\`: gateway dispatcher.
- \`nanobot-main-1/robot_ai/flow/execution_registry.py\`: current in-memory status.
- \`nanobot-main-1/robot_ai/flow/executor.py\`: real step callback boundary.
- \`nanobot-main-1/webui/src/lib/robot-library-api.ts\`: DTOs and browser client.
- \`nanobot-main-1/webui/src/robot/workbench/EngineerWorkbench.tsx\`: main engineer workspace.
- \`nanobot-main-1/webui/src/robot/components/RobotSidePanel.tsx\`: current status source.

### Task 1: Persist and control executions

**Files:**
- Create: \`nanobot-main-1/robot_ai/flow/execution_history.py\`
- Modify: \`nanobot-main-1/robot_ai/flow/execution_registry.py\`
- Modify: \`nanobot-main-1/robot_ai/flow/executor.py\`
- Test: \`nanobot-main-1/tests/robot_ai/test_flow_executor.py\`
- Test: \`nanobot-main-1/tests/robot_ai/test_robot_library_routes.py\`

- [ ] **Step 1: Write failing state/history tests**

\`\`\`python
def test_execution_history_survives_registry_reload(tmp_path):
    history = ExecutionHistory(tmp_path / "history.json")
    execution_id = history.create(kind="flow", source_id="delay-flow", step_count=2)
    history.mark_step(execution_id, 1, "succeeded", {"ok": True})
    history.finish(execution_id, "completed", {"ok": True})
    assert ExecutionHistory(tmp_path / "history.json").get(execution_id)["state"] == "completed"
\`\`\`

- [ ] **Step 2: Implement bounded JSON history**

Persist ID, kind, source, actor/session, timestamps, state, allowed controls, per-step result, final result and error. Bound the retained records to 1,000.

- [ ] **Step 3: Add cooperative executor checkpoints**

Before every real step, wait when paused; return a structured cancelled result when stopped; execute one step then pause when single-step is requested. Dry-run must not mutate a record.

- [ ] **Step 4: Add control API tests and implementation**

Implement \`pause\`, \`resume\`, \`step_once\`, \`stop\`, \`reset\`, \`list\`, \`get\`; invalid transitions return 409 and unknown IDs return 404.

- [ ] **Step 5: Verify and commit**

\`\`\`powershell
C:\\Users\\KY\\.venvs\\robot_modbus_311\\Scripts\\python.exe -m pytest tests\\robot_ai\\test_flow_executor.py tests\\robot_ai\\test_robot_library_routes.py -q
git add nanobot-main-1/robot_ai/flow nanobot-main-1/tests/robot_ai
git commit -m "feat: persist and control library executions"
\`\`\`

### Task 2: Add routes and live execution monitor

**Files:**
- Modify: \`nanobot-main-1/nanobot/api/robot_routes.py\`
- Modify: \`nanobot-main-1/nanobot/webui/ws_http.py\`
- Modify: \`nanobot-main-1/webui/src/lib/robot-library-api.ts\`
- Create: \`nanobot-main-1/webui/src/robot/workbench/ExecutionMonitor.tsx\`
- Modify: \`nanobot-main-1/webui/src/robot/workbench/ExecutionTimeline.tsx\`
- Modify: \`nanobot-main-1/webui/src/robot/workbench/EngineerWorkbench.tsx\`
- Test: \`nanobot-main-1/webui/src/tests/engineer-workbench.test.tsx\`

- [ ] **Step 1: Write failing route/client tests**

Cover list/detail plus \`POST /api/robot/library/executions/{id}/pause|resume|step|stop|reset\`, ownership checks, and client POST bodies.

- [ ] **Step 2: Implement route processors and WebSocket dispatch**

Keep existing GET status compatible. Return the full execution record after each action.

- [ ] **Step 3: Build execution monitor**

Show allowed controls based only on server state, live timeline, selected historic record and filters. Poll only queued/running/paused records and stop polling on unmount.

- [ ] **Step 4: Verify and commit**

\`\`\`powershell
npm.cmd test -- --run src/tests/engineer-workbench.test.tsx src/tests/robot-library-api.test.ts
npm.cmd run build
git commit -am "feat: monitor and control library executions"
\`\`\`

### Task 3: Implement duplicate, bulk archive, import, export, and preview

**Files:**
- Create: \`nanobot-main-1/robot_ai/library/transfer.py\`
- Modify: \`nanobot-main-1/nanobot/api/robot_routes.py\`
- Modify: \`nanobot-main-1/nanobot/webui/ws_http.py\`
- Create: \`nanobot-main-1/webui/src/robot/workbench/LibraryTransferDialog.tsx\`
- Create: \`nanobot-main-1/webui/src/robot/workbench/LibraryPreview.tsx\`
- Modify: \`nanobot-main-1/webui/src/lib/engineer-workbench-api.ts\`
- Modify: \`nanobot-main-1/webui/src/robot/workbench/EngineerWorkbench.tsx\`
- Test: \`nanobot-main-1/tests/robot_ai/test_robot_library_routes.py\`
- Test: \`nanobot-main-1/webui/src/tests/engineer-workbench.test.tsx\`

- [ ] **Step 1: Define failing transfer tests**

\`\`\`json
{"schema_version":1,"exported_at":"2026-07-14T00:00:00Z","commands":[],"flows":[]}
\`\`\`

Test invalid schema, duplicate ID/name, unknown component, invalid flow step, and import strategies: skip, rename, overwrite-draft-only.

- [ ] **Step 2: Implement pure transfer validation**

Published entries are never silently overwritten; every import returns per-entry success/failure results.

- [ ] **Step 3: Implement protected APIs**

Add engineer-only export/import, duplicate, and bulk-archive endpoints. Archive response returns successful and failed IDs.

- [ ] **Step 4: Implement UI**

Engineer list gets multi-select and actions: 另存为, 批量归档, 导入, 导出, 结构预览. Import displays its report and export downloads JSON. Preview is read-only.

- [ ] **Step 5: Verify and commit**

\`\`\`powershell
C:\\Users\\KY\\.venvs\\robot_modbus_311\\Scripts\\python.exe -m pytest tests\\robot_ai\\test_robot_library_routes.py -q
npm.cmd test -- --run src/tests/engineer-workbench.test.tsx
npm.cmd run build
git commit -am "feat: add library transfer and batch management"
\`\`\`

### Task 4: Cover legacy command families with forms

**Files:**
- Modify: \`nanobot-main-1/robot_ai/library/catalog.py\`
- Modify: \`nanobot-main-1/webui/src/robot/workbench/CommandDraftEditor.tsx\`
- Test: \`nanobot-main-1/tests/robot_ai/test_robot_library_routes.py\`
- Test: \`nanobot-main-1/webui/src/tests/engineer-workbench.test.tsx\`

- [ ] **Step 1: Write a legacy-to-catalog test matrix**

Test emergency/system, joint/linear/relative motion, delay, IO, named position and multi-point/table path component fields. Every field must be typed, constrained and documented.

- [ ] **Step 2: Add only verified controller components**

Use grouped parameter controls and an add/remove/reorder point editor for path data, never a JSON textbox. Do not expose global safety settings.

- [ ] **Step 3: Verify and commit**

\`\`\`powershell
npm.cmd test -- --run src/tests/engineer-workbench.test.tsx
C:\\Users\\KY\\.venvs\\robot_modbus_311\\Scripts\\python.exe -m pytest tests\\robot_ai\\test_robot_library_routes.py -q
git commit -am "feat: expand engineer command forms"
\`\`\`

### Task 5: Add read-only controller diagnostics

**Files:**
- Create: \`nanobot-main-1/webui/src/robot/workbench/ControllerDiagnostics.tsx\`
- Modify: \`nanobot-main-1/nanobot/api/robot_routes.py\`
- Modify: \`nanobot-main-1/nanobot/webui/ws_http.py\`
- Modify: \`nanobot-main-1/webui/src/lib/robot-library-api.ts\`
- Modify: \`nanobot-main-1/webui/src/robot/workbench/EngineerWorkbench.tsx\`
- Test: \`nanobot-main-1/tests/robot_ai/test_robot_routes.py\`
- Test: \`nanobot-main-1/webui/src/tests/engineer-workbench.test.tsx\`

- [ ] **Step 1: Write failing diagnostic snapshot tests**

The snapshot contains connection mode/address, health, position, IO, alarm, task state and command echo. Unavailable values are explicit \`null\` or \`unavailable\`; no value is fabricated.

- [ ] **Step 2: Implement read-only endpoint and panel**

Add \`GET /api/robot/diagnostics\`; add reconnect only when current backend offers an idempotent test operation. Render connection status, refresh, position/IO/task/echo tables and copyable snapshot; no movement action is added.

- [ ] **Step 3: Verify and commit**

\`\`\`powershell
C:\\Users\\KY\\.venvs\\robot_modbus_311\\Scripts\\python.exe -m pytest tests\\robot_ai\\test_robot_routes.py -q
npm.cmd test -- --run src/tests/engineer-workbench.test.tsx
git commit -am "feat: add engineer controller diagnostics"
\`\`\`

### Task 6: Build execution and operation log centre

**Files:**
- Create: \`nanobot-main-1/robot_ai/logging/engineer_log_store.py\`
- Create: \`nanobot-main-1/webui/src/robot/workbench/EngineerLogCenter.tsx\`
- Modify: \`nanobot-main-1/nanobot/api/robot_routes.py\`
- Modify: \`nanobot-main-1/nanobot/webui/ws_http.py\`
- Modify: \`nanobot-main-1/webui/src/lib/robot-library-api.ts\`
- Modify: \`nanobot-main-1/webui/src/robot/workbench/EngineerWorkbench.tsx\`
- Test: \`nanobot-main-1/tests/robot_ai/test_robot_library_routes.py\`
- Test: \`nanobot-main-1/webui/src/tests/engineer-workbench.test.tsx\`

- [ ] **Step 1: Define and test canonical log records**

Record timestamp, severity, category, actor, session/execution/source ID, message and safe structured details. Cover date/category/severity/session filters, pagination, CSV/JSON export and confirmed clear.

- [ ] **Step 2: Emit logs and expose routes**

Emit records for library lifecycle and execution operations; redact passwords/tokens. Add list, export and \`POST clear {confirm:true}\` endpoints. After clearing, write a fresh clear-operation record.

- [ ] **Step 3: Build UI and verify**

Implement filters, table, detail drawer, refresh/export and confirmed destructive clear. It is engineer-only and independent of chat history.

\`\`\`powershell
C:\\Users\\KY\\.venvs\\robot_modbus_311\\Scripts\\python.exe -m pytest tests\\robot_ai\\test_robot_library_routes.py tests\\robot_ai\\test_robot_routes.py -q
npm.cmd test -- --run src/tests/engineer-workbench.test.tsx
npm.cmd run build
git commit -am "feat: add engineer log center"
\`\`\`

### Task 7: End-to-end verification and documentation

**Files:**
- Modify: \`nanobot-main-1/README.md\` or the current engineer guide
- Modify: \`docs/superpowers/specs/2026-07-14-engineer-flow-step-editor-design.md\`

- [ ] **Step 1: Document roles, lifecycle, transfer conflicts, controls, diagnostics, log retention and exclusions.**

- [ ] **Step 2: Run all relevant tests**

\`\`\`powershell
Set-Location nanobot-main-1
C:\\Users\\KY\\.venvs\\robot_modbus_311\\Scripts\\python.exe -m pytest tests\\robot_ai\\test_flow_executor.py tests\\robot_ai\\test_robot_library_routes.py tests\\robot_ai\\test_robot_routes.py -q
Set-Location webui
npm.cmd test -- --run src/tests/engineer-workbench.test.tsx src/tests/engineer-workbench-api.test.ts src/tests/robot-library-api.test.ts
npm.cmd run build
\`\`\`

- [ ] **Step 3: Browser acceptance**

Use an engineer account and disposable data to create, duplicate, archive, import/export and inspect diagnostics/logs. Use only delay flows when testing flow controls; never run real motion.

- [ ] **Step 4: Commit**

\`\`\`powershell
git add docs nanobot-main-1/README.md
git commit -m "docs: document engineer backend operations"
\`\`\`

## Coverage review

- Execution controls, history and live status: Tasks 1–2.
- Bulk management, transfer and preview: Task 3.
- Qt command family form coverage: Task 4.
- Controller diagnostics: Task 5.
- Full logs: Task 6.
- Automated and safe browser proof: Task 7.
- System/safety configuration and AI/voice are excluded by design.

