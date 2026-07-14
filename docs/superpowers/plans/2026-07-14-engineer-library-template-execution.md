# Engineer Library Template Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace JSON-first engineer editing with component-schema forms and selectable command steps, then allow published commands and flows to preflight and execute directly from the library without a second user confirmation dialog.

**Architecture:** The existing component catalog remains the single source for command parameter schemas. The WebUI loads that catalog and renders typed controls; it serializes the resulting object into the existing versioned command/flow draft APIs. A new authenticated library-run API resolves only published items, turns a command into the runtime's normal one-step flow representation, performs a dry-run, then makes a real run only after that preflight succeeds. The direct button intentionally has no human-confirmation dialog, but it cannot bypass role authorization or the runtime controller safety gates.

**Tech Stack:** Python 3.11, aiohttp/websockets gateway, robot_ai component catalog and execution stores, React/TypeScript, Vitest, pytest.

---

### Task 1: Expose command schemas to the workbench client

**Files:**
- Modify: `nanobot-main-1/webui/src/lib/robot-library-api.ts`
- Modify: `nanobot-main-1/webui/src/robot/workbench/CommandDraftEditor.tsx`
- Test: `nanobot-main-1/webui/src/tests/engineer-workbench.test.tsx`

- [ ] **Step 1: Write the failing component-form test**

```tsx
vi.mock("@/lib/robot-library-api", () => ({
  robotLibraryComponents: vi.fn().mockResolvedValue({
    ok: true,
    data: { items: [{ id: "delay", name: "延时", parameters: [
      { name: "delay_sec", label: "延时秒数", type: "number", required: true, default: 1 },
    ] }], total: 1 },
  }),
}));

it("creates a command with catalog selection and typed fields instead of JSON", async () => {
  render(<CommandDraftEditor draft={blankDraft} onSave={onSave} components={delayCatalog} />);
  await userEvent.selectOptions(screen.getByLabelText("命令类型"), "delay");
  await userEvent.clear(screen.getByLabelText("延时秒数"));
  await userEvent.type(screen.getByLabelText("延时秒数"), "2");
  await userEvent.click(screen.getByRole("button", { name: "保存草稿" }));
  expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
    component_id: "delay", parameters: { delay_sec: 2 },
  }));
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm.cmd test -- --run src/tests/engineer-workbench.test.tsx`

Expected: FAIL because `CommandDraftEditor` has no `components` prop or typed parameter controls.

- [ ] **Step 3: Add catalog types and fetch helper**

```ts
export interface LibraryParameterSchema {
  name: string;
  label: string;
  type: "number" | "integer" | "string" | "boolean" | "select";
  required?: boolean;
  default?: unknown;
  options?: Array<{ label: string; value: string | number }>;
}

export interface LibraryComponent {
  id: string;
  name: string;
  description?: string;
  parameters: LibraryParameterSchema[];
}

export function robotLibraryComponents(token: string) {
  return libraryGet<{ ok: boolean; data: { items: LibraryComponent[]; total: number } }>(
    "/api/robot/library/components", token,
  );
}
```

- [ ] **Step 4: Render selected component parameters as typed controls**

```tsx
const component = components.find((item) => item.id === value.component_id);

<select aria-label={t("library.workbench.commandType")} value={value.component_id}
  onChange={(event) => setValue({
    ...value,
    component_id: event.target.value,
    parameters: defaultsFor(components.find((item) => item.id === event.target.value)),
  })}>
  <option value="">{t("library.workbench.selectCommandType")}</option>
  {components.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
</select>
{component?.parameters.map((field) => <ParameterField key={field.name} field={field}
  value={value.parameters[field.name]} onChange={(next) => setValue({
    ...value, parameters: { ...value.parameters, [field.name]: next },
  })} />)}
```

Keep a read-only `details` preview of the parameter object; remove the editable JSON textarea.

- [ ] **Step 5: Run the focused WebUI test**

Run: `npm.cmd test -- --run src/tests/engineer-workbench.test.tsx`

Expected: PASS.

- [ ] **Step 6: Commit the catalog-form slice**

```bash
git add nanobot-main-1/webui/src/lib/robot-library-api.ts nanobot-main-1/webui/src/robot/workbench/CommandDraftEditor.tsx nanobot-main-1/webui/src/tests/engineer-workbench.test.tsx
git commit -m "feat: build command drafts from catalog forms"
```

### Task 2: Build flows by selecting published command templates

