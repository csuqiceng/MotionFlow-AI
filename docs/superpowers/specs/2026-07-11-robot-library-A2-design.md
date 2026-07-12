# 机器人命令/流程库 — A2 操作员只读前端设计

日期：2026-07-11
状态：已确认，待实施计划
关联：A1 后端已完成（`2026-07-11-robot-library-A1-design.md`，命令/组件只读 API）。父草案 `2026-07-11-robot-knowledge-and-engineer-console-design-draft.md`。本文件是操作员只读视图切片；工程师后台（组件库→命令库→流程库 三层 + 鉴权 + 发布）后续单独做。

## 1. 目标与边界

A2 给操作员一个**只读命令库**：从共享 `Sidebar.tsx` 移除 Apps/Skills、新增「命令库」入口 → `#/library` 页面（命令/流程两页签，列表+筛选+详情）；后端补一个**只读流程 list/detail API**。**不**做组件库 UI（组件不面向操作员）、**不**做编辑/发布/归档/删除/执行、**不**改 `RobotOperatorApp`/`RobotSidePanel`/聊天/确认/执行链路。

**In scope：**
- `Sidebar.tsx`：移除 Apps/Skills 按钮（及其 props/handlers），新增「命令库」按钮。
- `App.tsx`：`ShellView += "library"`、路由 `#/library`、`onOpenLibrary`、`view==="library"` 渲染库页面、`rightPanel` 门控（`view !== "library" && rightPanel`）。
- 库页面：`webui/src/robot/library/`（`CommandLibraryPage` + `LibraryList` + `CommandDetail` + `FlowDetail`）。
- `webui/src/robot/hooks/useRobotLibrary.ts`：按页签拉 list + 筛选 + 选中 detail。
- `webui/src/lib/robot-library-api.ts`：4 个 API 函数（commands/command/flows/flow）。
- 后端：只读 `GET /api/robot/library/flows` + `GET /api/robot/library/flows/{name}`（`robot_routes.py` + `ws_http.py`）。
- 后端：命令库**首次启动自动播种**（gateway 启动时从打包的 `robot_ai/library/seed_query_table.json` 幂等迁移；见 §3.1）。
- i18n keys（`sidebar.commandLibrary` + `library.*`）。
- 测试：后端 pytest + 前端 vitest，含 `rightPanel` 门控回归测试。

**Out of scope：**
- 组件库 UI（留给工程师后台）。
- 编辑/发布/归档/删除/执行、工程师鉴权、角色路由保护。
- 流程步骤升级为 `{command_id, version}` → 阶段 C。
- 真机写入、改 `FlowRegistry` 模型/执行/控制器链路。
- 删除 Settings 内的 apps/skills 子页或 `#/apps`、`#/skills` 直接路由（A2 仅移除左栏按钮）。

**硬约束：** 不修改 `RobotOperatorApp.tsx`、`RobotSidePanel.tsx`、聊天/确认/执行链路、`robot_ai/flow/`（FlowRegistry 只读）、真实执行链路。

## 2. 可复用基础

- A1 后端：`/api/robot/library/commands`、`/commands/{id}`、`/components`、`/components/{id}`（已实现，token 闸门）。
- `robot_ai/flow/registry.py` `FlowRegistry`：`list_all()` / `get(name)`，文件 `~/.nanobot/robot_ai/flows.json`，case-insensitive by name。**只读使用**。
- `ws_http._dispatch_robot_library_routes`（A1）：扩展加 flow 路径，继承同一 `check_api_token` 闸门。
- `Sidebar.tsx` `SidebarActionButton` 模式；`App.tsx` Shell 的 view-gating（ThreadShell 常驻 + `view!=="chat"` 渲染 SettingsView）、`rightPanel` prop、`isOperatorConsole`。
- `robot-api.ts` `robotRequest`/`fetchWithTimeout` 模式（GET + Bearer）。
- `useRobotStatus` hook 模式（token 入参）——`useRobotLibrary` 用按需 fetch（无轮询）。
- vitest：happy-dom、`vi.mock("@/providers/ClientProvider")`、`vi.stubGlobal("fetch")`、`@testing-library/react` `render`/`renderHook`。
- i18n：`webui/src/i18n/locales/{en,zh-CN}/common.json` `sidebar` 命名空间。

