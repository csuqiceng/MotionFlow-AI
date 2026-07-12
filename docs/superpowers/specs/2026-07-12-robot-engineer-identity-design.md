# 工程师身份与多用户管理 — 切片① 设计（统一身份层后端）

日期：2026-07-12
状态：已确认（含 5 项安全/迁移边界补充），待实施计划
关联：B1a 后端已提交（`b02e3491`）；B1 design spec §5/§6/§7/§8。本切片是"统一角色登录 + 多用户"重构的**第一步**，取代 B1a 的单工程师密码模型。**后续切片**：② 双 Tab 统一登录页 + 会话命名空间隔离（前端 + session metadata）；③ 工程师台 UI（命令管理/组件库/审计/用户设置）；④ B2 流程管理（接入同一工程师台，步骤引用 `{command_id, version}`）。

## 1. 目标与边界

切片① 给 nanobot 引入**统一身份与多用户管理后端**：多用户账户（`operator`/`engineer` 两角色）、统一会话令牌（user token）、角色授权、用户管理 CRUD、B1a 单工程师凭据迁移、全审计。**gateway token 降级为 WebUI 传输层凭证，不再兼任用户身份**。

**In scope：**
- 用户模型 + `users.json` 存储（`atomic_write_json` + `pending_audits` outbox）。
- 统一会话 `UserSessionStore`（内存 user token，TTL 8h，**不 refresh**）。
- `/api/auth/login` `/api/auth/logout` + `/api/users/*` 管理端点。
- 角色授权（`operator`/`engineer`，engineer 兼管理员）。
- 迁移：B1a 单工程师密码 → `admin`（engineer）；gateway secret → `operator`（或禁用占位）。
- **本地 CLI bootstrap**：`nanobot users set-bootstrap-password`（修复首次安装锁死）。
- B1a engineer API 兼容别名（统一 user token，**不并行第二种 token**）。
- 审计（`actor="user:<user_id>"` + 结构化 `actor_user_id`/`actor_username`/`actor_role`）。
- 登录安全（dummy PBKDF2 timing、节流、成功审计 fail-closed、无 refresh token）。
- `user_id` 为切片② 会话命名空间 `<role>:<user_id>` 提供键。

**Out of scope（后续切片）：**
- 双 Tab 统一登录页 UI + 会话命名空间隔离（切片②）。
- 工程师台 UI（切片③）。
- 流程管理（B2）。
- `admin` 角色细分（engineer vs engineer-admin；现在 engineer 兼管理员，未来再分，**不混第三角色**）。
- refresh token（**明确不做**，避免持久化凭证）。

**硬约束：** 切片① 纯后端，不改 frontend；不破坏 B1a 已提交的命令管理业务能力（兼容别名平滑迁移）；gateway token 不再当用户身份。

---

## 2. 用户模型与存储

`~/.nanobot/robot_ai/users.json`，`schema_version: "1.0"`：

```json
{
  "schema_version": "1.0",
  "updated_at": "...",
  "users": {
    "<user_id>": {
      "user_id": "...",
      "username": "admin",
      "role": "engineer",
      "password_hash": "pbkdf2_sha256$...",
      "enabled": true,
      "created_at": "...",
      "updated_at": "..."
    }
  },
  "pending_audits": []
}
```

- `user_id`：`secrets.token_urlsafe(8)`，稳定主键（也为切片② namespace 键）。
- `username`：唯一；归一化比较用**新独立函数 `normalize_username()`**（`strip + casefold`）——**不复用 `normalize_id`**（`normalize_id` 服务命令 ID 域，修改它会影响命令 slug 行为）。原值保留用于展示/登录输入。
- `role`：`operator` | `engineer`。
- `password_hash`：复用 B1a `hash_password`/`verify_password`（`robot_ai/library/auth.py`，pbkdf2_sha256，策略 iterations 200k）。
- `enabled`：bool；`false` = 禁用。**不做物理删除**——UI"删除"即 `enabled=false`。
- `pending_audits`：根 outbox（沿用 `versioned_registry.py` 的 `_commit_with_audit` + `drain_pending_audits` 模式）；用户管理操作与 audit 同次 `atomic_write_json`，统一 drain。