**Files:**
- Modify: `nanobot-main-1/webui/src/robot/workbench/FlowDraftEditor.tsx`
- Modify: `nanobot-main-1/webui/src/robot/workbench/EngineerWorkbench.tsx`
- Modify: `nanobot-main-1/webui/src/i18n/locales/en/common.json`
- Modify: `nanobot-main-1/webui/src/i18n/locales/zh-CN/common.json`
- Test: `nanobot-main-1/webui/src/tests/engineer-workbench.test.tsx`

- [ ] **Step 1: Write the failing selectable-step test**

```tsx
it("adds a flow step from the command template picker", async () => {
  render(<FlowDraftEditor draft={blankFlow} commands={[homeCommand]} onSave={onSave} />);
  await userEvent.selectOptions(screen.getByLabelText("可选命令"), "home");
  await userEvent.click(screen.getByRole("button", { name: "添加步骤" }));
  expect(screen.getByText("1. Home")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "保存草稿" }));
  expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
    steps: [expect.objectContaining({ action: "Home", func_id: 108 })],
  }));
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm.cmd test -- --run src/tests/engineer-workbench.test.tsx`

Expected: FAIL because the editor has only manually typed step fields.

- [ ] **Step 3: Pass published command list to the flow editor**

```tsx
const commandLibrary = useRobotLibrary(gatewayToken, "commands");

<FlowDraftEditor
  draft={editor.draft}
  commands={commandLibrary.items}
  onSave={saveFlow}
/>
```

- [ ] **Step 4: Add template selection and step cards**

```tsx
const addSelectedCommand = () => {
  const command = commands.find((item) => item.id === selectedCommandId);
  if (!command) return;
  setValue((current) => ({
    ...current,
    steps: [...current.steps, {
      step_id: current.steps.length + 1,
      action: command.name,
      func_id: funcIdForComponent(command.component_id),
      params: command.parameters,
      position_name: null,
      spd_pct: Number(command.parameters.spd_pct ?? 100),
      description: command.description,
    }],
  }));
};
```

Retain only speed override, optional step description, remove, move up, and move down controls. Render the chosen command and its values as read-only details, rather than raw JSON/func-id input.

- [ ] **Step 5: Add Chinese and English labels**

```json
"commandType": "命令类型",
"selectCommandType": "选择命令类型",
"availableCommands": "可选命令",
"addStep": "添加步骤",
"parameterPreview": "参数预览"
```

- [ ] **Step 6: Run the focused WebUI test**

Run: `npm.cmd test -- --run src/tests/engineer-workbench.test.tsx`

Expected: PASS.

- [ ] **Step 7: Commit the selectable-flow slice**

```bash
git add nanobot-main-1/webui/src/robot/workbench/FlowDraftEditor.tsx nanobot-main-1/webui/src/robot/workbench/EngineerWorkbench.tsx nanobot-main-1/webui/src/i18n/locales/en/common.json nanobot-main-1/webui/src/i18n/locales/zh-CN/common.json nanobot-main-1/webui/src/tests/engineer-workbench.test.tsx
git commit -m "feat: compose flows from command templates"
```

### Task 3: Add authenticated direct-run endpoints that preserve preflight

**Files:**
- Modify: `nanobot-main-1/nanobot/api/robot_routes.py`
- Modify: `nanobot-main-1/nanobot/webui/ws_http.py`
- Test: `nanobot-main-1/tests/robot_ai/test_robot_library_routes.py`
- Test: `nanobot-main-1/tests/robot_ai/test_ws_http_library_routes.py`

- [ ] **Step 1: Write the failing backend tests**

```python
def test_published_library_command_direct_run_preflights_then_executes(tmp_path, patch_flow_runner):
    commands = seed_published_command(tmp_path, component_id="delay", parameters={"delay_sec": 1})
    status, result = process_robot_library_command_run("delay-1", commands_path=str(commands))
    assert status == 200
    assert result["ok"] is True
    seen, _ = patch_flow_runner
    assert [request.execute_real for request in seen] == [False, True]

def test_unknown_or_unpublished_library_command_never_reaches_runner(tmp_path, patch_flow_runner):
    status, result = process_robot_library_command_run("missing", commands_path=str(tmp_path / "commands.json"))
    assert status == 404
    seen, _ = patch_flow_runner
    assert seen == []
```

- [ ] **Step 2: Run the backend test to verify it fails**

Run: `python -m pytest tests/robot_ai/test_robot_library_routes.py -q`

Expected: FAIL because `process_robot_library_command_run` does not exist.

