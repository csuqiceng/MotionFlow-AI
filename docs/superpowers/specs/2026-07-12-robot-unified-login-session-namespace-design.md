# 统一双 Tab 登录页 + 会话命名空间隔离 — 切片② 设计

日期：2026-07-12
状态：已确认（含 7 项修正），待实施计划
关联：切片① 身份层已提交（`734a2192`，spec `2026-07-12-robot-engineer-identity-design.md`）；B1a 后端已提交（`b02e3491`）。本切片是"统一角色登录 + 多用户"重构的**第二步**：在切片① 已落地的 `/api/auth/*` `/api/users/*` `UserSessionStore` `users.json` 之上，做**前端登录页 + 会话命名空间隔离**。后续：③ 工程师台 UI（命令/组件/审计/用户管理）；④ B2 流程管理。

## 1. 目标与边界

切片② 给 nanobot WebUI 落地**统一双角色登录页**与**按用户隔离的会话命名空间**：操作员/工程师各自登录、各自只看到/只写到属于自己的会话；legacy 无命名空间会话默认隐藏且不可写；双 token（传输层 ws_token + 身份层 user_token）分离，均只在内存，刷新即重登。

**In scope：**
- 双 Tab 统一登录页（操作员 / 工程师），取代当前单 secret `AuthForm`。
- 会话命名空间隔离：`.jsonl` metadata 增 `namespace = "{role}:{user_id}"`；`list_sessions` 按 namespace 过滤；`new_chat` 盖 namespace；**所有按 session key 读取/写入的 REST 与 WS 路径都校验 namespace 归属**。
- 双 token 流：`bootstrap → ws_token → /api/auth/login → user_token → WS 首帧 auth`。
- 前端 token 仅内存（不入 localStorage）；刷新/重启 → 回登录页重登。
- WS 用户绑定（Approach 1b）：`auth` envelope 首帧绑定，未绑定前拒帧并关连接。
- shell 改由 `user_token.role` 驱动；操作员/工程师**同壳**（Sidebar + ThreadShell + RobotSidePanel），差别仅在 namespace/身份/后续工程能力。
- `unified_session=True` fail-closed（明确配置错误，绝不回退共享 `unified:default`）。
- legacy session 静默 404（不暴露存在）。

**Out of scope（后续切片）：**
- ③ 工程师台业务 UI（命令/流程管理、组件库编辑、审计查看、用户管理界面）。
- ④ B2 流程管理。
- legacy session 的"导入/归属分配"工具（独立后续工作，带审计）。
- `unified_session=True` 模式本身（本切片强制 False 并 fail-closed）。
- refresh token（切片① §3 已明确不做）。
- 第三种角色（engineer 兼管理员，未来才分 admin）。
- **操作员/工程师业务端点（机器人控制、命令库、流程等）从 ws_token 改接 user_token 的鉴权升级**——属切片① §3"逐步接入；切片① 不强制改全部"，本切片**不强制**。本切片只做：登录页 + session namespace 隔离 + 双 token 内存化。robot 命令/状态端点继续走 ws_token（`Bearer`，现有 `robotRequest` 模式），namespace 隔离只作用于**按 session key 的会话访问**。

**硬约束：** 切片① 鉴权后端零改动（复用 `/api/auth/*` `/api/users/*` `UserSessionStore`）；gateway ws_token 保持传输层凭证、不兼任身份；前端不持久化任何凭据；namespace 永远服务端从 user_token 派生，**前端传入的 namespace 不被信任**。

---

## 2. 双 Tab 统一登录页 UX

### 2.1 凭据模型（全多用户）

Tab = 角色（操作员 / 工程师），决定 `role`（提交给 `/api/auth/login`）与登录后目标路由。Tab 内为**用户名 + 密码**两字段。

- **用户名字段始终空起始、由用户输入**；**绝不预填、绝不写死** `admin`/`operator` 或任何账户名（与多账户审计、多用户会话隔离一致）。
- 密码字段空起始，`type=password`。
- 空用户名或空密码 → 提交按钮置灰（客户端，不发请求）。

### 2.2 Tab 切换规则