原子写：`atomic_write_json`（`robot_ai/library/storage.py`，temp+fsync+os.replace）。

新增 `UserRegistry`（`robot_ai/library/users.py`，模式同 `VersionedCommandRegistry`）：`_load`/`_save`/`_commit_with_audit`/`drain_pending_audits` + 用户 CRUD。

`normalize_username()`（`robot_ai/library/users.py`）：`(s or "").strip().casefold()`；带冲突测试（`"Admin"`/`"admin"`/`" ADMIN "` → 同一归一化 → 创建冲突 409）。独立单测，与 `normalize_id` 互不影响。

---

## 3. 统一会话与鉴权

### UserSessionStore（内存，取代 B1a `EngineerTokenStore`）

`robot_ai/library/auth.py` 新增（`EngineerTokenStore` 移除）：
```python
@dataclass
class UserSessionStore:
    ttl_seconds: int = 8 * 3600
    _sessions: dict[str, dict] = field(default_factory=dict)  # token -> {user_id, username, role, expiry}

    def issue(self, user: dict) -> str: ...        # secrets.token_urlsafe(32); 存 expiry=monotonic+ttl
    def check(self, token: str) -> dict | None: ... # 返回 session 或 None（过期清理）
    def revoke(self, token: str) -> None: ...
    def revoke_by_user_id(self, user_id: str) -> None: ...  # 禁用/降级/改密时立即踢出该 user 所有 session
```
TTL 8h；过期清理（issue/check 时 `_purge`）；**不 refresh**——刷新/重启/到期均重登。token 不持久化、不入 localStorage（前端，切片②）。

### 鉴权链路

- **传输层**：gateway token（`Authorization: Bearer` / `?token=`，bootstrap，localhost 自动）。
- **身份层**：`X-Nanobot-User-Token`（user session token）。
- **登录**：`{username, password, role}` → 查 user（`normalize_username` 归一化 + role 匹配 + `enabled`）→ `verify_password` → `issue` → 返回 `{user_token, user:{user_id,username,role}, expires_in}`。
- **API 鉴权矩阵**：

| 端点 | gateway token | user token | role |
|---|---|---|---|
| `POST /api/auth/login` | ✓ | — | — |
| `POST /api/auth/logout` | ✓ | ✓ | — |
| `/api/users/*`（list/create/patch/reset-password） | ✓ | ✓ | engineer |
| `POST /api/users/me/password` | ✓ | ✓ | — |
| B1a `/api/robot/engineer/*`（命令/审计业务） | ✓ | ✓ | engineer |
| 操作员业务（机器人控制等） | ✓ | ✓ | operator（逐步接入；切片① 不强制改全部） |

`role=engineer` 不匹配 → `403`。

---

## 4. 角色与权限矩阵

| 能力 | operator | engineer |
|---|---|---|
| 聊天（各自命名空间，切片②） | ✓ | ✓ |
| 机器人执行/控制 | ✓ | ✓ |
| 只读命令/流程库 | ✓ | ✓ |
| 命令库管理（草稿/发布/归档/编辑器） | ✗ | ✓ |
| 组件库查看 | ✓（只读） | ✓ |
| 审计查看 | ✗ | ✓ |
| 用户管理 + 改密 | ✗ | ✓（兼管理员） |

engineer 暂兼管理员（用户管理）。未来需"工程师非管理员"再加 `admin` 层，**现在不混第三角色**。

---

## 5. API 面

所有 `/api/auth/*` `/api/users/*`：响应 `Cache-Control: no-store` + `Pragma: no-cache`（沿用 B1a）。传输双轨：aiohttp 真 POST/PATCH（非浏览器客户端）+ ws_http GET+`X-Nanobot-Robot-Body` 头（`X-Nanobot-User-Token` 身份头）。

