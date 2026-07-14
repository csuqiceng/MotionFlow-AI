# 统一登录 + 会话命名空间隔离 — 切片② 前端实施计划 (Plan B)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 适配 webui 到切片② 后端 auth 门控与命名空间隔离：双 Tab 统一登录页（操作员/工程师）+ 双 token 内存化（`bootstrap → /api/auth/login → user_token → WS 首帧 auth`）+ shell 由 session 角色驱动 + 按用户命名空间隔离会话/sidebar。解除当前 `auth_required` 兼容性断点。

**Architecture:** 登录页先 `GET /webui/bootstrap`（localhost 免密拿 ws_token），再 `GET /api/auth/login`（`Authorization: Bearer <ws_token>` + `X-Nanobot-Robot-Body: {username,password,role}`）拿 `user_token`；两 token 仅存 React state（不入 localStorage）。WS 连上后 **`auth` 作为首帧**（携带 user_token），服务端绑定后才允许 `new_chat`/`message`；`NanobotClient` 用"未 auth 完成前缓冲业务帧"机制保证顺序，重连/`onReauth` 后重发 `auth`。shell 由 `user_token.role` 决定；两角色同壳（Sidebar+ThreadShell+RobotSidePanel）。会话列表/sidebar 按 `namespace="{role}:{user_id}"` 隔离。

**Tech Stack:** React + TypeScript, Vite, vitest (+ jsdom), shadcn/ui + Tailwind, i18next. 复用 `robotRequest` 模式（GET + `X-Nanobot-Robot-Body` + `Authorization: Bearer`）。复用切片② 后端（已实现，B1-B8）。

**关联:** spec `docs/superpowers/specs/2026-07-12-robot-unified-login-session-namespace-design.md`（§2 登录页/§3 跳转/§4 token 流/§5 WS auth/§9 前端改动）。后端 Plan A（B1-B8 已实现·待最终复核）。

---

## ⚠️ 硬约束（覆盖 skill 默认）

1. **全程 NO GIT**（memory `no-git-commit-unified-later`）：禁止 `git add/commit/push/branch`。每任务以 vitest/build 验证收尾，不提交。
2. **零进程管理**（memory `no-process-management-without-approval`）：**禁止 `taskkill`/`Stop-Process`/按名或通配杀进程；禁止启动/重启 gateway 或旧项目**。测试只用 `cd webui && bun run test`（vitest，纯前端，不起 gateway）。若 vitest 挂起，**只报告命令+现象+精确 PID，不自处理**。
3. **不动后端**：B1-B8 已实现，前端只调用其契约（`/api/auth/login`、`X-Nanobot-User-Token`、WS `auth` 帧、`auth_ok` 事件）。不改任何 `nanobot/`/`robot_ai/` 文件。
4. **测试零 skip**：用 `NanobotClient` 的 `socketFactory` 注入（nanobot-client.ts:110）造假 WebSocket；用 `vi.mock`/`vi.fn` 造假 fetch。**禁止 `it.skip`/`pytest.skip`**。
5. **不破坏既有 vitest**：每任务结束跑 `cd webui && bun run test`，既有用例不回归。

---

## 文件结构

| 文件 | 责任 | 动作 |
|---|---|---|
| `webui/src/lib/bootstrap.ts` | `fetchLogin`/`fetchLogout`；删 secret 持久化 | 改 |
| `webui/src/components/LoginPage.tsx` (新) | 双 Tab 登录页（操作员/工程师） | 增 |
| `webui/src/App.tsx` | `AuthForm`→`LoginPage`；`BootState.ready` 带 wsToken/userToken/user；shell-by-role；跨角色 hash 重定向；bootstrap-first | 改 |
| `webui/src/lib/api.ts` | session 调用加 `X-Nanobot-User-Token`；`listSessions(ws,user)` | 改 |
| `webui/src/hooks/useSessions.ts` | 按 namespace 参数化 | 改 |
| `webui/src/hooks/useSidebarState.ts` | 按 namespace 参数化（localStorage 键加 ns） | 改 |
| `webui/src/providers/ClientProvider.tsx` | 透传 `userToken` + `user` | 改 |
| `webui/src/lib/nanobot-client.ts` | `auth` 首帧 + 缓冲 + `auth_ok` + 重连重发 + auth 失败信号 | 改 |
| `webui/src/i18n/**` | 登录页/错误态文案 key | 改/增 |
| `webui/src/tests/login-page.test.tsx`/`client-auth.test.ts` 等 (新) | vitest | 增 |