## 3. 后端：只读流程 API

```
GET /api/robot/library/flows           -> {ok:true, data:{items:[FlowEntry...], total}}
GET /api/robot/library/flows/{name}    -> {ok:true, data:FlowEntry} | 404
```

- `nanobot/api/robot_routes.py`：新增 `process_robot_library_flows(*, flow_registry_path)` 与 `process_robot_library_flow(name, *, flow_registry_path)` + `handle_robot_library_flows` / `handle_robot_library_flow` + 注册到 `register_robot_routes`。复用既有 `_resolve_flow_registry_path` / `DEFAULT_FLOW_REGISTRY_PATH`。
- `nanobot/webui/ws_http.py`：`_dispatch_robot_library_routes` 加 flow 路径——正则 `^/api/robot/library/flows/([^/]+)$`（detail）+ 精确 `/api/robot/library/flows`（list）；dispatch 调 `process_robot_library_flow(s)`；继承 token 闸门；`{name}` 经 `unquote`。
- 流程详情返回 `FlowEntry.to_dict()`：`name/description/steps[{step_id,action,func_id,params,position_name,spd_pct,description}]/step_delay_ms/rehearsal_spd/confirmed/version/state/current_step/created_by/created_at/updated_at`。**步骤形状保持现状**（`func_id/params`），不升级为 `{command_id,version}`。
- **只读**：每次请求 `FlowRegistry(path)` 构造，仅 `list_all()`/`get()`，**不**调用 `_save`/任何写方法。

### 3.1 命令库自动播种（gateway 首次启动）

`commands.json` 不随包发布；gateway 首次启动时从打包种子幂等播种，规则：

- `~/.nanobot/robot_ai/commands.json` **已存在**：绝不覆盖（no-op）。
- **不存在**：从打包资源 `robot_ai/library/seed_query_table.json`（= legacy `query_table.json` 的 21 条记录副本，随 wheel 发布）执行 `migrate_commands` → 16 条 published v1 + 5 跳过 + 审计。
- 种子资源缺失或迁移失败：记录明确错误（loguru），**不**静默得到空库（库为空但错误已记入日志）。
- **不**自动迁移 flows——`migrate_robot_flows.py` 用 `FlowRegistry.replace()` 是破坏性覆写，会冲掉手工维护的 `flows.json`；flows.json 是唯一事实源。
- 实现：`robot_ai/library/migration.py` 新增 `seed_command_library_if_missing(commands_path, audit_path, *, seed_path=None, log=None) -> bool`；在 `_run_gateway`（`nanobot/cli/commands.py`）启动时调用一次（**不**挂 `build_gateway_services`——5 个 websocket 测试会调它，挂那里会向真实 `~/.nanobot` 写入）。`DEFAULT_COMMANDS_PATH`/`DEFAULT_AUDIT_PATH` 移至 `robot_ai/library/migration.py`，`robot_routes.py` 改为 import（避免重复定义）。种子 `seed_query_table.json` 必须在 Hatch `[tool.hatch.build] include` 中显式列出（默认 include 仅 `robot_ai/**/*.py`，不含 JSON）。

## 4. 前端 — Sidebar（`Sidebar.tsx`）

- 移除 Apps、Skills 两个 `SidebarActionButton`（当前 157-170 行区域）。
- 移除 `SidebarProps` 的 `onOpenApps`/`onOpenSkills` + Shell `sidebarProps` 中对应项 + Shell 的 `onOpenApps`/`onOpenSkills` handlers（定向清理，不留死代码）。
- 新增「命令库」按钮：icon `BookOpen`（lucide），`onClick={props.onOpenLibrary}`，`active={props.activeUtility === "library"}`，位置在 Search 之后、Automations 之前。
- `SidebarProps` 加 `onOpenLibrary: () => void`；`activeUtility` 联合类型加 `"library"`。
- 保留 NewChat/Search/Automations/Settings/会话列表/归档等不变。

## 5. 前端 — 路由与 Shell（`App.tsx`）