```
POST /api/auth/login            [body {username,password,role}] -> {user_token, user, expires_in} | 401 | 403(disabled) | 429
POST /api/auth/logout           -> 撤销当前 user token
GET  /api/users                 -> {users:[{user_id,username,role,enabled,created_at,updated_at}]}  # 不含 password_hash
POST /api/users                 [body {username,password,role}] -> 创建（engineer）；username 冲突 -> 409
PATCH /api/users/{user_id}      [body {enabled?,role?}] -> 禁用/启用/改角色（engineer）；最后 engineer 保护 -> 409
POST /api/users/{user_id}/password  [body {new_password}] -> 重置他人密码（engineer）；target==self -> 409
POST /api/users/me/password     [body {old_password,new_password}] -> 改自己密码（任何已登录；必验旧密码）
```

- **不提供 DELETE**（物理删除）；UI"删除" = `PATCH enabled=false`。
- list/create/patch/reset-password 需 `role=engineer`。
- **`POST /api/users/{user_id}/password` 拒绝 `user_id == 当前 actor 的 self_id`**（409 `code:"use_me_password"`）：防止 engineer 用重置端点绕过 `me/password` 的旧密码校验。**自身改密只能走 `/api/users/me/password`**（验旧密码）。
- list 响应**不含 `password_hash`**。

---

## 6. 用户管理操作（原子 outbox + 最后 engineer 保护 + session 撤销）

### 原子 outbox
create / disable / enable / role-change / reset-password / me-password 每个操作：
1. `UserRegistry` 修改 `users` + `pending_audits.append({audit_id, action, actor, actor_user_id, actor_username, actor_role, target:{user_id}, payload:{...}, timestamp})`。
2. 一次 `atomic_write_json(users.json)`。
3. drain：append audit entry → `audit.jsonl` → 移除 outbox 项（幂等，沿用 `drain_pending_audits`）。

### 最后 engineer 保护
- **disable**：若 `user.role==engineer && user.enabled && enabled_engineer_count()<=1` → `ConflictError`（409，`code:"last_engineer_protected"`）。
- **role-change `engineer→operator`**：若该 user 是最后 enabled engineer → `ConflictError`（409）。
- 防止永久锁死管理入口。

### session 撤销（立即失效，覆盖所有身份变更）
任何改变用户登录身份或凭据的操作成功后，调 `UserSessionStore.revoke_by_user_id(target)`，使其已签发 token 立即失效（不等 8h 过期）：
- **reset-password**（管理员重置他人）→ `revoke_by_user_id(target)`。
- **me/password 成功**（改自己密码）→ `revoke_by_user_id(self)`，要求当前会话重新登录。
- **任意 role-change**（不只 `engineer→operator`，也包括 `operator→engineer` 等所有角色变更）→ `revoke_by_user_id(target)`。
- **disable**（enabled true→false）→ `revoke_by_user_id(target)`。

---

## 7. 迁移（B1a → 多用户）

### 启动初始化（分域，不混命令库）
`_run_gateway`（`nanobot/cli/commands.py`）显式顺序调用两个**各自幂等、各自 drain**的初始化函数：
```
initialize_robot_libraries()  -> initialize_user_identity(gateway_secret=...)  -> gateway
```
- `initialize_robot_libraries()`（B1a，命令库域）**保持不变**，不塞身份逻辑。
- 新增 `initialize_user_identity(users_path=None, audit_path=None, gateway_secret=None)`（身份域，`robot_ai/library/migration.py` 或 `users.py`）：`migrate_users_if_needed(...) → UserRegistry(...).drain_pending_audits()`。