- **默认 Tab = 操作员**（无明确路由时）。**不按 runtime surface 分流**（不区分 native/web）。
- **URL 预选**（优先于默认）：`#/engineer` → 工程师 Tab；`#/operator` → 操作员 Tab。其余 hash / 无 hash → 操作员 Tab。
- **切 Tab**（操作员 ↔ 工程师）：清空密码、清空用户名（用户名是角色作用域，跨角色不通用）、清空错误态。
- Tab 偏好**不入 localStorage**（与"不持久化"一致；刷新后按 URL/默认重新决定）。

### 2.3 错误态映射

| HTTP | code | 文案 | 字段处理 |
|---|---|---|---|
| 401 | `invalid_credentials` | "用户名或密码错误" | 清密码、**保留用户名**、焦点回密码框 |
| 403 | `user_disabled` | "账户已禁用，请联系工程师" | 清密码、保留用户名 |
| 429 | `too_many_attempts` | "尝试过多，{N}s 后再试"（N 取自 `Retry-After` / `data.retry_after`） | 提交按钮置灰 + 秒级倒计时 |
| 5xx / 网络 | — | "服务暂不可用，请稍后重试" | 保留输入 |

- 401 覆盖三种后端情形（用户名不存在 / 密码错 / 角色不符），**统一文案、不区分**，防账户枚举（切片① `process_auth_login` 已对这三者返同一 `invalid_credentials`，见 `robot_routes.py:470/476/486`）。
- 403/429/5xx 各自独立文案（切片① 已分别返 `user_disabled` 403、`too_many_attempts` 429、`audit_write_failed` 503）。
- 错误展示在表单内（密码框上方），不用 toast。

### 2.4 登录页线框

```
┌──────────────────────────────┐
│     nanobot 机械手控制台      │
│  ┌─────────┐ ┌─────────┐      │   Tab=角色 → role + 目标路由
│  │■操作员■ │ │  工程师 │      │   默认操作员 / URL 预选 / 切 Tab 全清
│  └─────────┘ └─────────┘      │
│  用户名 [_______________]     │   空起始，绝不预填
│  密  码 [_______________]     │
│  [         登 录          ]   │   空字段置灰；错误态见 2.3
└──────────────────────────────┘
```

---

## 3. 跳转、shell 绑定与路由

### 3.1 shell 由 session 角色驱动（架构变更）

当前 `App.tsx:542` `shouldUseRobotOperatorApp(surface, hash)` 按 hash 决定 shell。登录体系上线后**改为按 session 角色**（`user_token.role`），否则操作员手敲 `#/engineer` 即可无鉴权进入工程师 shell。

- 登录成功：`role=operator` → `#/operator`；`role=engineer` → `#/engineer`。
- **两个角色同壳**：均渲染 `Sidebar + ThreadShell + RobotSidePanel`（**工程师侧面板不隐藏**）。差别仅在：会话命名空间、当前身份、以及切片③ 起追加的工程能力 UI。
- 因此 `App.tsx` 的 operator/engineer 双分支合并为单一 `<Shell rightPanel={<RobotSidePanel/>}>`；`shouldUseRobotOperatorApp` 移除。
- hash 只跟随角色（非权威）：手敲异角色 hash（如 operator 敲 `#/engineer`）→ 重定向回自己角色的 hash（`#/operator`）。

### 3.2 hash 方案（按角色）

- 操作员会话：`#/operator?chat=<key>`（沿用现有 operator hash 方案）。
- 工程师会话：`#/engineer?chat=<key>`（新；取代旧 `#/chat/<key>` 在工程师侧的使用）。
- `Shell` 内决定 hash 方案的逻辑从 `isOperatorConsole = rightPanel != null` 改为 `session.role`。
- legacy `#/chat/<key>` 深链：若目标 session 不属于当前用户 namespace → 落 §7 的 404 处理（列表/打开均不可见）。

### 3.3 刷新 / 登出 / 换角色

