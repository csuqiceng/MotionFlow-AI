# 工程师命令管理 — B1 设计

日期：2026-07-12
状态：已确认，待实施计划
关联：父草案 `2026-07-11-robot-knowledge-and-engineer-console-design-draft.md`（§3.2/§5/§7.B）。A1/A2（操作员只读库）已完成并提交（`a1ffec1a`）。本文件是工程师后台的**第一个切片**：工程师鉴权 + 命令草稿/发布/版本历史/编辑器 + 未发布草稿归档。已发布命令归档 + 流程引用保护 + 流程管理 → **B2**。

## 1. 目标与边界

B1 给工程师在 A1/A2 只读库之上增加**写能力**：本地工程师口令鉴权、`#/engineer` 独立应用壳、命令草稿/发布/版本历史/归档（仅未发布草稿）、命令编辑器、事务发件箱审计。**不**做：已发布命令归档、流程引用保护、流程管理（B2）；网页首设口令（禁止）；多工程师身份/RBAC（未来）；工程师端真机写入。

**In scope：**
- 工程师鉴权：`config.json` 口令哈希 + CLI 设置 + 短时内存工程师令牌。
- `#/engineer` 独立 `EngineerApp` 应用壳（不复用操作员 Sidebar/会话列表/`RobotSidePanel`）+ 三态登录 + 三视图控制台（命令管理 / 组件库 / 审计）。
- 工程师只读**组件库视图**（复用 A1 `/api/robot/library/components` API，展示 schema/字段/risk/安全语义，**不扩写权限**；流程库留 B2）。
- 命令写 API（login/logout/commands CRUD/draft/publish/archive/audit）。
- 版本树存储（逻辑 `command_id` + 不可变发布版本 + 单草稿）+ 命令聚合事务发件箱（`commands.json` 根 `pending_audits`）。
- 1.0→2.0 原子迁移；A2 操作员读 API 继续只投影 `published_version`。
- 命令编辑器（schema 受约束参数；草稿 vs base_version 差异）。
- 审计 UI（分页）。
- 测试（后端 pytest + 前端 vitest）。

**Out of scope（B2/B3/未来）：**
- 已发布命令归档 + 流程引用保护（B2，流程步骤升级为 `{command_id,version}` 后才有意义）。
- 流程管理（编辑器/发布/归档）+ 流程步骤升级（B2）。
- 工程师端真机写入入口；多工程师身份/RBAC；网页首设口令；导入审计（未来通用 outbox）。

**硬约束：** 不修改 `RobotSidePanel.tsx`、`RobotOperatorApp.tsx`、A2 操作员 `#/library` 只读行为、`robot_ai/flow/`、真机执行链路。编辑行为**不**直接驱动真机；真实执行仍走操作员 dry-run→confirm→execute。

## 2. 数据模型与存储

`~/.nanobot/robot_ai/commands.json`，`schema_version` 升至 `2.0`（A1 为 `1.0` 单条记录）：

```json
{
  "schema_version": "2.0",
  "updated_at": "...",
  "commands": {
    "<command_id>": {
      "command_id": "home",
      "published_version": 1,            // int 或 null（未发布）
      "versions": {
        "1": { ...Command, "version": 1, "status": "published" }   // 已发布版本永不原地改
      },
      "draft": {                          // 单一活动草稿；或 null
        "revision": 3,                    // 乐观并发计数器
        "base_version": 1,                // 基于哪个已发布版本
        ...Command 字段, "status": "draft"
      }
    }
  },
  "pending_audits": [                     // 根 outbox —— 命令聚合的所有持久化写操作（create/start-draft/update-draft/publish/archive）
    { "audit_id": "...", "action": "command_publish", "actor": "...", "target": {...}, "payload": {...}, "timestamp": "..." }
  ]
}
```