### migrate_users_if_needed
- `users.json` 存在 → no-op（幂等）。
- `users.json` 不存在 → 创建：
  - **`admin`（engineer）**：读 config `robot_ai.engineer.password_hash`（B1a）；若存在且非空 → `admin` 账户 `password_hash` = 该 hash（用户用原 B1a 工程师密码登录 `admin`）。**若不存在/为空 → `admin` 禁用占位**（`enabled=false`，随机占位 hash），由 CLI bootstrap 启用（见下）。
  - **`operator`**：读 **gateway config 的 `token_issue_secret`（优先）或 `token`**（`nanobot/webui/ws_http.py:327` `_handle_bootstrap` 用同一来源，后端运行时可读；从 gateway config 传入 `initialize_user_identity(gateway_secret=...)`）。**仅当该 secret 非空可读** → `operator` 账户 `password_hash = hash_password(secret)`（operator 用旧 secret 登录）。**若 secret 为空/不可读 → 创建禁用的 `operator` 占位**（`enabled=false`，随机占位 hash），由 `admin` 后续 `POST /api/users/{id}/password` 设置密码。
  - **绝不**把 gateway **API token**（bootstrap 后的临时 session token）当用户密码——只读 config 的 `token_issue_secret`/`token` 持久字段；若两者皆空，operator 一律禁用占位，不猜测、不 fallback 到任何运行时 token。
- 迁移本身写一条审计（`action:"users_migration"`，`actor:"system:migration"`，`actor_role:"system"`，`payload:{admin_from_b1a_hash:bool, operator_from_secret:bool}`）。

### CLI bootstrap（修复首次安装锁死）
若没有 B1a engineer hash，`admin` 被建为禁用占位 → 没有任何启用 engineer 能设密码 → 锁死。新增 CLI：
```
nanobot users set-bootstrap-password --username <name>
```
- **仅 `getpass` 隐藏输入**（沿用 B1a `engineer set-password` 模式）；**不接受 `--password` 参数或任何命令行明文**（"密码不出现在 args" 硬约束；脚本化的 stdin/secret-provider 后续另行设计，不在本切片）。
- 原子操作：设该 username 的 `password_hash = hash_password(pw)` 且 `enabled=true`（一次性 outbox 原子写 + 审计 `user_bootstrap_password`，`actor:"system:cli"`）。
- username 必须存在（迁移占位）；不存在 → 报错（不通过 CLI 隐式建账户）。
- 测试：无 B1a hash 全新安装 → `migrate_users` 建 `admin` 禁用占位 → `nanobot users set-bootstrap-password --username admin` → `admin.enabled=true` + 可登录。

---

## 8. B1a 兼容策略

**目标**：不并行第二种 token；B1a engineer 能力平滑切到统一 user token。

- **`/api/robot/engineer/login`**：保留为**兼容别名**。内部调统一 `process_auth_login({username:"admin", password, role:"engineer"})`，返回**同一 user token**（`user_token` 字段；兼容期响应也可带 `engineer_token` 同值字段供旧调用方，但底层是 user token）。**不签发独立的 engineer token**。
- **`X-Nanobot-Engineer-Token` header**：**过渡期**作 `X-Nanobot-User-Token` 的**同值别名**（鉴权层两者都接受，等价）。切片② 前端**只用 `X-Nanobot-User-Token`**。
- **B1a engineer 业务 endpoints**（`/api/robot/engineer/commands/*`、`/audit`）：鉴权从 `gateway token + engineer token` 改为 `gateway token + user token + role=engineer`。业务逻辑（`VersionedCommandRegistry`、`_validate_publish_params`、audit pagination、命令 CRUD）**完全保留**，仅鉴权层切换。
- **移除**：B1a `EngineerTokenStore`、`process_engineer_login`/`process_engineer_logout`（并入 `process_auth_login`/`process_auth_logout`）。`LoginThrottle` **复用**（节流键调整见 §11）。
- **`nanobot engineer set-password`（B1a CLI）→ 弃用别名**：身份层上线后**不再只改 config `robot_ai.engineer.password_hash`**（否则 `admin` 的 users.json 密码不变，用户误以为改密成功）。保留命令为**弃用别名**：内部改为更新 `admin` 用户（users.json）的密码（原子 outbox 写 + 审计 `user_password_change`，`actor:"system:cli"`），并输出迁移提示（指向 `nanobot users set-bootstrap-password` 或工程师设置 UI）。测试：别名改密 → `admin` 可用新密码登录；登录鉴权只认 users.json，config `password_hash` 不再是凭据来源。
- **B1a 测试更新**：`test_engineer_login.py` 等更新到统一 user token + 兼容别名（不删兼容路径测试）。