- **刷新/重启**：user_token 仅内存、未持久化 → 回登录页重走（切片① §3）。WS token 经 localhost 免密 `bootstrap` 重新获取。
- **登出**：`GET /api/auth/logout`（`Authorization: Bearer ws_token` + `X-Nanobot-User-Token`）撤销 user_token → 清内存 token → 回登录页。
- **换角色**：登出后回登录页重登（**不做快捷角色切换器**；YAGNI，切片③ 再视需要加）。

---

## 4. 双 token 流与传输契约

切片① §3 已定：gateway ws_token = 传输层凭证；user_token = 身份。二者分离。本切片前端串联顺序（**关键修正：bootstrap 在前**）：

```
1. GET /webui/bootstrap                           # appliance localhost 免密（ws_http.py:342）
   -> { token(ws_token), ws_path, expires_in, ... }
2. GET /api/auth/login                            # 受 gateway token 门控
   Authorization: Bearer <ws_token>
   X-Nanobot-Robot-Body: {"username","password","role"}   # GET+body-header，不是 POST
   -> { user_token, user:{user_id,username,role}, expires_in }
3. ws://...?token=<ws_token>  建连                 # ws_token 仍是 URL（传输 token，现有模式）
4. WS 首帧 {type:"auth", user_token}              # 见 §5，绑定 {role,user_id}
5. 后续帧/REST 全部以 user_token 为身份
```

两个 token 都只存 React state（`BootState.ready` 携带 `wsToken` + `userToken` + `user`），**不入 localStorage**。

**传输硬约束（修正 2）：**
- gateway 的 WS HTTP 通道是 **GET + `X-Nanobot-Robot-Body`**（`websockets` 库只接 GET，见 `robot-api.ts:24` 注释）。WebUI 主路径的 `/api/auth/login` **必须写成 GET + body header，不能写成 POST**。
- aiohttp 真 POST 传输（非浏览器客户端/SDK）可保留 POST 适配；切片① 已实现两传输并存（`ws_http.py` GET+body-header + aiohttp POST）。
- `/api/auth/login` 当前已受 gateway token 门控（切片① §3 鉴权矩阵），本切片不改变其鉴权，只明确前端调用顺序与传输写法。

**bootstrap 失败边界（修正 4）：**
- 本流程依赖 appliance localhost 可**匿名**取得 `ws_token`（`/webui/bootstrap`，`ws_http.py:342` localhost 免密）。
- 登录页**先 bootstrap、成功后才允许提交登录**。若 `/webui/bootstrap` 不可用（网络/网关未起）或**要求旧 secret**（非 appliance 部署、配置了 `token_issue_secret`）→ **停在登录页，显示"无法建立控制台连接"**（独立错误态），**绝不误报成用户名/密码错误**（不进 401/403 文案）。
- 即三种前端错误态严格区分：① 连接错误（bootstrap 失败）→ "无法建立控制台连接"；② 凭据错误（登录 401/403/429）→ §2.3 文案；③ 服务错误（5xx）→ "服务暂不可用"。互不串扰。
- **WS 重连 / ws_token 刷新后必须重发首帧 `auth`**（绑定不跨连接；见 §5）。client 在 `onReauth`/重连回调里重发 `auth`，未 auth 完成前缓冲出站帧。

---

## 5. WS 用户绑定 — Approach 1b（auth envelope 首帧）

**问题**：WS 连接靠 ws_token 鉴权（传输层，不绑定用户）。用户身份（user_token）在 REST 层。服务端要在 `new_chat`/`attach`/`message` 上知道用户才能盖/校验 namespace。

**方案（修正 1，Approach 1b）**：ws_token 只用于建连；**身份用首帧 `auth` envelope 绑定，user_token 绝不进 URL**（避免进入浏览器历史、代理、访问日志）。