- [ ] **Step 3: Implement direct command execution through the runtime flow path**

```python
def _published_command_flow(command: dict[str, Any]) -> FlowEntry:
    component = ComponentCatalog().get(str(command["component_id"]))
    return FlowEntry(
        name=str(command["name"]),
        steps=[FlowStep(step_id=1, action=component.id, func_id=component.func_num,
                        params=dict(command["parameters"]), description=str(command.get("description", "")))],
    )

def _run_library_flow(entry: FlowEntry) -> dict[str, Any]:
    dry_run = run_flow(entry, execute_real=False)
    if not dry_run.get("ok"):
        return dry_run
    return run_flow(entry, execute_real=True, confirm_work_area_clear=True,
                    confirm_estop_ready=True,
                    confirmation_code=REAL_EXECUTION_CONFIRMATION_CODE)

def process_robot_library_command_run(command_id, *, commands_path):
    command = _get_published_command(command_id, _resolve_commands_path(commands_path))
    if command is None:
        return 404, {"error": {"code": "command_not_found", "message": "Published command not found."}}
    return 200, _run_library_flow(_published_command_flow(command))
```

Use only published records. Add a matching flow wrapper that resolves the registered flow and calls `_run_library_flow`; it must return the failed dry-run unchanged and must never issue the real run in that case. Append an audit event for both the dry-run rejection and the final result, including item type, item id/name, actor, and result state.

- [ ] **Step 4: Dispatch and authorize library-run routes in the gateway**

```python
command_run = re.match(r"^/api/robot/library/commands/([^/]+)/run$", got)
flow_run = re.match(r"^/api/robot/library/flows/([^/]+)/run$", got)

if command_run:
    user = get_user_session_store().check(_user_token_from_request(request))
    if user is None:
        return _http_error(401, "Authenticated user required")
    return _resp(*robot_routes.process_robot_library_command_run(
        unquote(command_run.group(1)), commands_path=commands_path,
        actor={"actor_user_id": user["user_id"], "actor_role": user["role"]},
    ))
```

Require the gateway token plus an authenticated user token. Allow `operator` and `engineer`; do not expose the endpoint to anonymous users. Keep the existing library GET routes read-only and token-gated as they are.

- [ ] **Step 5: Run backend and route tests**

Run: `python -m pytest tests/robot_ai/test_robot_library_routes.py tests/robot_ai/test_ws_http_library_routes.py tests/robot_ai/test_robot_flow_routes.py -q`

Expected: PASS, with fakes proving dry-run happens before real execution and unpublished content cannot execute.

- [ ] **Step 6: Commit the library-run API slice**

```bash
git add nanobot-main-1/nanobot/api/robot_routes.py nanobot-main-1/nanobot/webui/ws_http.py nanobot-main-1/tests/robot_ai/test_robot_library_routes.py nanobot-main-1/tests/robot_ai/test_ws_http_library_routes.py
git commit -m "feat: run published library items after preflight"
```

### Task 4: Add library execution controls and status feedback

**Files:**
- Modify: `nanobot-main-1/webui/src/lib/robot-library-api.ts`
- Modify: `nanobot-main-1/webui/src/robot/library/CommandDetail.tsx`
- Modify: `nanobot-main-1/webui/src/robot/library/FlowDetail.tsx`
- Modify: `nanobot-main-1/webui/src/robot/library/CommandLibraryPage.tsx`
- Modify: `nanobot-main-1/webui/src/robot/workbench/EngineerWorkbench.tsx`
- Modify: `nanobot-main-1/webui/src/i18n/locales/en/common.json`
- Modify: `nanobot-main-1/webui/src/i18n/locales/zh-CN/common.json`
- Test: `nanobot-main-1/webui/src/tests/command-library-page.test.tsx`
- Test: `nanobot-main-1/webui/src/tests/engineer-workbench.test.tsx`

- [ ] **Step 1: Write failing direct-run UI tests**