**不破坏**：B1a 命令管理业务能力（已提交 `b02e3491`）零改动逻辑，仅鉴权层切。

---

## 9. 审计

### actor 格式（兼容 + 结构化）
- `actor`：兼容字符串 `"user:<user_id>"`（**不把原有 string `actor` 改成对象**；`audit.jsonl` 现有 string actor 不变）。
- `actor_user_id` / `actor_username` / `actor_role`：新增结构化字段。
- 系统事件（迁移/CLI bootstrap）：`actor:"system:migration"`/`"system:cli"`，`actor_role:"system"`，无 `actor_user_id`/`actor_username`。

### 审计事件
- `user_login`（success/failure，含 `reason`）/ `user_logout`
- `user_create` / `user_disable` / `user_enable` / `user_role_change`
- `user_password_reset` / `user_password_change` / `user_bootstrap_password` / `users_migration`
- B1a 命令管理审计（`command_create` 等）的 `actor` 改真实用户身份（之前固定 `"engineer"`）。

### 写法
- **用户管理操作** → outbox 原子写（§6）。
- **登录** → 直接 `_audit_append`（成功 **fail-closed**：`OSError` → revoke 刚发 token + 503 不发 token，沿用 B1a；失败 best-effort）。
- **系统迁移 / CLI bootstrap** → 直接审计。

---

## 10. 会话命名空间基础（为切片②）

切片① 定义 `user_id`。切片② 实现会话隔离：
- session metadata（`.jsonl` 首行 metadata）加 `namespace` = `"{role}:{user_id}"`（如 `engineer:<uid>`、`operator:<uid>`）。
- `list_sessions` 支持 `?namespace=` 过滤；`new_chat` WS 帧带 `namespace`。
- 前端 `useSessions(namespace)` + `useSidebarState(namespace)`；双 Shell 各自命名空间。
- 切片① 只需保证 `user_id` 稳定可用（不实现 session 隔离本身）。

---

## 11. 安全

- **timing**：`verify_password` 已 harden（B1a D8：每失败路径 dummy PBKDF2）。login 复用。
- **节流**：复用 `LoginThrottle`（`auth.py`）。键 = `username:role`（账户级，防定向爆破）**叠加** gateway token 客户键（B1a D2）。任一超限 → 429 + `Retry-After`（HTTP header，两传输，沿用 B1a R5）。
- **成功审计 fail-closed**：login 成功 → `_audit_append`；`OSError` → revoke token + 503 不发 token（沿用 B1a）。
- **不 refresh**：token 仅内存 8h；刷新/重启/到期重登。**无 refresh token**。
- **改密验旧**：`me/password` 必验 `old_password`（错 → 401）；重置端点拒绝 self（§5）。
- **最后 engineer 保护**（§6）。
- **身份变更立即踢出**（§6）：reset-password / me-password / 任意 role-change / disable → `revoke_by_user_id`。
- **密码不出现**在 args / 响应 / 日志 / 审计 / list 输出（沿用 B1a）。
- **响应 no-store**（沿用 B1a）。
- **disabled user**：login 查 `enabled` → 拒（403）；disable 时 `revoke_by_user_id`。

---

## 12. 测试（pytest，`.venv-robot-desktop`）