```
连上后客户端必须以 {type:"auth", user_token:"<user_token>"} 作为第一帧。
服务端：
  - 收到 auth 帧 -> user_session_store.check(user_token)
    - 有效 -> 把 {role, user_id, namespace=f"{role}:{user_id}"} + user_token 绑定到该连接对象
    - 无效/过期 -> 关闭连接（客户端回登录页）
  - 绑定完成前，任何非 auth 帧 -> 拒绝并关闭连接
  - 绑定后，每个业务帧(new_chat/attach/message)用 bound user_token 再调 user_session_store.check()：
    - 有效 -> 用返回的 {role,user_id} 派生 namespace，授权该帧
    - 返回 None（被 revoke_by_user_id 撤销 / 过期，见 §11）-> 关闭连接，客户端回登录页
    - 目标 session 不属于本 namespace（跨用户或 legacy）-> 回错误帧 {type:"error",code:"session_not_available"}，
      连接保持可用（不关连接、不泄露归属）
```

- **绑定一次、每帧验活**：auth 帧建立绑定；业务帧用 bound token 调 `check()` 验活（内存 dict 查找，廉价）。这样禁用/改密/角色变更（`revoke_by_user_id`）后，**已有 WS 连接的下一业务帧即失败、被关闭**——与 §11 撤销语义一致（修正"只校验一次"的矛盾）。客户端无需每帧重传 user_token（区别于被否决的 Approach 2）。
- **关连接 vs 保持**：只有"未绑定 / auth 失败 / 业务帧验活失败"才关连接；业务帧的 namespace 不匹配（跨用户/legacy）只回 `session_not_available` 错误帧，**连接保持**（用户仍可用其名下其他会话）。WS 无 HTTP 404，归属不匹配用**不泄露信息的错误帧**表达。
- user_token 8h 过期 → 下一业务帧 `check()` 返回 None → 关连接 → 回登录页。
- **WS 重连 / ws_token 刷新后必须重发首帧 `auth`**（绑定不跨连接）。
- ws_token 仍在 WS URL（`?token=`）——传输层凭证、不是身份；只有 user_token 被排除出 URL。

> 备选（不采用）：Approach 1a（user_token 进 URL query）被否——URL 会进浏览器历史/代理/访问日志；Approach 2（每帧带 user_token）易漏帧；Approach 3（ws_token 携带身份）与切片① §3"ws_token 不兼任身份"冲突。

---

## 6. 会话命名空间模型与强制点

### 6.1 模型

- `.jsonl` 首行 `_type:metadata` 增字段 `namespace: "{role}:{user_id}"`（如 `engineer:AbCd1234`、`operator:Zx9Y`）。
- `user_id` 来自切片① `UserSessionStore.check(user_token)` 返回 session 的 `user_id`（稳定主键，切片① §2）。
- namespace **永远服务端派生**：REST 从 `X-Nanobot-User-Token` 校验得到 session → `{role}:{user_id}`；WS 从连接 bound user。

### 6.2 强制点（全部 server-side 派生，客户端不可信）

覆盖**所有按 session key 读取或写入**的路径（修正 5，防手工 URL 越权读他人历史）：

1. **`new_chat`**（WS 帧 / REST）：服务端用派生 namespace 盖入新 session metadata；不接受客户端传入的 namespace。
2. **`list_sessions`**（REST）：从 user_token 派生 namespace → 只回 metadata.namespace 匹配项。即使保留 `?namespace=` 兼容参数，**仅当其值与派生值完全一致才接受，否则拒绝**（修正 4）。
3. **会话详情 / 消息读取（thread）/ 标题 / 归档 / 删除 / automations**（REST，按 session key）：解析目标 session 的存储 namespace；若 ≠ 派生 namespace → 落 §7（404）。
4. **`attach` / `message`**（WS 帧）：每帧先用 bound token `check()` 验活（见 §5），再用派生 namespace 校验目标 session 归属；不符（跨用户或 legacy）→ 回错误帧 `{type:"error",code:"session_not_available"}`，**连接保持**（不关连接、不泄露归属）。REST 等价路径返回 `404 session not available`。
5. **legacy session（无 namespace）**：对任何 user 都不匹配 → 列表不出现 + 读/写均拒（§7）。

涉及文件：`nanobot/session/manager.py`（metadata namespace 读写、`list_sessions(namespace)` 过滤、按 key 访问前归属校验、new_chat 盖 namespace）、`nanobot/channels/websocket.py`（`_route_envelope` 帧处理用 bound user）、`nanobot/webui/ws_http.py`（`_dispatch_session_routes` 全部按 key 路由加归属校验 + `X-Nanobot-User-Token` 读取）。