- **版本主键语义**：`command_id`（逻辑，稳定）≠ 不可变版本（`versions["N"]`，发布即冻结）。`published_version` 指向当前对操作员可见的版本；`null` = 无已发布版本（操作员不可见）。
- **versions 内记录永不原地改**；只创建新草稿，发布时生成 `N+1`。
- **草稿**：每命令最多一个活动草稿（`draft` 单数）；编辑已发布命令 = 基于其当前发布版本建/替换草稿（`base_version` = 当前 published_version）；发布 = 草稿 → `versions[N+1]` + 清草稿。
- **`Command` 字段**（沿用 A1）：`id, name, aliases, description, component_id, parameters, risk_level, status, version, source, created_by, created_at, updated_at, published_at`。草稿复用，加 `revision, base_version`。
- **`pending_audits` 根 outbox** 覆盖**命令聚合的所有持久化写操作**（create/start-draft/update-draft/publish/archive）；每次状态变更与对应 audit outbox 项同一次 `atomic_write_json` 原子写入，统一 drain（见 §8）。登录审计直接 append `audit.jsonl`（fail-closed）；登出先撤销令牌再尽力审计（审计失败记服务端错误，安全性优先于审计完整性）；B2 流程在 flows 聚合内自建 outbox。
- `audit.jsonl`：append-only 全审计（A1 已有），每行 `{action, actor, target, audit_id/migration_id, before/after, timestamp}`。
- 原子写：沿用 A1 `atomic_write_json`（temp+fsync+os.replace）。

## 3. `ComponentCatalog` 扩展（risk_level）

每个内置组件新增 **`risk_level`**（`low/medium/high/critical`），发布时 command 的 `risk_level` **由组件推导**（非客户端字段）。4 组件：`system_action`→high、`linear_move`→high、`delay`→low、`io_write`→medium（值在实施时按安全策略最终确定）。`Component` 模型加 `risk_level: str` 字段。

## 4. 迁移：commands.json 1.0 → 2.0（原子、幂等）

- 读旧 `commands.json`（schema 1.0，`commands:[Command...]` 单条记录）。
- 每条已发布 Command（A1 全是 published v1）→ 实体 `{command_id=旧id, published_version=1, versions={"1": <记录>}, draft=null}`。
- 写新结构（schema 2.0，`commands:{...}`，`pending_audits:[]`），一次 `atomic_write_json`。
- 幂等：若已是 schema 2.0，no-op。
- **启动顺序固定**：`_run_gateway` 内依次 `seed_command_library_if_missing()` → `migrate_commands_schema_if_needed()` → 启动。首装时 seed 先生成 schema 1.0 文件、migrate 紧随转 2.0（顺序反了则首启迁移 no-op、要二次启动才升 2.0）。两者都幂等。
- A2 操作员读 API（`process_robot_library_commands`）改为投影 `published_version` 指向的版本（无已发布版本则不返回）。

## 5. 工程师鉴权

- **口令哈希**：`~/.nanobot/config.json` 新字段 `robot_ai.engineer.password_hash`，格式自描述 `pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>`。`iterations` 是**策略值**（`robot_ai.engineer.pbkdf2_iterations`，默认如 200000）。随机 salt（`secrets.token_bytes`）。校验用 `hashlib.pbkdf2_hmac("sha256", ...)` + `secrets.compare_digest`。
  - **迭代升级策略**：登录成功验证后，若所存哈希的 `iterations` < 当前策略值，用刚验证的口令按新策略重新哈希并原子更新 config（透明升级——使既有口令随策略提升而增强）；`nanobot engineer set-password` 始终用当前策略值。
- **CLI 设置**：`nanobot engineer set-password` —— 隐藏输入（`getpass`），**明文不入命令行参数、不入日志**。校验并写入 config。`#/engineer` 未配置时只显示"请运行 `nanobot engineer set-password`"，**禁止网页首设**。
- **工程师令牌**：`secrets.token_urlsafe(32)`，**内存**存储 `{token: expiry}`（不持久化），TTL 8h。每次鉴权清理过期项。重启/页面刷新/到期 → 重新登录。登出（`GET /engineer/logout`）立即撤销。
- **写 API 鉴权**：gateway token **且** `X-Nanobot-Engineer-Token`（有效未过期）。读 API（A1/A2 library）只要 gateway token。`GET /engineer/commands`（看草稿/版本）需 gateway token + 工程师令牌。
- **登录节流**：`GET /engineer/login` 先过 gateway token，再按 IP/会话失败次数节流，超限 `429` + `Retry-After`。
- **登录审计 fail-closed**：成功认证后追加审计（`{action:"engineer_login", actor:"engineer", result:"success", timestamp}`）；**审计 append 失败 → 503、不发令牌**（避免无审计高权会话）。失败登录审计写失败 → 仅服务端运行日志、拒绝结果不变。审计**绝不**记录密码或令牌。