- **用户模型 + `normalize_username`**：create（归一化/唯一/role/enabled/默认 enabled=true）；`normalize_username` 冲突（`"Admin"`/`"admin"`/`" ADMIN "` → 同一归一化 → 创建 409）；**独立于 `normalize_id`**（断言改 `normalize_username` 不影响命令 ID 归一化）。
- **UserSessionStore**：issue/check/revoke/revoke_by_user_id/expiry/不 refresh。
- **登录**：success / fail（错密码）/ role-mismatch（user 存在但 role 不符 → 401，不泄露 user 存在）/ disabled（403）/ 节流 429 + Retry-After / 成功审计 fail-closed（审计写失败 → 503 不发 token）/ dummy PBKDF2 timing。
- **用户管理**：list（不含 password_hash）/ create / patch（disable/enable/role-change）/ reset-password；**outbox 原子写 + drain**（状态与 audit 同次）；**最后 engineer 保护**（禁用/降级最后 enabled engineer → 409）；**无物理 DELETE 端点**。
- **self_id 绕过拒绝**：engineer 用 `POST /api/users/{self_id}/password` → 409 `use_me_password`（必须走 `me/password` 验旧密码）。
- **me/password**：验旧密码成功；旧密码错 → 401；成功后 `revoke_by_user_id(self)` → 当前 token 立即失效。
- **session 撤销覆盖**：reset-password(target)→target token 失效；me/password→self token 失效（要求重登）；**任意 role-change**（含 operator→engineer）→target token 失效；disable→target token 失效。
- **迁移**：users.json 不存在 → `admin`（B1a hash 存在→保留可登；**不存在→禁用占位**）+ `operator`（gateway secret `token_issue_secret`/`token` 存在→`hash_password(secret)`；**不存在→禁用占位**）；**绝不把 gateway API token 当密码**（断言：secret 缺失时 operator 占位 password_hash 是随机占位、enabled=false，非任何运行时 token）；幂等（二次 no-op）；迁移审计条目。
- **CLI bootstrap**：无 B1a hash 全新安装 → `migrate_users` 建 `admin` 禁用占位 → `nanobot users set-bootstrap-password --username admin`（mock getpass）→ `admin.enabled=true` + `hash_password` 写回 + 可登录；username 不存在 → 报错。
- **CLI bootstrap 无明文参数**：`nanobot users set-bootstrap-password --username admin --password x` → 拒绝（`--password` 不被接受）；密码仅经 `getpass`。
- **`nanobot engineer set-password` 弃用别名**：调用 → 改 `admin`（users.json）密码（原子 outbox + 审计）+ 输出迁移提示；`admin` 用新密码可登录；config `robot_ai.engineer.password_hash` 不再用于登录鉴权。
- **审计 actor**：`actor=="user:<user_id>"` + `actor_user_id`/`actor_username`/`actor_role` 三结构化字段；系统迁移 `actor=="system:migration"`；CLI `actor=="system:cli"`；密码/token 不入审计。
- **兼容**：`/api/robot/engineer/login` 别名返 user token（默认 admin/engineer）；`X-Nanobot-Engineer-Token` 同值别名鉴权通过；命令 endpoint 用 user token+role=engineer 可访问。
- **角色授权**：operator user token 访问 `/api/users` POST 或 `/api/robot/engineer/commands` POST → 403；engineer 访问 → 通过。
- **初始化分域**：`_run_gateway` 顺序 `initialize_robot_libraries() → initialize_user_identity(gateway_secret=...)`；两函数各自幂等 + 各自 drain（断言 drain 各调一次）。
- **B1a 回归**：B1a 命令管理测试（versioned registry、publish schema、audit pagination）在统一鉴权下仍绿（鉴权夹具改 user token）。

---

## 13. 验收标准

- `nanobot` 启动：`initialize_robot_libraries → initialize_user_identity → gateway`；产出 `admin`（B1a 工程师密码可登，或禁用占位待 CLI bootstrap）+ `operator`（gateway secret 可登 or 禁用占位）。
- 无 B1a hash 全新安装：`nanobot users set-bootstrap-password --username admin`（getpass，**无 `--password` 参数**）→ 可登录 admin（无锁死）。
- `nanobot engineer set-password`（弃用别名）改 `admin` 密码 + 迁移提示；身份层后登录鉴权只认 users.json，不认 config hash。
- 统一 `/api/auth/login` 双角色登录，签发 user token；旧 `/api/robot/engineer/login` 兼容别名返同一 token；`X-Nanobot-Engineer-Token` 同值别名过渡。
- 用户管理 CRUD（无物理删除，禁用代替；最后 engineer 保护；**身份变更/改密立即撤销 session**；self 改密禁走重置端点）。
- 全审计（`actor="user:<user_id>"` + 结构化字段）；登录成功审计 fail-closed；密码/token 不入审计。
- B1a 命令管理业务保留（逻辑零改），鉴权切 user token+role=engineer；B1a 测试更新通过。
- token 内存 8h 不 refresh；刷新/重启重登；无 refresh token。
- 后端 pytest 全绿（含 B1a 回归）；ruff clean。