---

## 7. legacy session 处理（静默 404，修正 6）

切片② 上线前磁盘上已有、无 namespace 的 `.jsonl` session：

- **不迁移、不自动归属**（不归 admin、不进共享池——旧聊天没有可靠用户/角色归属，自动归属会造成跨角色泄露或错配）。
- 原文件 + 原 metadata **原地保留不动**。
- 对**所有**按 key 访问（列表/详情/读消息/写/删）：**REST** 返回 **`404 session not available`**；**WS** 回错误帧 `{type:"error",code:"session_not_available"}` 且**连接保持**（见 §5）。二者均**不向普通用户提示"需工程师认领"**，避免暴露旧 session 的存在（信息保密）。
- 服务端可记内部日志/审计（跨 namespace 访问尝试），便于排查。
- legacy 的"导入/归属分配"工具是**切片② 之后的独立工作**（由工程师管理员操作，写审计），本切片不做。

> 落地含义：§6.2 第 3/4/5 点的"不符 → 404"对 legacy 同样适用——legacy 无 namespace，与任何派生 namespace 都不匹配，自然 404，且与"session 不存在"的 404 不可区分（防枚举）。

---

## 8. unified_session fail-closed（修正 7）

`unified_session=True`（`config.agents.defaults.unified_session`，`schema.py:158`，所有 channel 共享一个 `unified:default` session）与多用户命名空间隔离根本冲突。

- **fail-closed**：在身份会话模式启动初始化（`initialize_user_identity`）或创建聊天（`new_chat`）时，若 `unified_session == True` → **直接抛明确配置错误**（如 "unified_session 与多用户命名空间隔离不兼容，请设为 false"），**绝不回退**到共享 `unified:default`。
- 不做"兼容降级"——隔离失效是安全事件，必须显式失败。

---

## 9. 前端改动

- **`webui/src/App.tsx`**：
  - `AuthForm`（219-271 行）→ 新 `LoginPage` 组件（dual-Tab + 用户名 + 密码 + §2 错误态）。
  - `BootState.auth` 分支渲染 `LoginPage`；`BootState.ready` 携带 `wsToken` + `userToken` + `user{role,...}`。
  - 移除 `shouldUseRobotOperatorApp`；operator/engineer 双分支合并为单一 `<Shell rightPanel={<RobotSidePanel/>}>`（§3.1）。
  - 新增跨角色 hash 重定向 effect（§3.1）。
  - 删除 `loadSavedSecret/saveSecret/clearSavedSecret` 调用与 `bootstrapSecretRef`（不再持久化 secret）。
- **`webui/src/lib/bootstrap.ts`**：
  - 保留 `fetchBootstrap`（localhost 免密）。
  - 新增 `fetchLogin({username,password,role}, wsToken)`：GET `/api/auth/login` + `Authorization: Bearer ${wsToken}` + `X-Nanobot-Robot-Body`。
  - 新增 `fetchLogout(wsToken, userToken)`。
  - **删除** `loadSavedSecret/saveSecret/clearSavedSecret` + `SECRET_STORAGE_KEY`。
- **`webui/src/lib/api.ts`**：
  - `listSessions(token)` → `listSessions(wsToken, userToken)`：加 `X-Nanobot-User-Token` 头；不传 namespace（服务端派生）。
  - 所有按 session key 的调用（`fetchWebuiThread`、`apiDeleteSession`、rename/archive、`fetchSessionAutomations` 等）加 `X-Nanobot-User-Token`。
- **`webui/src/hooks/useSessions.ts` / `useSidebarState.ts`**：
  - 按 `namespace`（= `{role}:{user_id}`，来自登录 user）参数化；sidebar 偏好 localStorage 键加 namespace 后缀（各用户置顶/归档/重命名互不影响）。
- **`webui/src/providers/ClientProvider.tsx`**：透传 `userToken` + `user`。
- **`webui/src/lib/nanobot-client.ts`**：WS 连上后自动发首帧 `{type:"auth", user_token}`；未 auth 完成前缓冲/拒绝其他帧；`auth` 失败 → 触发回登录页。