## 6. 传输与缓存

- **WebUI 主路径**：`GET` + `X-Nanobot-Robot-Body` 头（`ws_http` 跑在 `websockets` 库，`process_request` 只收 GET、不暴露 body）。所有工程师端点（login/logout/commands/draft/publish/archive/audit）走此机制。
- **aiohttp standalone 适配**：`register_robot_routes` 加真 POST/PUT（非浏览器客户端）。
- `process_engineer_*` 传输无关；`handle_engineer_*`（aiohttp，读 `request.json()`）；`ws_http._dispatch_robot_engineer_routes`（GET+header，复用 `_robot_body_from_request`）。
- **访问日志不得记录 `X-Nanobot-Robot-Body` 头**（登录 body 含密码）。
- **所有工程师响应 `Cache-Control: no-store` + `Pragma: no-cache`**（登录/登出尤其关键——URL 固定，令牌绝不能被按 URL 缓存）。

## 7. 工程师 API 面

所有工程师写/读端点：gateway token +（除 login 外）工程师令牌；响应 no-store；WebUI=GET+body 头。

```
GET  /api/robot/engineer/login                  [body 头 {password}] -> {engineer_token, expires_in} | 429 | 503
GET  /api/robot/engineer/logout                 -> 撤销当前工程师令牌
GET  /api/robot/engineer/commands               -> {entities:[{command_id, name, published_version, has_draft, draft_revision, updated_at}]}  # 摘要，不含版本树
GET  /api/robot/engineer/commands/{command_id}  -> {command_id, published_version, versions, draft}  # 全实体
POST /api/robot/engineer/commands               [body {component_id, name, aliases?, description?, parameters?}] -> 服务端生成 command_id（name 归一化 slug，拒冲突）+ 建实体 + 初始草稿(revision=1)；客户端**不**传 command_id
PUT  /api/robot/engineer/commands/{id}/draft    [body 全量草稿 + expected_draft_revision] -> 更新草稿(revision+1)；expected 不符 -> 409
POST /api/robot/engineer/commands/{id}/publish  -> 校验草稿 + 发布 N+1（outbox 审计）
POST /api/robot/engineer/commands/{id}/archive  -> 归档；存在已发布版本 -> 409（B1 仅未发布草稿）
GET  /api/robot/engineer/audit ?limit=&before=<opaque cursor>  -> 分页审计（倒序，limit≤100；cursor 为 `{timestamp, audit_key}` 复合键的不透明编码——audit_key=`audit_id`(B1 新增) 或 `migration_id`(A1 旧迁移记录)；返回该复合键之前的项，避免同 timestamp 漏项）
```

- **列表摘要**：`GET /engineer/commands` 只返回摘要（command_id/name/published_version/has_draft/draft_revision/updated_at），**不**返回版本树（避免历史膨胀）。
- **乐观并发**：草稿 `revision` 每次 PUT 自增；body 带 `expected_draft_revision`；服务端不匹配 → `409`（提示前端重载）。`PUT` = 全量替换；局部更新才用 `PATCH`（B1 先实现 PUT 全量）。
- **审计分页**：`GET /engineer/audit` `limit`（上限 100）+ `before`（**不透明复合 cursor** = `{timestamp, audit_key}`，audit_key 为 `audit_id` 或 A1 旧记录的 `migration_id`），倒序；不全量读 `audit.jsonl`。复合键避免同 timestamp 漏项。
- **归档语义**：B1 仅允许归档**无已发布版本**的命令（`published_version` 为 null）；存在已发布版本 → `409`（归档已发布命令 + 引用保护 → B2）。

## 8. 发布校验与事务发件箱

**发布校验（服务端，失败 400 + 原因；客户端 func/VR/risk/时间一律忽略）：**
1. `component_id` ∈ ComponentCatalog 白名单。
2. `parameters` 按组件 schema（类型/必填/范围）。
3. `name`/`aliases` 全局唯一（跨所有**已发布**命令），**排除本 `command_id` 自身当前发布版本**（避免自冲突）；草稿间可重名，发布才拒。
4. `risk_level` = 组件 `risk_level`（服务端推导）。
5. 草稿结构完整。

**命令聚合事务（无半状态，所有持久化写操作使用 outbox）：**

