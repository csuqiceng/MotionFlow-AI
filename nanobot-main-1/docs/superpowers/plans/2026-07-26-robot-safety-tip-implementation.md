# 机器人安全按钮 Tip 交互 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将机器人侧栏七个安全按钮的浏览器确认弹框替换为非阻塞 Tip，同时保留完整服务端安全调用链。

**Architecture:** `RobotSidePanel` 继续通过 `robotSystemAction()` 执行系统动作；该函数的计划、确认码与执行请求不变。组件在请求开始时设置执行中 Tip，请求完成时更新为成功或失败 Tip，不再调用 `window.confirm`。

**Tech Stack:** React、TypeScript、Vitest、Testing Library。

---

### Task 1: 覆盖侧栏安全按钮的 Tip 行为

**Files:**
- Create: `webui/src/tests/robot-side-panel.test.tsx`
- Modify: `webui/src/robot/components/RobotSidePanel.tsx:75-89`

- [ ] **Step 1: 写入失败的组件测试**

```tsx
it("runs an emergency action without browser confirms and shows lifecycle tips", async () => {
  const confirm = vi.spyOn(window, "confirm");
  vi.mocked(robotSystemAction).mockResolvedValue({ ok: true, message: "done" } as RobotResult);
  render(<RobotSidePanel token="token" />);

  await userEvent.click(screen.getByRole("button", { name: "急停" }));

  expect(confirm).not.toHaveBeenCalled();
  expect(screen.getByRole("status")).toHaveTextContent("正在执行急停");
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("急停 已执行"));
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npm test -- --run src/tests/robot-side-panel.test.tsx`

Expected: FAIL，因为当前组件调用两次 `window.confirm`，且没有执行中 Tip。

- [ ] **Step 3: 实现最小交互改动**

```tsx
const runAction = async (action: string, label: string) => {
  setBusy(action);
  showToast(`正在执行${label}…`, true);
  try {
    const result = await robotSystemAction(token, safetySessionKey.current, action);
    showToast(result.ok ? `${label} 已执行` : `${label} 失败:${result.message}`, result.ok);
  } catch (e) {
    showToast(`${label} 失败:${(e as Error).message}`, false);
  } finally {
    setBusy(null);
  }
};
```

- [ ] **Step 4: 运行组件测试确认通过**

Run: `npm test -- --run src/tests/robot-side-panel.test.tsx`

Expected: PASS，且不出现浏览器确认框。

- [ ] **Step 5: 提交本任务**

```bash
git add webui/src/robot/components/RobotSidePanel.tsx webui/src/tests/robot-side-panel.test.tsx
git commit -m "feat: replace robot safety confirms with tips"
```

### Task 2: 验证所有安全按钮共享同一行为

**Files:**
- Modify: `webui/src/tests/robot-side-panel.test.tsx`
- Verify: `webui/src/robot/components/RobotSidePanel.tsx:13-29,75-89`

- [ ] **Step 1: 写入失败的参数化测试**

```tsx
it.each([
  ["急停", "emergency_stop"], ["暂停", "pause"], ["继续", "resume"],
  ["报警复位", "alarm_reset"], ["解除急停", "release_emergency_stop"],
  ["解除取消", "release_cancel"], ["停止当前", "stop_current"],
])("runs %s without browser confirms", async (label, action) => {
  render(<RobotSidePanel token="token" />);
  await userEvent.click(screen.getByRole("button", { name: label }));
  expect(window.confirm).not.toHaveBeenCalled();
  expect(robotSystemAction).toHaveBeenCalledWith("token", expect.any(String), action);
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npm test -- --run src/tests/robot-side-panel.test.tsx`

Expected: FAIL，当前七个按钮均会进入 `window.confirm`。

- [ ] **Step 3: 复核共享 `runAction` 路径**

确认 `EMERGENCY_ACTION`、`PRIMARY_CONTROL_ACTIONS` 与 `SECONDARY_ACTIONS` 均只通过 `runAction` 调用 `robotSystemAction`，不增加各按钮的分支逻辑。

- [ ] **Step 4: 运行测试确认通过**

Run: `npm test -- --run src/tests/robot-side-panel.test.tsx`

Expected: PASS，七个按钮均显示同一 Tip 生命周期且保留后端安全调用。

- [ ] **Step 5: 提交本任务**

```bash
git add webui/src/tests/robot-side-panel.test.tsx
git commit -m "test: cover robot safety tip actions"
```

### Task 3: 端到端 simulation 回归

**Files:**
- Verify: `webui/src/robot/components/RobotSidePanel.tsx`
- Verify: `webui/src/lib/robot-api.ts:1-220`

- [ ] **Step 1: 运行 WebUI 回归与生产构建**

Run: `npm test -- --run` and `npm run build`

Expected: 现有 WebUI 测试通过，TypeScript 与 Vite 生产构建成功。

- [ ] **Step 2: 启动 simulation 服务并人工验证**

Run:

```powershell
$env:ROBOT_AI_BACKEND='simulation'
python -m robot_server.cli --port 8766 --data-dir <scratch>\runtime\robot_platform
```

依次点击七个按钮并确认：不出现浏览器弹框；显示执行中、成功或失败 Tip；没有真实硬件连接。

- [ ] **Step 3: 提交本任务**

```bash
git add docs/superpowers/specs/2026-07-26-robot-safety-tip-design.md docs/superpowers/plans/2026-07-26-robot-safety-tip-implementation.md
git commit -m "docs: document robot safety tip behavior"
```