---

## 10. 后端改动

- **`nanobot/session/manager.py`**：
  - metadata 读写支持 `namespace` 字段。
  - `list_sessions(namespace=None)`：`namespace` 非空时只回匹配项；`None` 仅内部/迁移用途。
  - 新增按 key 的归属校验助手 `assert_namespace_owner(key, namespace)`：解析存储 namespace，不匹配/缺失 → 抛 `SessionNotAvailableError`（→ 404）。
  - `new_chat` 创建时盖 namespace。
- **`nanobot/channels/websocket.py`**（`_route_envelope`，656 行附近）：
  - 连接握手状态机：未 auth → 仅接受 `auth` 帧，其它帧拒绝并关连接；`auth` 帧 `user_session_store.check` → 绑定 `{role,user_id,namespace}` 到连接。
  - `new_chat`/`attach`/`message`：每帧先用 bound token `check()` 验活，再用 bound user 派生 namespace 校验目标 session；不匹配（跨用户/legacy）→ 回 `session_not_available` 错误帧（**连接保持**）；验活失败（撤销/过期）→ 关连接。
- **`nanobot/webui/ws_http.py`**：
  - `_dispatch_session_routes` 全部按 key 路由加 `assert_namespace_owner`；从 `X-Nanobot-User-Token` 头派生 namespace。
  - `list_sessions` 路由：派生 namespace 过滤；`?namespace=` 仅在 == 派生值时接受。
  - `/api/auth/login`、`/api/users/*`：**零改动**（切片① 已完成，GET+body-header + Bearer ws_token 门控 + user_token 鉴权）。
- **`robot_ai/library/users.py` / `auth.py`**：零改动（`UserSessionStore.check` 已返回 `{user_id,role,...}`，足够派生 namespace）。
- **`nanobot/cli/commands.py`**（`_run_gateway`）：`initialize_user_identity` 前后增加 `unified_session=True` 检查 → fail-closed（§8）。

---

## 11. 安全

- **双 token 分离**：ws_token 仅传输层（URL，localhost），user_token 仅身份（内存 + WS auth 帧 + REST header，绝不入 URL/localStorage）——修正 1/2 落实。
- **namespace 服务端派生**：REST 从 `X-Nanobot-User-Token`，WS 从 bound connection；前端传入 namespace 不被信任（修正 4）。
- **全 session-key 路径鉴权**：列表/详情/读消息/标题/归档/删除/automations/attach/message 全部校验 namespace 归属（修正 5），防手工 URL 越权。
- **legacy 静默 404**：跨 namespace + 无 namespace 统一 `404 session not available`，不暴露存在（修正 6），与"不存在"不可区分。
- **`unified_session` fail-closed**：绝不回退共享 session（修正 7）。
- **登录安全沿用切片①**：dummy PBKDF2 timing、节流（`username:role` + 客户键）、成功审计 fail-closed（503不发 token）、401 不区分用户存在性、无 refresh token、密码不入日志/审计/响应。
- **身份变更立即踢出**（切片① §6）：reset-password / me-password / role-change / disable → `revoke_by_user_id` → 该 user 的 WS 连接绑定失效（下次帧校验失败 → 关连接，需重登）。
- **响应 no-store**（切片① 沿用）。

---

## 12. 测试

### pytest（`.venv-robot-desktop`，在切片① 525 passed 基础上只增不减）