所有命令状态变更（create/start-draft/update-draft/publish/archive）：
1. `atomic_write_json(commands.json)`：状态变更 + `pending_audits.append({audit_id, action, actor, target, payload, timestamp})`。
2. drain：append 该 audit entry → `audit.jsonl` → 移除 outbox 项。

- **drain（幂等）**：gateway 启动 + 每次工程师写前，遍历 `pending_audits`：按 `audit_id` 查 `audit.jsonl`，已有则移除项、未有则补写后移除。
- 崩溃在"状态已写、audit 未 append"之间 → 下次 drain 可靠补审计，不丢"状态已变但审计缺失"。
- **登录审计不经 outbox**：直接 append `audit.jsonl`（成功 fail-closed：审计 append 失败 → 503 不发令牌；失败登录审计写失败 → 仅运行日志、拒绝不变）。
- **登出语义**：先撤销令牌（安全性优先），再尽力 append 审计；审计失败记服务端错误、不影响登出成功。
- B2 流程发布在 flows 聚合内自建 outbox。

## 9. 前端 — `EngineerApp` 应用壳

- `App.tsx` 新增 `EngineerApp` 分支：`shouldRenderEngineerApp(hash)` → `#/engineer` 命中时渲染 `<EngineerApp>`，**不**落通用聊天 `<Shell>`。`EngineerApp` 自有布局，**不复用**操作员 Sidebar、会话列表、`RobotSidePanel`。
- `readShellRoute`：`#/engineer` → 新 view/state（非 chat）。`shellRouteHash`：engineer → `#/engineer`。
- 入口：直接 URL `#/engineer`（不在操作员侧栏链接；密码门保护）。
- 三态：
  1. 未配置口令 → `GET /engineer/login` 返回 403 + `{"error":{"code":"engineer_password_not_configured"}}`，前端据此显示"请运行 `nanobot engineer set-password`"。
  2. 未登录 → 密码表单 → `GET /engineer/login`(body 头) → 工程师令牌存**内存 React state**（不落 localStorage；刷新即重登）→ 控制台。
  3. 已登录 → 控制台 + 登出按钮（→ `GET /engineer/logout`）。

## 10. 前端 — 控制台 + 编辑器

- 左迷你导航「命令管理 / 组件库 / 审计」+ 主区。
- **命令管理**：列表（摘要）→ 选中 → 编辑器。
- **组件库**（只读）：复用 A1 `GET /api/robot/library/components` + `/{id}`，展示组件 schema/字段/范围/risk/安全语义。**不扩大写权限**（组件平台受控）。
- **编辑器**（表单）：`name` / `aliases` / `description` / `component_id` 下拉（驱动参数 schema）/ 参数字段（按组件 schema 受约束，**无 func/VR 字段**）。显示 `draft.revision` + `base_version` + **差异 = 草稿 vs `base_version`**（不做多版本 diff）。按钮：保存草稿（`PUT`+`expected_draft_revision`；409 → 提示重载）/ 发布（`POST publish`）/ 归档（`POST archive`，仅未发布草稿可见）。
- **审计**：分页表格（`GET /engineer/audit?limit=&before=`，action/actor/target/timestamp/summary），只读。

## 11. 安全边界

- 工程师端**无真机写入**入口；执行仍走操作员 dry-run→confirm→execute。
- 服务端忽略客户端 func 号/VR 地址/risk/发布时间。
- 登录成功审计 fail-closed；响应 no-store；节流；访问日志不记 body 头；令牌仅内存。
- A2 操作员库不受影响（继续只读 `published_version`）。

## 12. 测试

**后端 pytest（`.venv-robot-desktop`）：**
- 版本树 registry：建实体+草稿、发布 N+1（不可变）、命名空间排除自身、乐观并发 409、归档（draft-only 409）。
- 事务 outbox：**所有命令状态变更**（create/start-draft/update-draft/publish/archive）写 `pending_audits` + drain 幂等（已有 audit_id 不重复）、崩溃恢复（模拟审计失败→重跑补）、登出语义（先撤销令牌、再尽力审计）。
- 迁移 1.0→2.0：16 条→16 实体 versions["1"]、幂等、A2 读 API 仍投影 published_version；**启动顺序** seed→migrate（首装一次升 2.0，非二次启动）。
- 鉴权：pbkdf2 校验、**迭代升级（旧哈希低 iterations 登录后自动 re-hash + 更新 config）**、令牌生命周期（签发/过期清理/登出撤销）、登录节流 429、登录成功审计失败→503 不发令牌、审计不含密码/令牌。
- API process 函数：login/logout/commands(摘要 vs 详情)/draft(409)/publish/archive/audit(**复合 cursor 分页 + 同 timestamp 跨页不漏**)/commands-create(**command_id 服务端 slug 生成 + 冲突拒**)；no-store 头。