---

## 14. 决策记录

1. 统一身份层 `/api/auth/*` + `/api/users/*`；gateway token 降为传输层凭证，不再兼任用户身份。
2. 用户存储独立 `users.json`（`atomic_write_json` + `pending_audits` outbox），不混 `config.json`。
3. `UserSessionStore`（内存 user token，TTL 8h，**不 refresh**）取代 B1a `EngineerTokenStore`。
4. 角色 `operator`/`engineer`；engineer 兼管理员（未来才分 `admin`，不混第三角色）。
5. **不物理删除用户**（禁用代替）；**最后 engineer 保护**（禁用/降级最后 enabled engineer → 409）。
6. 迁移：B1a 工程师密码 → `admin`；gateway secret → `operator`（或禁用占位）；**绝不迁 gateway API token 当密码**。
7. B1a engineer API 兼容别名（统一 user token，**不并行第二种 token**）；`X-Nanobot-Engineer-Token` 过渡同值别名；切片② 前端只用 `X-Nanobot-User-Token`。
8. 审计 `actor` 保持兼容字符串 `"user:<user_id>"`（**不改 string 为对象**）+ 新增 `actor_user_id`/`actor_username`/`actor_role` 结构化字段。
9. 用户管理操作走 outbox 原子写（状态+audit 同次 `atomic_write_json` + drain）；登录直接审计（成功 fail-closed）。
10. 节流键 `username:role` + gateway token（D2 叠加）。
11. **不做 refresh token**（避免持久化凭证）。
12. `user_id` 为切片② 会话命名空间 `<role>:<user_id>` 的键；切片① 只定义 user_id，不实现 session 隔离。
13. **身份变更/改密立即撤销 session**：reset-password / me-password / 任意 role-change / disable → `revoke_by_user_id`（不等 8h 过期）。
14. 首个 engineer username `admin`，首个 operator username `operator`（迁移默认）。
15. **`normalize_username()` 独立**（strip+casefold），**不复用 `normalize_id`**（命令 ID 域隔离，避免改用户名规则影响命令 slug）。
16. **CLI `nanobot users set-bootstrap-password`** 修复首次安装锁死（无 B1a hash 时 admin 禁用占位 → CLI 原子设密码+启用）；username 必须已存在（不隐式建账户）。
17. **初始化分域**：`initialize_user_identity` 独立于 `initialize_robot_libraries`（身份域 vs 命令库域）；`_run_gateway` 显式顺序 `initialize_robot_libraries() → initialize_user_identity(gateway_secret=...) → gateway`；两函数各自幂等 + 各自 drain。
18. **self 改密禁止走 `/api/users/{self_id}/password`**（防绕过旧密码校验，409 `use_me_password`）；自身改密只能 `/api/users/me/password`（验旧密码）。
19. **gateway secret 字段精确**：`token_issue_secret`（优先）或 `token`（gateway config，`ws_http.py:327` 同源读取）；从 gateway config 传入 `initialize_user_identity(gateway_secret=...)`；两者皆空 → operator 禁用占位，**绝不** fallback 到任何运行时 API token。
20. **CLI 不接受命令行密码参数**：`nanobot users set-bootstrap-password` 仅 `getpass`（"密码不出现在 args" 硬约束）；脚本化 stdin/secret-provider 后续设计，不在本切片。
21. **`nanobot engineer set-password` 弃用别名**：身份层后不再只改 config hash（避免 `admin` users.json 密码不变的假成功）；内部改 `admin` users.json 密码 + 迁移提示；登录鉴权只认 users.json。