- **metadata namespace**：读写 `namespace` 字段；旧 metadata（无 namespace）向后兼容读取。
- **`list_sessions(namespace)`**：只回匹配项；无 namespace 的 legacy 不回；`namespace=None` 行为不变。
- **`assert_namespace_owner`**：归属正确 → 通过；跨 user → `SessionNotAvailableError`；legacy（无 namespace）→ `SessionNotAvailableError`；与"key 不存在"的 404 不可区分。
- **`new_chat` 盖 namespace**：服务端用派生值盖入；忽略客户端传入 namespace。
- **WS 握手状态机**：未 auth 时非 auth 帧 → 拒绝 + 关连接；`auth` 帧无效 user_token → 关连接；有效 → 绑定 `{role,user_id,namespace}+user_token`。
- **WS 每帧验活（修正 §5/§11 矛盾）**：绑定后业务帧用 bound token 调 `check()`；改密/禁用/角色变更（`revoke_by_user_id`）后，**已有连接下一业务帧即失败、被关闭**；过期同理。
- **WS 错误帧 vs 关连接（修正 3）**：业务帧跨 namespace / legacy → 回错误帧 `{type:"error",code:"session_not_available"}` + **连接保持**（不关连接、不泄露归属，用户仍可用名下其他会话）；只有未绑定 / auth 失败 / 验活失败才关连接。
- **伪造 namespace 被拒**：`new_chat`/`list_sessions?namespace=` 传他人 namespace → 用派生值覆盖/拒绝（不接受与派生值不一致的 `?namespace=`）。
- **全 session-key REST 鉴权**：跨 user 访问 detail/messages/rename/archive/delete/automations → 404；同 user → 通过。
- **`unified_session=True` fail-closed**：启动初始化 / `new_chat` 抛明确配置错误，不回退 `unified:default`。
- **legacy 静默拒绝（修正 6）**：REST 跨 namespace 与 legacy 访问均返 `404 session not available`（文案一致，与"不存在"不可区分）；WS 等价为 `session_not_available` 错误帧 + 连接保持。

### vitest（`webui`）

- **`LoginPage`**：dual-Tab 渲染；**默认操作员 Tab（不按 surface 分流）**；URL `#/engineer`/`#/operator` 预选 Tab（优先）；切 Tab 清密码/用户名/错误态；用户名空起始不预填；空字段提交置灰；错误态映射（401 通用 + 清密码留用户名 + 焦点回密码 / 403 禁用 / 429 倒计时 / 5xx 网络 / bootstrap 失败="无法建立控制台连接"）；登录成功回调 `{wsToken,userToken,user}`。
- **shell-by-session-role**：`role=operator`/`engineer` 均渲染 `Sidebar+ThreadShell+RobotSidePanel`；hash 为 `#/operator?chat=`/`#/engineer?chat=`。
- **跨角色 hash 重定向**：operator 敲 `#/engineer` → 回 `#/operator`。
- **`useSessions(namespace)`**：按 namespace 隔离；不同 namespace 不串。
- **token 仅内存**：登录后 `localStorage` 无 user_token/ws_token/secret；刷新 → 回登录页。
- **bootstrap 失败边界（修正 4）**：`/webui/bootstrap` 不可用或要求 secret → 停登录页显示"无法建立控制台连接"（**不报凭据错**）；登录提交被禁用直至 bootstrap 成功；凭据错误（401/403/429）与服务错误（5xx）文案互不串扰。
- **WS 重连重发 auth**：`onReauth`/重连后客户端重发首帧 `auth`；未 auth 完成前出站业务帧被缓冲/拒绝。

### 终验命令

```
cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/ nanobot/config/ nanobot/cli/ -q   # 切片① 525 passed 基线上只增不减
cd nanobot-main-1/webui && bun run test
cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m ruff check nanobot/ robot_ai/                          # clean
```

---

## 13. 验收标准

- 双 Tab 登录页：操作员/工程师 Tab（**默认操作员、不按 surface 分流** + URL `#/engineer`/`#/operator` 预选优先 + 切 Tab 全清）+ 用户名（空起始不预填）+ 密码；错误态按 §2.3 映射。
- 登录走 `bootstrap → /api/auth/login（GET+body-header, Bearer ws_token）→ user_token → WS 首帧 auth`；user_token 绝不入 URL/localStorage；**bootstrap 失败停登录页"无法建立控制台连接"，不误报凭据错**。
- WS：`auth` 首帧绑定 `{role,user_id,namespace}+user_token`；**业务帧每帧 `check()` 验活**（改密/禁用/角色变更 → 已有连接下一帧被关）；跨 namespace/legacy → `session_not_available` 错误帧、**连接保持**；重连/刷新后重发 `auth`。
- shell 由 `user_token.role` 驱动；两角色同壳（含 RobotSidePanel）；跨角色 hash 重定向。
- 会话 namespace = `{role}:{user_id}` 写入 metadata；`list_sessions` 按 namespace 过滤；所有按 key 的 REST/WS 访问校验归属；namespace 服务端派生、前端不可信。
- legacy session 静默 404（不暴露存在、不可写）；不做自动归属。
- `unified_session=True` fail-closed（明确错误，不回退）。
- 刷新/重启 → 回登录页重登；登出/换角色 → `/api/auth/logout` + 登录页。
- 切片① 鉴权后端零改动；B1a 命令管理业务不受影响。
- pytest 全绿（525 基线只增不减）+ vitest 全绿 + ruff clean。