**前端 vitest（happy-dom）：**
- `EngineerApp` 三态、登录流程、登出；`#/engineer` 不复用操作员 Sidebar/`RobotSidePanel`。
- 编辑器表单：component 下拉驱动参数 schema、保存草稿 + 并发 409 提示重载、发布、归档（仅未发布）。
- 审计 UI 分页。
- 差异 = 草稿 vs base_version。

## 13. 验收标准

- CLI `nanobot engineer set-password` 设口令（隐藏输入、不落明文）。
- `#/engineer`：未配置→提示 CLI；未登录→登录表单；登录→控制台。刷新需重登。
- 工程师建命令（草稿）→ 编辑（乐观并发 409）→ 发布（N+1 不可变）→ 操作员 `#/library` 可见该已发布命令。
- 归档仅未发布草稿（已发布→409）。
- 发布审计完整（outbox + drain）；登录审计成功/失败、无密码/令牌泄露；登录成功审计失败→503。
- 所有工程师响应 no-store；访问日志不含 body 头。
- 工程师**组件库只读可见**（schema/字段/risk/安全语义，复用 A1 API，不扩写权限）。
- 新建命令 `command_id` 由服务端生成（slug，拒冲突）；客户端不传 id。
- A2 操作员库不受影响；编辑器无真机写入入口。
- 后端 pytest + 前端 vitest 全过；ruff/tsc/eslint clean。

## 14. 决策记录

1. 存储模型 A：单文件版本树（逻辑 `command_id` + 不可变版本 + 单草稿 + 根 `pending_audits` outbox）。
2. 版本主键：稳定逻辑 id ≠ 不可变版本号；`published_version` 可空（操作员不可见）。
3. 归档：B1 仅未发布草稿；已发布归档 + 引用保护 → B2（流程步骤未升级为命令引用前无法判引用）。
4. 鉴权：`config.json` pbkdf2 口令哈希 + CLI 隐藏输入设置 + 禁止网页首设；工程师令牌内存 8h；写 API 要 `X-Nanobot-Engineer-Token`；登录 gateway-token 闸门 + 节流 429；登录成功审计 fail-closed。
5. 传输：WebUI GET + `X-Nanobot-Robot-Body`（ws_http 只收 GET）；aiohttp 真 POST/PUT 适配；访问日志不记 body 头；响应统一 no-store。
6. 列表摘要（不含版本树）；草稿乐观并发（`expected_draft_revision`，409）；审计分页（limit+cursor）；审计 API。
7. 发布校验：组件白名单 + schema + 命名空间排除自身 + risk=组件 risk；客户端 func/VR/risk 忽略。
8. 事务发件箱：`commands.json` 根 outbox 覆盖**命令聚合的所有持久化写操作**（create/start-draft/update-draft/publish/archive），统一 `audit_id` 幂等 drain；登录直接 append（fail-closed）；登出先撤销令牌再尽力审计；B2 流程自建 outbox。
9. `risk_level` 服务端推导（ComponentCatalog 每组件带 risk_level）。
10. `EngineerApp` 独立 App 分支（不复用操作员 Sidebar/会话/`RobotSidePanel`）；直接 URL 进入。
11. 编辑器差异 = 草稿 vs `base_version`（不做多版本 diff）。
12. 迁移 1.0→2.0 原子幂等；gateway 启动执行。
13. **启动顺序**：`seed → migrate → gateway`（首装一次升 2.0）。
14. **审计 cursor** = `{timestamp, audit_id/migration_id}` 复合键（避免同 timestamp 漏项）。
15. **工程师只读组件库视图**（复用 A1 `/library/components`，不扩写权限）；迷你导航「命令管理 / 组件库 / 审计」；流程库 → B2。
16. **`command_id` 服务端生成**（name 归一化 slug + 拒冲突；客户端不传）。
17. **PBKDF2 迭代升级策略**（登录验证旧低 iterations 哈希后自动 re-hash + 原子更新 config；CLI 用当前策略值）。
