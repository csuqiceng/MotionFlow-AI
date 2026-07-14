# Engineer Command and Flow Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give engineers a WebUI workbench to create, edit, validate, publish, and archive commands and flows while keeping published versions immutable.

**Architecture:** The command editor reuses the current versioned command registry and engineer routes. A parallel versioned flow registry and engineer flow routes supply draft lifecycle semantics; a role-gated React workbench calls those APIs. Publishing is the only operation that advances an active version, and authoring never executes motion.

**Tech Stack:** Python 3.11, websocket HTTP gateway, React/TypeScript, pytest, Vitest.

---

### Task 1: Add a versioned flow registry

**Files:**
- Create: `nanobot-main-1/robot_ai/flow/versioned_registry.py`
- Modify: `nanobot-main-1/robot_ai/flow/__init__.py`
- Test: `nanobot-main-1/tests/robot_ai/test_versioned_flow_registry.py`

- [ ] **Step 1: Write the failing lifecycle test**

```python
def test_flow_publish_keeps_prior_version(tmp_path):
    reg = VersionedFlowRegistry(tmp_path / "flows.json", audit_path=tmp_path / "audit.jsonl")
    reg.create_entity("pick", "Pick", [valid_step()])
    reg.publish("pick")
    reg.start_draft("pick")
    reg.update_draft("pick", expected_revision=1, name="Pick v2", steps=[valid_step()])
    entity = reg.publish("pick")
    assert entity["published_version"] == 2
    assert entity["versions"]["1"]["name"] == "Pick"
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `.venv-robot-desktop\\Scripts\\python.exe -m pytest -q tests\\robot_ai\\test_versioned_flow_registry.py`

Expected: FAIL because `VersionedFlowRegistry` does not exist.

- [ ] **Step 3: Implement the registry**

```python
class VersionedFlowRegistry:
    def create_entity(self, flow_id, name, steps, *, description="", actor="engineer"): ...
    def start_draft(self, flow_id, *, actor="engineer"): ...
    def update_draft(self, flow_id, *, expected_revision, name, steps, **metadata): ...
    def validate_draft(self, flow_id) -> list[str]: ...
    def publish(self, flow_id, *, actor="engineer"): ...
    def archive(self, flow_id, *, actor="engineer"): ...
```

Use the command registry schema pattern: `{flow_id, published_version, versions, draft, updated_at}`, atomic writes, revision conflicts, and pending audit events. Reject empty names or step lists, duplicate step IDs, nonpositive speeds, and invalid delay values.

- [ ] **Step 4: Run flow registry tests**

Run: `.venv-robot-desktop\\Scripts\\python.exe -m pytest -q tests\\robot_ai\\test_versioned_flow_registry.py`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add robot_ai/flow/versioned_registry.py robot_ai/flow/__init__.py tests/robot_ai/test_versioned_flow_registry.py; git commit -m "feat: add versioned flow registry"`

### Task 2: Add engineer flow APIs

**Files:**
- Modify: `nanobot-main-1/nanobot/api/robot_routes.py`
- Modify: `nanobot-main-1/nanobot/webui/ws_http.py`
- Test: `nanobot-main-1/tests/robot_ai/test_engineer_flow_api.py`
- Test: `nanobot-main-1/tests/robot_ai/test_engineer_routes.py`

- [ ] **Step 1: Write failing role and lifecycle tests**

```python
def test_engineer_can_create_and_publish_flow(tmp_path):
    status, body = process_engineer_create_flow(valid_flow_body(), **engineer_context(tmp_path))
    assert status == 201
    status, _ = process_engineer_publish_flow(body["data"]["flow_id"], **engineer_context(tmp_path))
    assert status == 200

def test_operator_cannot_create_flow(tmp_path):
    status, _ = process_engineer_create_flow(valid_flow_body(), **operator_context(tmp_path))
    assert status == 403
```

- [ ] **Step 2: Run test and verify it fails**