---

## 14. 决策记录

1. **凭据模型 = 用户名 + 密码（全多用户）**：Tab=角色，用户名始终用户输入、绝不预填 `admin`/`operator`——与多账户审计 + 会话隔离一致（否决"仅密码 kiosk"与"预填主账户"）。
2. **Tab 行为 = 默认操作员 + URL 预选 + 切 Tab 全清**：无明确路由时默认操作员（**不按 runtime surface 分流**）；`#/engineer`/`#/operator` 预选且优先；切 Tab 清密码/用户名/错误态；Tab 偏好不入 localStorage。
3. **shell 由 session 角色驱动**（非 hash）：防操作员手敲 `#/engineer` 无鉴权进入；两角色同壳（含 RobotSidePanel），差别仅 namespace/身份/后续工程能力。
4. **跳转**：登录后按角色跳 `#/operator`/`#/engineer`；跨角色 hash 重定向回自己角色；刷新/重启/登出/换角色 → 回登录页重登（无快捷切换器）。
5. **双 token 分离 + bootstrap 在前**：`bootstrap → ws_token → /api/auth/login → user_token → WS auth 帧`；ws_token=传输层、user_token=身份，均仅内存；**bootstrap 失败停登录页"无法建立控制台连接"，不误报凭据错**；WS 重连/ws_token 刷新后重发首帧 `auth`。
6. **传输 = GET + `X-Nanobot-Robot-Body`**（WebUI 主路径不写 POST；aiohttp 可保留 POST 适配）——gateway `websockets` 只接 GET。
7. **WS 用户绑定 = Approach 1b**：ws_token 建连，首帧 `auth` envelope 携 user_token，校验后绑定 `{role,user_id,namespace}+user_token`；**绑定一次、业务帧每帧用 bound token 调 `check()` 验活**（失效即关连接，与 §11 撤销语义一致）；未绑定 / auth 失败 / 验活失败 → 关连接；业务帧跨 namespace/legacy → 回 `session_not_available` 错误帧、**连接保持**（WS 无 HTTP 404）；WS 重连/ws_token 刷新后重发 `auth`；**user_token 绝不入 URL**（否决 1a URL query / 2 客户端每帧重传 / 3 ws_token 携身份）。
8. **namespace 服务端派生、前端不可信**：REST 从 `X-Nanobot-User-Token`，WS 从 bound connection；`?namespace=` 仅在 == 派生值时接受。
9. **全 session-key 路径鉴权**：列表/详情/读消息/标题/归档/删除/automations/attach/message 全部校验 namespace 归属（防手工 URL 越权读他人历史）。
10. **legacy 静默拒绝**：不迁移、不自动归属、不进共享池；原文件保留；跨 namespace + 无 namespace 统一静默拒绝（**REST `404 session not available` / WS `session_not_available` 错误帧 + 连接保持**），不提示"需认领"（防存在性泄露）；认领工具后续单独做。
11. **`unified_session=True` fail-closed**：启动/new_chat 抛明确配置错误，绝不回退共享 `unified:default`。
12. **错误态**：401 通用（防枚举）+ 清密码留用户名；403 禁用；429 倒计时；5xx 网络；空字段置灰。
13. **切片① 鉴权后端零改动**；namespace 隔离在 session 层 + WS/REST 派发层实现。
14. **不持久化任何凭据**：user_token/ws_token/secret 均不入 localStorage；刷新即重登（切片① §3）。
