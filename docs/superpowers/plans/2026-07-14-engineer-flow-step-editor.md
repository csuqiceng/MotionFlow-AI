# 工程师流程步骤编辑与执行时间线 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 支持工程师重排、复制、删除流程步骤，并显示执行时间线。

**Architecture:** 将步骤数组操作放进纯函数工具模块，编辑器只负责交互；时间线为独立展示组件，工作台把既有库执行的结果转换为时间线状态。

**Tech Stack:** React、TypeScript、Vitest、Testing Library、现有 robot library API。

---

### Task 1: 实现并测试流程步骤数组工具

**Files:**
- Create: `nanobot-main-1/webui/src/robot/workbench/flow-steps.ts`
- Test: `nanobot-main-1/webui/src/tests/flow-steps.test.ts`

- [ ] **Step 1: 写失败测试**

```ts
expect(moveFlowStep(steps, 0, 1).map((step) => step.action)).toEqual(["close", "home"]);
expect(cloneFlowStep(steps, 0)[1].params).not.toBe(steps[0].params);
expect(removeFlowStep(steps, 0).map((step) => step.step_id)).toEqual([1]);
```

- [ ] **Step 2: 验证 RED**

Run: `npm.cmd test -- --run src/tests/flow-steps.test.ts`

Expected: FAIL，因为 `flow-steps.ts` 尚不存在。

- [ ] **Step 3: 最小实现**

```ts
const renumber = (steps) => steps.map((step, index) => ({ ...step, step_id: index + 1 }));
export const moveFlowStep = (steps, from, to) => { const next = [...steps]; next.splice(to, 0, next.splice(from, 1)[0]); return renumber(next); };
export const cloneFlowStep = (steps, index) => { const next = [...steps]; next.splice(index + 1, 0, { ...steps[index], params: structuredClone(steps[index].params) }); return renumber(next); };
export const removeFlowStep = (steps, index) => renumber(steps.filter((_, current) => current !== index));
```

- [ ] **Step 4: 验证 GREEN 并提交**

Run: `npm.cmd test -- --run src/tests/flow-steps.test.ts`

Expected: PASS。

```bash
git add nanobot-main-1/webui/src/robot/workbench/flow-steps.ts nanobot-main-1/webui/src/tests/flow-steps.test.ts
git commit -m "feat: add flow step editing helpers"
```

### Task 2: 在流程编辑器接入拖拽、复制和删除

**Files:**
- Modify: `nanobot-main-1/webui/src/robot/workbench/FlowDraftEditor.tsx`
- Modify: `nanobot-main-1/webui/src/i18n/locales/zh-CN/common.json`
- Modify: `nanobot-main-1/webui/src/i18n/locales/en/common.json`
- Test: `nanobot-main-1/webui/src/tests/flow-draft-editor.test.tsx`

- [ ] **Step 1: 写失败测试**

```tsx
await userEvent.click(screen.getByRole("button", { name: "复制步骤 1" }));
expect(screen.getAllByRole("group", { name: /步骤/ })).toHaveLength(3);
await userEvent.click(screen.getByRole("button", { name: "删除步骤 1" }));
expect(screen.queryByText("home")).not.toBeInTheDocument();
```

- [ ] **Step 2: 验证 RED**

Run: `npm.cmd test -- --run src/tests/flow-draft-editor.test.tsx`

Expected: FAIL，因为复制按钮不存在。

- [ ] **Step 3: 最小实现**

为每个步骤容器增加 `draggable`、拖动手柄与 `onDrop`，调用 `moveFlowStep`；增加 `复制步骤 {{number}}` 按钮调用 `cloneFlowStep`；删除按钮改调用 `removeFlowStep`。保留现有上移和下移按钮作为键盘替代方案。

- [ ] **Step 4: 验证 GREEN 并提交**

Run: `npm.cmd test -- --run src/tests/flow-draft-editor.test.tsx src/tests/flow-steps.test.ts`

Expected: PASS。

```bash
git add nanobot-main-1/webui/src/robot/workbench/FlowDraftEditor.tsx nanobot-main-1/webui/src/i18n/locales/zh-CN/common.json nanobot-main-1/webui/src/i18n/locales/en/common.json nanobot-main-1/webui/src/tests/flow-draft-editor.test.tsx
git commit -m "feat: edit flow step order and copies"
```

### Task 3: 实现执行时间线

**Files:**
- Create: `nanobot-main-1/webui/src/robot/workbench/ExecutionTimeline.tsx`
- Modify: `nanobot-main-1/webui/src/robot/workbench/EngineerWorkbench.tsx`
- Test: `nanobot-main-1/webui/src/tests/execution-timeline.test.tsx`

- [ ] **Step 1: 写失败测试**

```tsx
render(<ExecutionTimeline entries={[{ label: "home", state: "succeeded" }, { label: "close", state: "failed", message: "controller alarm" }, { label: "place", state: "skipped" }]} />);
expect(screen.getByText("home：完成")).toBeInTheDocument();
expect(screen.getByText("close：失败")).toBeInTheDocument();
expect(screen.getByText("place：已跳过")).toBeInTheDocument();
```

- [ ] **Step 2: 验证 RED**

Run: `npm.cmd test -- --run src/tests/execution-timeline.test.tsx`

Expected: FAIL，因为 `ExecutionTimeline` 尚不存在。

- [ ] **Step 3: 最小实现**

定义 `queued | running | succeeded | failed | skipped` 状态和纯展示组件。在 `runSelected` 启动前为流程步骤创建 `queued` 项，当前项置为 `running`；API 成功后全部置为 `succeeded`；失败时当前项置为 `failed`、后续置为 `skipped`，使用服务端消息作为失败原因。命令只创建一个时间线项；不得绕过既有预检与执行 API。

- [ ] **Step 4: 验证 GREEN 并提交**

Run: `npm.cmd test -- --run src/tests/execution-timeline.test.tsx src/tests/app-layout.test.tsx`

Expected: PASS。

```bash
git add nanobot-main-1/webui/src/robot/workbench/ExecutionTimeline.tsx nanobot-main-1/webui/src/robot/workbench/EngineerWorkbench.tsx nanobot-main-1/webui/src/tests/execution-timeline.test.tsx
git commit -m "feat: show library execution timeline"
```

### Task 4: 验证

**Files:**
- Test: `nanobot-main-1/webui/src/tests/flow-steps.test.ts`
- Test: `nanobot-main-1/webui/src/tests/flow-draft-editor.test.tsx`
- Test: `nanobot-main-1/webui/src/tests/execution-timeline.test.tsx`

- [ ] **Step 1: 执行聚焦测试**

Run: `npm.cmd test -- --run src/tests/flow-steps.test.ts src/tests/flow-draft-editor.test.tsx src/tests/execution-timeline.test.tsx`

Expected: PASS。

- [ ] **Step 2: 构建并进行网页验证**

Run: `npm.cmd run build`

Expected: TypeScript 和 Vite 构建完成。

登录 `http://127.0.0.1:5173/#/engineer`，创建或编辑流程，完成添加、复制、重排、删除、保存；确认时间线组件可见。自动化网页验证不得点击会驱动机械手的执行按钮。