- `ShellView` 加 `"library"`。
- `readShellRoute`：`if (path === "/library") return {view:"library", activeKey, settingsSection:"overview"};`。
- `shellRouteHash`：`view==="library"` → `#/library`（携带 `?chat=` 若有 activeKey）。
- `onOpenLibrary` handler → `navigate({view:"library", activeKey, settingsSection:"overview"})`。
- 中心区渲染拆分当前 `view !== "chat"` 的 SettingsView 块：
  - `view === "library"` → `<CommandLibraryPage token={token} />`。
  - `view === "settings" | "apps" | "automations" | "skills"` → 既有 `SettingsView`。
  - `view === "chat"` → ThreadShell（既有，常驻+invisible 机制不变）。
- **rightPanel 门控**：`{view !== "library" && rightPanel}`——库页隐藏 `RobotSidePanel`，让列表+详情占满中间+右侧；`RobotSidePanel` 组件本身不改，其它视图照常显示。
- `shouldUseRobotOperatorApp` 不改（operator 入口逻辑不变；`#/library` 在 native 下仍走 operator Shell，但 rightPanel 被 view 门控隐藏）。

## 6. 前端 — 库页面（`webui/src/robot/library/`）

- `CommandLibraryPage.tsx`：顶部「命令/流程」两页签；左列固定 ~300px（`w-72`）含搜索框 + 筛选 + 列表；右列详情区。桌面操作台定位，**固定列表宽度，不做窄窗抽屉**。
- `LibraryList.tsx`：搜索输入 + 筛选下拉（命令：`component_id`/`risk_level`；流程：**本地 `q` 搜索**匹配 name/description，无服务端筛选）+ 列表项（name + 副标题）。
- `CommandDetail.tsx`：`name/aliases/description/component_id/parameters(表)/risk_level/status/version`——只读。
- `FlowDetail.tsx`：`name/description/steps(有序：step_id/action/func_id/params 摘要)/state/version/confirmed`——只读。
- `useRobotLibrary.ts`：当前页签 + 筛选 + 选中 id；按页签拉 list（commands|flows）+ 选中后拉 detail；token 入参；`loading`/`error` 态；**无轮询**（按需 fetch）。**flows 页签的 `q` 为本地筛选**（拉全量后按 name/description 子串过滤）；commands 的筛选走服务端。切换页签时同步清空 items（避免旧 items 在新页签下错配渲染）。
- `webui/src/lib/robot-library-api.ts`：
  - `robotLibraryCommands(token, {component_id?, risk_level?, status?, q?})` → `GET /api/robot/library/commands?...`
  - `robotLibraryCommand(token, id)` → `GET /api/robot/library/commands/{id}`
  - `robotLibraryFlows(token)` → `GET /api/robot/library/flows`
  - `robotLibraryFlow(token, name)` → `GET /api/robot/library/flows/{name}`
  - 复用 `robot-api.ts` 的 `robotRequest`/`fetchWithTimeout`（GET + Bearer）；导出 `LibraryCommand`/`LibraryFlow`/`LibraryListResponse<T>` 类型。

## 7. i18n

`webui/src/i18n/locales/{en,zh-CN}/common.json`：
- `sidebar.commandLibrary`：`"命令库"` / `"Commands"`。
- `library.tabs.commands` / `library.tabs.flows`；`library.filters.*`（component/risk/confirmed/state）；`library.empty.*`；`library.error.*`。

## 8. 安全

- 所有 library 端点（含新 flow 端点）经 `ws_http._dispatch_robot_routes` 的中心 `check_api_token` 闸门；无 token → 401。
- 只读：无写入、无执行、不访问控制器。Flow API 仅读 `flows.json` 文件。

## 9. 测试

**后端 pytest（`.venv-robot-desktop`）：**
- 扩展 `tests/robot_ai/test_robot_library_routes.py`：flow list（空 + 用 tmp `FlowRegistry` 播种）、flow detail found + 404、非法 path。
- 扩展 `tests/robot_ai/test_ws_http_library_routes.py`：flow list/detail 路径匹配 + token 闸门 + `?version=` 拒绝。
- Flow 数据用 `FlowRegistry(tmp).add(FlowEntry(...))` 播种（镜像 `test_flow_registry.py`）。
- **命令库自动播种**（`tests/robot_ai/test_library_migration.py` 扩展）：首次启动（commands.json 缺失）→ 16 条 + 审计；二次启动（commands.json 已存在且含自定义命令）→ 不覆盖、自定义命令保留；种子缺失（`seed_path` 指向不存在文件）→ 安全失败（不抛、库为空、返回 False）。