---

## Task F1: `bootstrap.ts` — `fetchLogin`/`fetchLogout` + 删 secret 持久化

**Files:** Modify `webui/src/lib/bootstrap.ts`；Test `webui/src/tests/bootstrap.test.ts`（既有，扩展）。

- [ ] **Step 1: 写失败测试（追加到既有 bootstrap 测试或新 client-auth 测试）**

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fetchLogin, fetchLogout } from "@/lib/bootstrap";

describe("fetchLogin / fetchLogout", () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn();
  });

  it("fetchLogin: GET /api/auth/login with Bearer wsToken + X-Nanobot-Robot-Body", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true, data: {
        user_token: "utok", expires_in: 28800,
        user: { user_id: "u1", username: "op", role: "operator" } } }), { status: 200 }),
    );
    const res = await fetchLogin({ username: "op", password: "pw", role: "operator" }, "ws-tok");
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/auth/login",
      expect.objectContaining({
        method: "GET",
        headers: expect.objectContaining({
          Authorization: "Bearer ws-tok",
          "X-Nanobot-Robot-Body": JSON.stringify({ username: "op", password: "pw", role: "operator" }),
        }),
      }),
    );
    expect(res.data.user_token).toBe("utok");
    expect(res.data.user.role).toBe("operator");
  });

  it("fetchLogin: 401 throws (invalid credentials)", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      new Response(JSON.stringify({ error: { code: "invalid_credentials" } }), { status: 401 }),
    );
    await expect(fetchLogin({ username: "x", password: "y", role: "engineer" }, "ws"))
      .rejects.toThrow(/401|invalid/i);
  });

  it("fetchLogout: GET /api/auth/logout with both tokens", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );
    await fetchLogout("ws-tok", "user-tok");
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/auth/logout",
      expect.objectContaining({
        method: "GET",
        headers: expect.objectContaining({
          Authorization: "Bearer ws-tok",
          "X-Nanobot-User-Token": "user-tok",
        }),
      }),
    );
  });
});
```

- [ ] **Step 2: 跑确认失败** — `cd webui && bun run test -- bootstrap 2>&1 | tail -20` → FAIL（`fetchLogin`/`fetchLogout` 不存在）。

- [ ] **Step 3: 写实现**

在 `bootstrap.ts`：
(a) **删除** `SECRET_STORAGE_KEY` 常量 + `loadSavedSecret`/`saveSecret`/`clearSavedSecret` 三个函数。保留 `fetchBootstrap`/`deriveWsUrl`。
(b) 新增（沿用 `fetchWithTimeout` + `robotRequest` 风格 GET+body-header）：
```ts
export interface LoginResponse {
  ok: boolean;
  data: { user_token: string; expires_in: number;
          user: { user_id: string; username: string; role: "operator" | "engineer" } };
}

export async function fetchLogin(
  creds: { username: string; password: string; role: "operator" | "engineer" },
  wsToken: string,
  baseUrl: string = "",
  timeoutMs?: number,
): Promise<LoginResponse> {
  const res = await fetchWithTimeout(`${baseUrl}/api/auth/login`, {
    method: "GET",
    credentials: "same-origin",
    headers: {
      Authorization: `Bearer ${wsToken}`,
      "X-Nanobot-Robot-Body": JSON.stringify(creds),
    },
  }, timeoutMs);
  if (!res.ok) throw new Error(`login failed: HTTP ${res.status}`);
  const body = await res.json();
  if (!body?.data?.user_token) throw new Error("login response missing user_token");
  return body as LoginResponse;
}