Run: `.venv-robot-desktop\\Scripts\\python.exe -m pytest -q tests\\robot_ai\\test_engineer_flow_api.py`

Expected: FAIL because flow processors are absent.

- [ ] **Step 3: Implement route processors and gateway dispatch**

```python
def process_engineer_create_flow(body, **kwargs): ...
def process_engineer_start_flow_draft(flow_id, **kwargs): ...
def process_engineer_update_flow_draft(flow_id, body, **kwargs): ...
def process_engineer_validate_flow_draft(flow_id, **kwargs): ...
def process_engineer_publish_flow(flow_id, **kwargs): ...
def process_engineer_archive_flow(flow_id, **kwargs): ...
```

Mount `/api/robot/engineer/flows` and `/api/robot/engineer/flows/{id}/{draft|validate|publish|archive}`. Require both gateway and engineer user tokens; use the existing engineer action header for create/start-draft/update-draft; return `409` for revision mismatch.

- [ ] **Step 4: Run backend tests**

Run: `.venv-robot-desktop\\Scripts\\python.exe -m pytest -q tests\\robot_ai\\test_engineer_flow_api.py tests\\robot_ai\\test_engineer_routes.py`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add nanobot/api/robot_routes.py nanobot/webui/ws_http.py tests/robot_ai/test_engineer_flow_api.py tests/robot_ai/test_engineer_routes.py; git commit -m "feat: add engineer flow API"`

### Task 3: Add a typed engineer workbench client

**Files:**
- Create: `nanobot-main-1/webui/src/lib/engineer-workbench-api.ts`
- Test: `nanobot-main-1/webui/src/tests/engineer-workbench-api.test.ts`

- [ ] **Step 1: Write the failing request test**

```ts
it("creates commands with gateway and engineer tokens", async () => {
  await engineerCreateCommand("gateway", "engineer", commandBody);
  expect(fetchWithTimeout).toHaveBeenCalledWith(
    "/api/robot/engineer/commands",
    expect.objectContaining({ headers: expect.objectContaining({
      "X-Nanobot-Engineer-Action": "create",
      "X-Nanobot-User-Token": "engineer",
    }) }),
    15_000,
  );
});
```

- [ ] **Step 2: Run test and verify failure**

Run: `npm.cmd --prefix webui test -- --run src/tests/engineer-workbench-api.test.ts`

Expected: FAIL because the client does not exist.

- [ ] **Step 3: Implement command and flow methods**

```ts
export const engineerCreateCommand = (gateway, user, body) => engineerRequest(...);
export const engineerUpdateCommandDraft = (gateway, user, id, body) => engineerRequest(...);
export const engineerPublishCommand = (gateway, user, id) => engineerRequest(...);
export const engineerCreateFlow = (gateway, user, body) => engineerRequest(...);
export const engineerUpdateFlowDraft = (gateway, user, id, body) => engineerRequest(...);
export const engineerPublishFlow = (gateway, user, id) => engineerRequest(...);
```

Use GET plus `Authorization`, `X-Nanobot-User-Token`, `X-Nanobot-Engineer-Action`, and `X-Nanobot-Robot-Body`. Translate `409` into a typed conflict error.

- [ ] **Step 4: Run client tests**

Run: `npm.cmd --prefix webui test -- --run src/tests/engineer-workbench-api.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add webui/src/lib/engineer-workbench-api.ts webui/src/tests/engineer-workbench-api.test.ts; git commit -m "feat: add engineer workbench client"`

### Task 4: Build the role-gated editors

**Files:**
- Create: `nanobot-main-1/webui/src/robot/workbench/EngineerWorkbench.tsx`
- Create: `nanobot-main-1/webui/src/robot/workbench/CommandDraftEditor.tsx`
- Create: `nanobot-main-1/webui/src/robot/workbench/FlowDraftEditor.tsx`
- Modify: `nanobot-main-1/webui/src/robot/library/CommandLibraryPage.tsx`
- Modify: `nanobot-main-1/webui/src/App.tsx`
- Test: `nanobot-main-1/webui/src/tests/engineer-workbench.test.tsx`

- [ ] **Step 1: Write failing UI tests**

```tsx
it("shows New command only to engineers", () => {
  render(<EngineerWorkbench role="engineer" {...tokens} />);
  expect(screen.getByRole("button", { name: "New command" })).toBeVisible();
});