**前端 vitest（happy-dom）：**
- `test_robot_library_api.ts`：4 函数、fetch mock、URL+query 正确、信封解析、错误抛出。
- `test_use_robot_library.ts`：`renderHook`、按页签拉 list、筛选、选中→detail fetch、loading/error、**flows 页签 `q` 本地搜索**（按 name/description 过滤）、**切页签清空旧 items**。
- `test_command_library_page.tsx`：render、页签切换（命令/流程）、列表 render、选中→detail render、空/错误态。
- `test_sidebar_library_nav.tsx`（或扩 `app-layout.test.tsx`）：Apps/Skills 按钮缺失、命令库按钮存在、点击→`#/library`。
- **`rightPanel` 门控回归测试（必需）**：
  - (a) 在 `#/operator`（native surface）挂载 → `RobotSidePanel` 渲染（rightPanel 已注入）；随后 hash 切到 `#/library` → 断言：共享 `Sidebar` 仍在、`RobotSidePanel` **不**渲染、`CommandLibraryPage` 渲染。
  - (b) 直接在 `#/library`（native）挂载 → 断言相同库布局（`Sidebar` + 库页面、无 `RobotSidePanel`）。
  - 覆盖「rightPanel 由初始 `#/operator` 注入、经 hash 切到 library」的真实路径。

## 10. 验收标准

- `Sidebar`：无 Apps/Skills 按钮；命令库按钮存在；点击 → `#/library`。
- `#/library`：`CommandLibraryPage` 含命令/流程页签；命令列表+筛选+详情、流程列表+本地 `q` 搜索+详情；只读。
- `RobotSidePanel` 在库页隐藏（`#/operator`→库 与直接 `#/library` 两种路径皆然）。
- 命令库自动播种：gateway 首次启动 `commands.json` 缺失 → 16 条；已存在 → 不覆盖；种子缺失 → 记录错误不静默空库。
- Flow API：list/detail 只读、token 闸门、404。
- 库页面固定列表宽度（无窄窗抽屉）。
- 聊天/确认/执行链路不变；`RobotOperatorApp`/`RobotSidePanel` 不变；`FlowRegistry` 只读。
- 后端 pytest + 前端 vitest 全过；`ruff` clean；前端无 lint 错误。
- 不提交 git。

## 11. 决策记录

1. A2 改共享 `Sidebar.tsx`（非新造 operator 左栏）；`RobotOperatorApp`/`RobotSidePanel` 不碰。
2. 组件库不面向操作员（无 UI）；A1 component API 留给工程师后台。
3. 命令库 = 单入口 → 页内命令/流程两页签。
4. 布局：共享左栏 | 列表+筛选(~300px) | 详情；库页隐藏 `RobotSidePanel`；窄窗 `lg`+`Sheet` 抽屉。
5. 路由 `#/library`、`ShellView "library"`、标签「命令库」。
6. Apps/Skills 仅从左栏移除；Settings 子页与 `#/apps`/`#/skills` 路由保留。
7. 补只读 flow list/detail API（`FlowRegistry` 只读）；步骤→`{command_id,version}` 留阶段 C。
8. `rightPanel` 门控 `view !== "library" && rightPanel`，覆盖初始 `#/operator` + hash 切 library 与直接 `#/library` 两路径。
9. 必需回归测试覆盖 `rightPanel`-via-hash 门控路径。
10. **[审查修正 P1]** 命令库首次启动自动播种：从打包资源 `seed_query_table.json` 幂等迁移，绝不覆盖既有 `commands.json`，种子缺失/失败记错不静默空库；不自动迁移 flows（破坏性）。
11. **[审查修正 P1]** 流程页签删除 `confirmed`/`state` 筛选承诺（YAGNI，~7 条流程），保留并实现本地 `q` 搜索（name/description）。
12. **[审查修正 P2]** 删除窄窗口抽屉承诺，移除误导性 `lg:flex`；桌面操作台固定列表宽度。