```tsx
it("runs a selected command and renders preflight result", async () => {
  vi.mocked(runLibraryCommand).mockResolvedValue({ ok: true, state: "completed" });
  render(<CommandLibraryPage />);
  await userEvent.click(screen.getByRole("button", { name: "执行命令" }));
  expect(runLibraryCommand).toHaveBeenCalledWith(gatewayToken, userToken, "home");
  expect(await screen.findByRole("status")).toHaveTextContent("执行完成");
});

it("does not render an execution button for an unpublished item", () => {
  render(<CommandDetail command={{ ...command, status: "draft" }} onRun={onRun} />);
  expect(screen.queryByRole("button", { name: "执行命令" })).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the UI tests to verify they fail**

Run: `npm.cmd test -- --run src/tests/command-library-page.test.tsx src/tests/engineer-workbench.test.tsx`

Expected: FAIL because no run helper, button, or status region exists.

- [ ] **Step 3: Add typed run helpers**

```ts
export function runLibraryCommand(gatewayToken: string, userToken: string, id: string) {
  return libraryPost(`/api/robot/library/commands/${encodeURIComponent(id)}/run`, gatewayToken, userToken);
}

export function runLibraryFlow(gatewayToken: string, userToken: string, name: string) {
  return libraryPost(`/api/robot/library/flows/${encodeURIComponent(name)}/run`, gatewayToken, userToken);
}
```

- [ ] **Step 4: Render direct execution controls**

```tsx
{command.status === "published" && onRun ? (
  <Button disabled={running} onClick={() => void onRun(command.id)}>
    {running ? t("library.running") : t("library.runCommand")}
  </Button>
) : null}
{runResult && <p role="status">{runResult.ok ? t("library.runComplete") : runResult.message}</p>}
```

Use identical published-only gating for flows. A click invokes the direct-run endpoint once; there is no frontend confirmation modal. Show backend preflight rejection text unchanged and keep the button disabled while the request is in flight.

- [ ] **Step 5: Add localized labels and run full WebUI verification**

Run: `npm.cmd test -- --run src/tests/command-library-page.test.tsx src/tests/engineer-workbench.test.tsx src/tests/robot-library-api.test.ts && npm.cmd run build`

Expected: all selected tests and TypeScript/Vite build PASS.

- [ ] **Step 6: Commit the execution-controls slice**

```bash
git add nanobot-main-1/webui/src/lib/robot-library-api.ts nanobot-main-1/webui/src/robot/library/CommandDetail.tsx nanobot-main-1/webui/src/robot/library/FlowDetail.tsx nanobot-main-1/webui/src/robot/library/CommandLibraryPage.tsx nanobot-main-1/webui/src/robot/workbench/EngineerWorkbench.tsx nanobot-main-1/webui/src/i18n/locales/en/common.json nanobot-main-1/webui/src/i18n/locales/zh-CN/common.json nanobot-main-1/webui/src/tests/command-library-page.test.tsx nanobot-main-1/webui/src/tests/engineer-workbench.test.tsx
git commit -m "feat: execute published items from the library"
```

### Task 5: Final safety and regression verification

**Files:**
- Modify: only files changed by Tasks 1–4 if verification exposes a defect
- Test: `nanobot-main-1/tests/robot_ai/test_engineer_api.py`
- Test: `nanobot-main-1/tests/robot_ai/test_robot_flow_routes.py`
- Test: `nanobot-main-1/webui/src/tests/engineer-workbench.test.tsx`
- Test: `nanobot-main-1/webui/src/tests/command-library-page.test.tsx`

- [ ] **Step 1: Run backend regression tests**

Run: `python -m pytest tests/robot_ai/test_engineer_api.py tests/robot_ai/test_robot_library_routes.py tests/robot_ai/test_robot_flow_routes.py tests/robot_ai/test_ws_http_library_routes.py -q`

Expected: PASS.

- [ ] **Step 2: Run WebUI regression tests and production build**

Run: `npm.cmd test -- --run src/tests/engineer-workbench.test.tsx src/tests/command-library-page.test.tsx src/tests/robot-library-api.test.ts src/tests/i18n.test.tsx && npm.cmd run build`

Expected: PASS.

- [ ] **Step 3: Inspect the live UI without executing a robot item**

Open `http://127.0.0.1:5173/`, sign in only if an existing local session is available, and verify: component selector, typed fields, command picker, published-only execution button, and disabled-in-flight state. Do not click a real run control.

- [ ] **Step 4: Commit any verification-only correction**

```bash
git add <corrected-files>
git commit -m "fix: align engineer library execution behavior"
```

## Review checklist

- The component catalog, not a second UI-only schema, defines command fields.
- No editable JSON fields remain in engineer command or flow creation.
- Flow steps come from selected published command templates, retain ordering controls, and serialize to the existing `EngineerFlowDraft` API shape.
- Library execution accepts only published command/flow records and performs a dry-run before any real execution call.
- The direct UI button has no extra human-confirmation modal, but a failed preflight never executes.
- All runner tests use fakes; browser verification never clicks a real run control.