it("adds a step then publishes a validated flow", async () => {
  render(<FlowDraftEditor draft={draft} {...callbacks} />);
  await user.click(screen.getByRole("button", { name: "Add step" }));
  await user.click(screen.getByRole("button", { name: "Publish flow" }));
  expect(callbacks.publish).toHaveBeenCalled();
});
```

- [ ] **Step 2: Run tests and verify failure**

Run: `npm.cmd --prefix webui test -- --run src/tests/engineer-workbench.test.tsx`

Expected: FAIL because the workbench is absent.

- [ ] **Step 3: Implement editors and actions**

Render the existing library unchanged for operators. For engineers render list/detail plus New, Edit draft, Save, Validate, Publish and Archive. Command drafts edit metadata, component and JSON parameters. Flow drafts edit metadata and ordered steps with add/remove/up/down. Publish requires a confirmation dialog; validation and `409` errors remain visible; successful writes reload the list.

- [ ] **Step 4: Run component tests**

Run: `npm.cmd --prefix webui test -- --run src/tests/engineer-workbench.test.tsx src/tests/command-library-page.test.tsx`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add webui/src/robot/workbench webui/src/robot/library/CommandLibraryPage.tsx webui/src/App.tsx webui/src/tests/engineer-workbench.test.tsx; git commit -m "feat: add engineer command and flow workbench"`

### Task 5: Verify the complete lifecycle

**Files:**
- Modify: `nanobot-main-1/tests/robot_ai/test_engineer_routes.py`
- Modify: `nanobot-main-1/webui/src/tests/app-layout.test.tsx`
- Modify: `nanobot-main-1/README.md`

- [ ] **Step 1: Add failing gateway lifecycle coverage**

```python
async def test_engineer_flow_lifecycle_over_gateway(tmp_path):
    client, tokens = await make_engineer_client(tmp_path)
    created = await client.create_flow(valid_flow_body())
    published = await client.publish_flow(created["flow_id"])
    assert published["version"] == 1
```

- [ ] **Step 2: Run test and verify failure**

Run: `.venv-robot-desktop\\Scripts\\python.exe -m pytest -q tests\\robot_ai\\test_engineer_routes.py`

Expected: FAIL until the complete flow lifecycle reaches the gateway.

- [ ] **Step 3: Complete documentation and token wiring**

Document draft/publish behavior and immutable versions in `README.md`. Ensure `App.tsx` passes the authenticated user role, gateway token, and user token to the workbench; do not add robot execution calls.

- [ ] **Step 4: Run targeted verification**

Run: `.venv-robot-desktop\\Scripts\\python.exe -m pytest -q tests\\robot_ai\\test_versioned_flow_registry.py tests\\robot_ai\\test_engineer_flow_api.py tests\\robot_ai\\test_engineer_routes.py tests\\robot_ai\\test_engineer_api.py`

Run: `npm.cmd --prefix webui test -- --run src/tests/engineer-workbench-api.test.ts src/tests/engineer-workbench.test.tsx src/tests/command-library-page.test.tsx src/tests/app-layout.test.tsx`

Run: `npm.cmd --prefix webui run build`

Expected: all selected tests and production build pass.

- [ ] **Step 5: Browser verification**

Log in as engineer, create disposable command and flow drafts, validate and publish them, then confirm library version `1`. Do not send a robot run or system action.

- [ ] **Step 6: Commit**

Run: `git add README.md tests/robot_ai/test_engineer_routes.py webui/src/tests/app-layout.test.tsx; git commit -m "test: verify engineer workbench lifecycle"`