export async function fetchLogout(wsToken: string, userToken: string, baseUrl: string = ""): Promise<void> {
  const res = await fetchWithTimeout(`${baseUrl}/api/auth/logout`, {
    method: "GET",
    credentials: "same-origin",
    headers: { Authorization: `Bearer ${wsToken}`, "X-Nanobot-User-Token": userToken },
  });
  if (!res.ok) throw new Error(`logout failed: HTTP ${res.status}`);
}
```
(c) 搜全 webui 对 `loadSavedSecret`/`saveSecret`/`clearSavedSecret` 的引用（App.tsx 等）——F3 会改 App.tsx；本任务若发现**其它**引用，先记录、不擅自改（报告为 DONE_WITH_CONCERNS），由 F3 收口。

- [ ] **Step 4: 跑确认通过** — `cd webui && bun run test -- bootstrap 2>&1 | tail -15` → PASS。
- [ ] **Step 5: 验证（不提交）** — `cd webui && bun run test 2>&1 | tail -20`（App.tsx 等引用 secret 的会红——预期，F3 收口；本任务只要求 bootstrap 测试 + 不引入新 lint）。`cd webui && bunx tsc --noEmit 2>&1 | grep bootstrap` 无新错。

---

## Task F2: `LoginPage` 组件（双 Tab + 表单 + 错误态）

**Files:** Create `webui/src/components/LoginPage.tsx`；Test `webui/src/tests/login-page.test.tsx`。

- [ ] **Step 1: 写失败测试**（shadcn Tabs，参照既有组件测试如 `webui/src/tests/*.test.tsx` 的 render/query 模式）

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { LoginPage } from "@/components/LoginPage";

// 项目用 hash 路由（App.tsx readShellRoute 读 window.location.hash），**非 react-router**。
// 测试直接操作 jsdom 的 window.location.hash，不要引入 react-router/history。

function renderWithHash(hash: string) {
  window.location.hash = hash;
  return render(<LoginPage onSubmit={vi.fn()} bootstrapOk={true} />);
}

describe("LoginPage", () => {
  it("default tab is operator when no hash", () => {
    window.location.hash = "";
    render(<LoginPage onSubmit={vi.fn()} bootstrapOk={true} />);
    expect(screen.getByRole("tab", { name: /操作员|operator/i })).toHaveAttribute("aria-selected", "true");
  });

  it("#/engineer preselects engineer tab (URL priority over default operator)", () => {
    renderWithHash("#/engineer");
    expect(screen.getByRole("tab", { name: /工程师|engineer/i })).toHaveAttribute("aria-selected", "true");
  });

  it("username field starts empty (never prefilled)", () => {
    render(<LoginPage onSubmit={vi.fn()} bootstrapOk={true} />);
    expect((screen.getByPlaceholderText(/用户名|username/i) as HTMLInputElement).value).toBe("");
  });

  it("submit disabled when username or password empty", () => {
    render(<LoginPage onSubmit={vi.fn()} bootstrapOk={true} />);
    expect(screen.getByRole("button", { name: /登录|login/i })).toBeDisabled();
  });

  it("switching tab clears username + password + error", () => {
    render(<LoginPage onSubmit={vi.fn()} bootstrapOk={true} />);
    const user = screen.getByPlaceholderText(/用户名|username/i) as HTMLInputElement;
    fireEvent.change(user, { target: { value: "abc" } });
    fireEvent.click(screen.getByRole("tab", { name: /工程师|engineer/i }));
    expect((screen.getByPlaceholderText(/用户名|username/i) as HTMLInputElement).value).toBe("");
  });

  it("bootstrap failed shows connection error, not credential error, and disables submit", () => {
    render(<LoginPage onSubmit={vi.fn()} bootstrapOk={false} />);
    expect(screen.getByText(/无法建立控制台连接|cannot establish/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /登录|login/i })).toBeDisabled();
  });

  it("401 shows generic credential error; on submit calls onSubmit with role+creds", async () => {
    const onSubmit = vi.fn();
    render(<LoginPage onSubmit={onSubmit} bootstrapOk={true} error={{ status: 401 }} />);
    fireEvent.change(screen.getByPlaceholderText(/用户名|username/i), { target: { value: "op" } });
    fireEvent.change(screen.getByPlaceholderText(/密码|password/i), { target: { value: "pw" } });
    fireEvent.click(screen.getByRole("button", { name: /登录|login/i }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ username: "op", password: "pw", role: expect.stringMatching(/operator|engineer/) })));
    expect(screen.getByText(/用户名或密码错误|invalid credentials/i)).toBeInTheDocument();
  });
});
```
> 注：tab 文案用 shadcn `Tabs`（`aria-selected`）；i18n key 见 Step 3。若项目不用 `react-router`（hash 路由是手写的，见 App.tsx `readShellRoute`），测试里直接操作 `window.location.hash` 即可（jsdom 支持）——不要引入 react-router。

- [ ] **Step 2: 跑确认失败** — `cd webui && bun run test -- login-page 2>&1 | tail -20` → FAIL（组件不存在）。

- [ ] **Step 3: 写实现** `webui/src/components/LoginPage.tsx`：
- shadcn `Tabs`（两 Tab：操作员/工程师）；默认按 `window.location.hash`（`#/engineer`→engineer，`#/operator` 或其它→operator）；切 Tab 清 `username`/`password`/`error`。
- `username`（`Input`，空起始，**不预填**）+ `password`（`Input type=password`）。空任一 → 提交 `Button` 置灰。
- props: `{ bootstrapOk: boolean; error?: { status?: number; retryAfter?: number } | null; onSubmit: (creds: {username,password,role}) => void; }`。
- 错误态文案（i18n，新增 key）：`bootstrapOk=false` → "无法建立控制台连接"（置灰提交）；`error.status===401||403(role)` → "用户名或密码错误"（清密码、留用户名、焦点回密码）；`403 user_disabled` → "账户已禁用，请联系工程师"；`429` → "尝试过多，{N}s 后再试"（按钮置灰 + 倒计时，N 来自 `error.retryAfter`）；`5xx` → "服务暂不可用，请稍后重试"。
- 失败后：清密码、保留用户名、焦点回密码框（401/403/429）；5xx 保留输入。

- [ ] **Step 4: 跑确认通过** — `cd webui && bun run test -- login-page 2>&1 | tail -20` → PASS（7 测试，0 skip）。
- [ ] **Step 5: 验证（不提交）** — `cd webui && bunx tsc --noEmit 2>&1 | grep -i "LoginPage\|login-page" ` 无错。

---

## Task F3: `App.tsx` — BootState + shell-by-role + 跨角色重定向 + bootstrap-first + 接 LoginPage

**Files:** Modify `webui/src/App.tsx`（重点：`BootState` :56-67、`AuthForm` :219-271、`bootstrapWithSecret` :403、`shouldUseRobotOperatorApp` :200、Shell 分支 :542-557、`handleLogout` :518）；Test `webui/src/tests/app-layout.test.tsx`（既有，扩展）。

> **执行者须知：** App.tsx 1698 行，本任务多处外科手术式改动。先完整读 `BootState` 定义、`AuthForm`、`bootstrapWithSecret`、`shouldUseRobotOperatorApp`、render 末尾的 Shell 分支、`handleLogout`，再动手。

- [ ] **Step 1: 写失败测试（追加到 app-layout.test.tsx 或新 app-auth.test.tsx）**

```tsx
import { describe, it, expect, vi } from "vitest";
// 参照既有 app-layout.test.tsx 的 render App + mock client/bootstrap 模式

it("BootState.auth renders LoginPage (not legacy AuthForm secret field)", () => {
  // mock fetchBootstrap to reject/unavailable → state auth
  // assert: LoginPage 的 Tab 出现；旧 "secret/password" 单字段不出现
});

it("shell is driven by user.role: engineer role also renders RobotSidePanel (same shell)", () => {
  // mock login as engineer → state ready with user.role=engineer
  // assert: RobotSidePanel 存在（两角色同壳）
});

it("operator hash #/engineer redirects back to #/operator", () => {
  // mock operator logged in, set location.hash=#/engineer
  // assert: hash 重定向回 #/operator
});

it("login success stores wsToken+userToken+user in memory; localStorage has no tokens", () => {
  // mock bootstrap+login success
  // assert: window.localStorage 不含 user_token/ws_token/secret
});
```
> 按既有 app-layout.test.tsx 的 mock 套路（它如何 mock `fetchBootstrap`/`NanobotClient`/`window.location.hash`）补全实现；**0 skip**。

- [ ] **Step 2: 跑确认失败** → FAIL。

- [ ] **Step 3: 写实现**（外科手术）：
(a) `BootState`：`auth` 分支保留；`ready` 分支增加 `userToken: string` + `user: {user_id,username,role}`（既有 `token` 重命名为 `wsToken` 或保留 `token` 并加 `userToken`——**保留 `token` 名以减少 ClientProvider 改动**，新增 `userToken`+`user`）。`loading`/`error` 保留，新增 `bootstrapError` 子态。
(b) 删 `AuthForm`（:219-271）+ `bootstrapSecretRef`（:365）；`auth` 渲染改用 `<LoginPage bootstrapOk={!bootstrapError} error={...} onSubmit={handleLogin} />`。
(c) 新增 `handleBootstrap()`：`fetchBootstrap()`（**localhost 免密，不传 secret**）→ 拿 ws_token → `setState({status:"auth"})`；失败 → `setState({status:"auth", bootstrapError:true})`（LoginPage 显示"无法建立控制台连接"）。`useEffect` 启动调 `handleBootstrap`（取代 `bootstrapWithSecret(loadSavedSecret())`）。
(d) 新增 `handleLogin({username,password,role})`：`fetchLogin(creds, wsToken)` → 成功：`setState({status:"ready", client, token:wsToken, userToken, user, ...})` 并 `client.setAuthToken(userToken)`（F6 加）+ `client.connect()`；失败：按 status 映射 `{status, retryAfter}` 喂给 LoginPage（`setState({status:"auth", loginError})`）。
(e) `shouldUseRobotOperatorApp`（:200）：**改为** `state.user.role === "operator"`（shell 由 session 角色驱动）。删 `runtimeSurface`/`hash` 入参语义（保留函数名或内联）。
(f) render 末尾 Shell 分支（:542-557）：**两角色都渲染 `rightPanel={<RobotSidePanel token={state.token} />}`**（工程师侧面板不隐藏）；移除 operator/engineer 分支差异。
(g) 跨角色 hash 重定向 `useEffect`：若 `user.role==="operator"` 且 `location.hash` 以 `#/engineer` 开头 → `location.hash="#/operator"`（反之 engineer→`#/engineer`）。
(h) `handleLogout`（:518）：`fetchLogout(wsToken, userToken)` → `client.close()` → `setState({status:"auth"})`（回登录页；**不删 localStorage**——本就不存）。
(i) 登录成功后跳转：`role===operator` → `#/operator`；`engineer` → `#/engineer`。
(j) `ClientProvider` 透传 `userToken`+`user`（F6 改 Provider 签名，App 传新 props）。

- [ ] **Step 4: 跑确认通过** — `cd webui && bun run test -- app-layout 2>&1 | tail -20` → PASS（含新断言）。既有 app-layout 用例若因"shell 不再按 hash 分支/无 secret"红 → 按新语义修夹具（不弱化断言、不 skip）。
- [ ] **Step 5: 验证（不提交）** — `cd webui && bunx tsc --noEmit 2>&1 | tail -10` 无新错。

---

## Task F4: `api.ts` — `X-Nanobot-User-Token` on session calls + `listSessions(ws,user)`

**Files:** Modify `webui/src/lib/api.ts`（`listSessions` :102、`fetchWebuiThread` :~150、`apiDeleteSession`、`fetchSessionAutomations`、rename/archive 等 session-key 调用）；Test `webui/src/tests/api.test.ts`（既有，扩展）。

- [ ] **Step 1: 写失败测试**
```ts
it("listSessions sends X-Nanobot-User-Token + Bearer wsToken", async () => {
  globalThis.fetch = vi.fn().mockResolvedValue(new Response('{"sessions":[]}', {status:200}));
  await listSessions("ws-tok", "user-tok");
  const [, init] = (globalThis.fetch as any).mock.calls[0];
  expect(init.headers.Authorization).toBe("Bearer ws-tok");
  expect(init.headers["X-Nanobot-User-Token"]).toBe("user-tok");
});
it("fetchWebuiThread sends X-Nanobot-User-Token", async () => {
  globalThis.fetch = vi.fn().mockResolvedValue(new Response('{"messages":[]}', {status:200}));
  await fetchWebuiThread("ws", "user", "websocket:k");
  expect((globalThis.fetch as any).mock.calls[0][1].headers["X-Nanobot-User-Token"]).toBe("user");
});
```
- [ ] **Step 2: 跑确认失败** → FAIL。
- [ ] **Step 3: 写实现** — 所有 session-key REST 调用签名加 `userToken: string`，headers 加 `"X-Nanobot-User-Token": userToken`（沿用既有 `Authorization: Bearer ${token}`）。覆盖：`listSessions`、`fetchWebuiThread`、`apiDeleteSession`、`fetchSessionAutomations`、及任何 `/api/sessions/...` 调用。调用方（useSessions、App、ThreadShell 等）相应传 `userToken`（从 `useClient()` 取——F6 透传）。
- [ ] **Step 4: 跑确认通过** — `cd webui && bun run test -- api 2>&1 | tail -15` → PASS。调用方 typecheck 错由 F3/F5/F6 收口。
- [ ] **Step 5: 验证（不提交）** — `bunx tsc --noEmit`（跨文件 type 错在 F3-F6 收口）。

---

## Task F5: `useSessions(namespace)` + `useSidebarState(namespace)`

**Files:** Modify `webui/src/hooks/useSessions.ts`、`useSidebarState.ts`；Test 既有 hooks 测试扩展。

- [ ] **Step 1: 写失败测试**
```ts
it("useSessions scopes list to namespace", async () => {
  // mock listSessions 返回 [a,b]；useSessions(ns="engineer:u1") 只暴露该 ns
});
it("useSidebarState keys localStorage by namespace (per-user isolation)", () => {
  // 两个 namespace 的 sidebar state 互不串（localStorage 键含 ns）
});
```
- [ ] **Step 2: 跑确认失败** → FAIL。
- [ ] **Step 3: 写实现**：
- `useSessions()` 从 `useClient()` 取 `userToken`+`user`，派生 `namespace = \`${user.role}:${user.user_id}\``，传给 `listSessions(wsToken, userToken)`（服务端已按 user_token 派生过滤——前端 namespace 主要用于 sidebar state 隔离 + useSessions 不再混用）。
- `useSidebarState`：localStorage 键加 namespace 后缀（如 `nanobot-webui.sidebar.<ns>`），各用户置顶/归档/重命名互不串。`fetchSidebarState`/`persistSidebarState` 加 `X-Nanobot-User-Token`（若这些端点也门控；sidebar-state 是 `/api/webui/sidebar-state`，非 session-key，**确认是否需 user_token**——若后端 sidebar-state 也按用户存，则加；否则仅 localStorage 键隔离）。
- [ ] **Step 4: 跑确认通过** → PASS。
- [ ] **Step 5: 验证（不提交）** — tsc。

---

## Task F6: `ClientProvider`（userToken/user）+ `NanobotClient`（auth 首帧 + 缓冲 + auth_ok + 重连重发 + 失败信号）— **解除 auth_required 的核心**

**Files:** Modify `webui/src/lib/nanobot-client.ts`、`webui/src/providers/ClientProvider.tsx`；Test `webui/src/tests/client-auth.test.ts`（新，用 `socketFactory` 注入）。

> **执行者须知：** 读 `connect()`(:284)/`handleOpen`(:435)/`handleMessage`(:447，`ready`/`attached`/`error` 分支)/`queueSend`(:658)/`scheduleReconnect`(:638，`onReauth`)。核心：`auth` 必须是每条连接的首个业务帧；未 auth 完成前缓冲所有业务帧（含 reconnect 的 re-attach）。

- [ ] **Step 1: 写失败测试（用 socketFactory 注入假 WebSocket，0 skip）**

```ts
import { describe, it, expect, vi } from "vitest";
import { NanobotClient } from "@/lib/nanobot-client";

class FakeSocket {
  sent: any[] = [];
  onopen: ((ev:any)=>void)|null = null;
  onmessage: ((ev:any)=>void)|null = null;
  onclose: ((ev:any)=>void)|null = null;
  onerror: ((ev:any)=>void)|null = null;
  readyState = 0; // CONNECTING
  send(data:string){ this.sent.push(JSON.parse(data)); }
  close(){ this.readyState = 3; }
  // test helper: simulate server
  fireOpen(){ this.readyState=1; this.onopen?.({}); }
  recv(obj:any){ this.onmessage?.({ data: JSON.stringify(obj) }); }
}

describe("NanobotClient auth first-frame", () => {
  it("on open, sends auth {user_token} BEFORE any new_chat/attach", () => {
    const sock = new FakeSocket();
    const client = new NanobotClient({ url: "ws://x", socketFactory: () => sock });
    client.setAuthToken("user-tok");
    client.connect();
    sock.fireOpen();            // server ready
    // 服务端还没发 auth_ok；客户端此时若发 new_chat 应被缓冲，不应出现在 sock.sent
    client.newChat(1000);
    expect(sock.sent.map(f=>f.type)).toEqual(["auth"]); // 只有 auth，new_chat 被缓冲
    expect(sock.sent[0]).toEqual({ type:"auth", user_token:"user-tok" });
  });

  it("after auth_ok, flushes buffered business frames (new_chat proceeds)", async () => {
    const sock = new FakeSocket();
    const client = new NanobotClient({ url:"ws://x", socketFactory:()=>sock });
    client.setAuthToken("user-tok");
    client.connect(); sock.fireOpen();
    const p = client.newChat(1000);
    sock.recv({ event:"auth_ok", role:"operator", user_id:"u1" }); // 服务端确认
    sock.recv({ event:"attached", chat_id:"c1" });                 // new_chat 响应
    await expect(p).resolves.toBe("c1");
    // auth_ok 后才发了 new_chat
    expect(sock.sent.map(f=>f.type)).toEqual(["auth","new_chat"]);
  });

  it("auth_ok carries no chat_id (no default chat) — readyChatId stays null until new_chat", () => {
    const sock = new FakeSocket();
    const client = new NanobotClient({ url:"ws://x", socketFactory:()=>sock });
    client.setAuthToken("t"); client.connect(); sock.fireOpen();
    sock.recv({ event:"ready", client_id:"c" });
    sock.recv({ event:"auth_ok", role:"engineer", user_id:"u" });
    expect(client.defaultChatId).toBeNull();
  });

  it("server auth_failed/auth_required close → client surfaces auth-failed signal", async () => {
    const sock = new FakeSocket();
    const onAuthFailed = vi.fn();
    const client = new NanobotClient({ url:"ws://x", socketFactory:()=>sock, reconnect:false, onAuthFailed });
    client.setAuthToken("bad"); client.connect(); sock.fireOpen();
    sock.recv({ event:"error", detail:"auth_failed" });
    // 服务端随后 close 1008
    sock.readyState=3; sock.onclose?.({ code:1008 });
    expect(onAuthFailed).toHaveBeenCalled();
  });

  it("reconnect re-sends auth (binding does not persist across connections)", async () => {
    const sock1 = new FakeSocket();
    const client = new NanobotClient({ url:"ws://x", socketFactory:()=>sock1, reconnect:false });
    client.setAuthToken("t"); client.connect(); sock1.fireOpen();
    sock1.recv({ event:"auth_ok", role:"operator", user_id:"u" });
    // 模拟重连：新 socket
    const sock2 = new FakeSocket();
    client.updateUrl("ws://x2", () => sock2);
    client.connect(); sock2.fireOpen();
    expect(sock2.sent.map(f=>f.type)).toEqual(["auth"]); // 重连后第一帧又是 auth
  });
});
```

- [ ] **Step 2: 跑确认失败** — `cd webui && bun run test -- client-auth 2>&1 | tail -20` → FAIL（`setAuthToken`/`onAuthFailed`/缓冲 不存在）。

- [ ] **Step 3: 写实现** `nanobot-client.ts`：
(a) 新增字段：`private authToken: string | null = null;` + `private authed = false;` + `private authPending = false;`。
(b) 新增 `setAuthToken(token: string): void { this.authToken = token; }`。
(c) `NanobotClientOptions` 加 `onAuthFailed?: () => void`（auth 失败回调，App 用来回登录页）。
(d) `handleOpen()`（:435）重写：**先发 `auth`**：
```ts
private handleOpen(): void {
  this.setStatus("open");
  this.reconnectAttempts = 0;
  this.authed = false;
  this.authPending = true;
  this.rawSend({ type: "auth", user_token: this.authToken ?? "" });
  // 不在此处 re-attach / flush —— 等 auth_ok
}
```
(e) `handleMessage`（:447）：新增 `auth_ok` 分支（在 `ready` 分支之后）：
```ts
if (parsed.event === "auth_ok") {
  this.authed = true;
  this.authPending = false;
  // auth 成功后才 re-attach 已知 chat + flush 缓冲
  for (const chatId of this.knownChats) this.rawSend({ type:"attach", chat_id: chatId });
  const queued = this.sendQueue.splice(0);
  for (const frame of queued) this.rawSend(frame);
  return;
}
```
`ready` 分支（:466）：B4 的 `ready` 只有 `client_id`（无 `chat_id`）——删 `this.readyChatId = parsed.chat_id`（改为不设，或仅记 client_id）；`readyChatId` 改为只在 `new_chat`→`attached` 后由调用方管理（或保留 null）。
(f) `queueSend`（:658）：未 auth 完成时一律入队（即使 socket OPEN）：
```ts
private queueSend(frame: Outbound): void {
  if (this.socket?.readyState === WS_OPEN && this.authed && !this.authPending) {
    this.rawSend(frame);
  } else {
    this.sendQueue.push(frame);
  }
}
```
（`auth` 帧本身在 handleOpen 用 `rawSend` 直发，不走 queueSend。）
(g) `handleClose`（:574）：若 close code 1008（auth 相关）且 `!this.authed` → 调 `this.options.onAuthFailed?.()`（不再 reconnect）。其它 close 走既有 reconnect。
(h) `scheduleReconnect`（:638）的 `onReauth` 回调：既有刷新 URL（ws_token）保留；重连后 `handleOpen` 会自动重发 `auth`（用现存 `authToken`）。若 `authToken` 已过期（8h）→ 服务端 `auth_failed` close → onAuthFailed → App 重登。

`ClientProvider.tsx`：`ClientContextValue` 加 `userToken: string; user: { user_id:string; username:string; role:"operator"|"engineer" }`；`ClientProvider` props 加同名；`useClient()` 透传。App.tsx（F3）传入。

- [ ] **Step 4: 跑确认通过** — `cd webui && bun run test -- client-auth 2>&1 | tail -20` → PASS（5 测试，0 skip）。
- [ ] **Step 5: 验证（不提交）** — `cd webui && bunx tsc --noEmit 2>&1 | tail -10` 无错；`cd webui && bun run test 2>&1 | tail -20` 既有 client 测试不回归（既有用例若依赖 `ready.chat_id`/无 auth 帧 → 按新语义修夹具：注入 setAuthToken + 喂 auth_ok）。

---

## Task F7: vitest 全绿 + typecheck + build（前端收尾，B9 前关卡）

- [ ] **Step 1: 全量 vitest** — `cd webui && bun run test 2>&1 | tail -30` → 全绿（0 fail，0 skip）。既有用例若因 auth/secret/shell-by-role 红 → 按 F3/F6 新语义修夹具，不弱化、不 skip。
- [ ] **Step 2: typecheck** — `cd webui && bunx tsc --noEmit 2>&1 | tail -15` → 0 error。
- [ ] **Step 3: build** — `cd webui && bun run build 2>&1 | tail -15` → 成功（产出 `dist`）。
- [ ] **Step 4: 验证（不提交）** — 确认无 git 操作；记录 Plan B 完成。
- [ ] **Step 5: 移交 B9** — Plan B 完成；B9（前后端统一回归 + 修剩余后端 channels/webui 测试 + pytest + vitest + ruff）作为最终关卡。**B9 仍遵守零进程管理**：只跑 pytest/vitest/ruff/build，不起 gateway；若需前后端联调冒烟，由**用户**手动起 gateway（用户批准后我只读观察，不启不杀）。

---

## 自查（Plan B vs spec + 约束）

| spec / 约束 | 任务 |
|---|---|
| §2 双 Tab 登录页（默认操作员/URL 预选/切 Tab 全清/用户名空起始/错误态） | F2 |
| §3 shell 由 role 驱动 + 跨角色 hash 重定向 + 刷新重登 + 登出 | F3 |
| §4 token 流 bootstrap→login→user_token→WS auth | F1（fetchLogin）+ F3（App 编排）+ F6（WS auth 首 帧） |
| §4 bootstrap 失败="无法建立控制台连接"不报凭据错 | F2（bootstrapOk=false）+ F3（bootstrapError） |
| §5 WS auth 首帧 + 重连重发 + auth 失败信号 | F6 |
| §6 namespace 隔离（前端只发 user_token，服务端派生） | F4（X-Nanobot-User-Token）+ F5（hooks） |
| §9 前端改动清单 | F1-F6 一一对应 |
| 全程 NO GIT | 硬约束 + 每任务"不提交" |
| 零进程管理（不起/杀 gateway） | 硬约束 + B9 冒烟由用户手动 |
| 测试 0 skip | F1-F6 用 socketFactory/vi.mock 假实现 |

**类型一致性**：`fetchLogin(creds, wsToken)`（F1 定义，F3 调用）；`LoginPageProps{bootstrapOk,error,onSubmit}`（F2 定义，F3 使用）；`BootState.ready.{token(=ws),userToken,user}`（F3，F6 ClientProvider 透传）；`listSessions(wsToken,userToken)`（F4，F5 调用）；`client.setAuthToken(token)`+`onAuthFailed`（F6，F3 设置/订阅）。

**诚实声明**：vitest 的 render/mock 细节（react-router vs hash、shadcn Tabs 的 aria、既有 app-layout.test.tsx 的 mock 套路）执行 subagent 须读 `webui/src/tests/` 既有测试对齐；测试**意图与关键断言**已完整给出（含 socketFactory 假 WebSocket 的 5 个 client-auth 用例），不是占位。
