# 机器人命令/组件知识库 — A1 后端独立交付设计

日期：2026-07-11
状态：已确认，待实施计划
关联：本文件是 `2026-07-11-robot-knowledge-and-engineer-console-design-draft.md`（北极星草案）阶段 A 的**第一个可独立交付子项目**。阶段 B/C/D 及 A2 各自后续单独走 spec → 计划 → 实现周期。

## 1. 目标与边界

A1 交付一个**纯后端、可独立验证**的本地命令/组件知识库地基：数据模型、原子注册表、只读组件目录、legacy 迁移、只读 API。不改任何前端文件、不碰真机、不实现编辑/版本历史/工程师鉴权。

**In scope（A1 交付）：**

- `Command` / `Component` / `AuditEntry` Python 模型与枚举。
- 原子 `CommandRegistry`（`commands.json`）+ 只读 `ComponentCatalog`（内置 4 组件，不落盘）。
- `query_table.json → commands.json` 可重复迁移 + 迁移报告 + 审计汇总。
- 只读 `/api/robot/library/*` API（token 闸门、筛选、详情、稳定错误格式）。
- pytest 覆盖模型 / 迁移 / 原子写 / API / 非法参数 / 未授权访问。

**Out of scope（留后续阶段）：**

- 多版本历史存储、`?version=` 查询、编辑/草稿/发布/归档端点 → **阶段 B**。
- 工程师鉴权（本地口令 / 角色 / 独立 token）→ **阶段 B**。
- 流程步骤升级为 `{command_id, version}` 引用 + legacy 流程兼容层 → **阶段 C**。
- 操作员命令库/组件库前端页面、移除操作员导航里的 Apps/Skills → **A2**（紧随 A1）。
- 真机写入、执行链路改动 → 不涉及。

**硬约束：** 不修改 `App.tsx`、`RobotOperatorApp.tsx` 或任何现有前端文件。

## 2. 可复用基础（现有代码）

- `robot_ai/flow/registry.py` 的 FlowRegistry 原子写模式（temp + fsync + os.replace）——A1 **不复用其代码**，新增独立 `atomic_write_json()`，FlowRegistry 保持不动。
- `nanobot/api/robot_routes.py` 的 `process_*` / `handle_*` 拆分、`_error_json(status, message, err_type)`、`RobotResult` 信封（`{ok, state, data, errors}`）。
- `nanobot/webui/ws_http.py` 的 `_dispatch_robot_routes`：维护 `/api/robot/*` 路径表并先调 `self.check_api_token(request)` 做中心鉴权，再 dispatch 到 `process_*`。library 端点挂这里，自动继承 token 闸门。
- `tools/migrate_robot_flows.py` 独立迁移脚本范式。
- 数据目录约定 `~/.nanobot/robot_ai/`（`os.path.expanduser("~")`，无 env / config）。
- `data/legacy/query_table.json`：21 条记录，字段 `query_key / func_num / keywords / description / safety_level / params`。

## 3. 模块布局

新增子包 `robot_ai/library/`（与现有 `robot_ai/knowledge/` 区分——后者是文档/FAQ 知识库，概念不同）：

| 文件 | 职责 |
|---|---|
| `models.py` | `Command`、`Component`、`ParameterField`、`AuditEntry` + `RiskLevel` / `CommandStatus` 枚举 |
| `catalog.py` | `ComponentCatalog`——4 个内置组件，只读 |
| `registry.py` | `CommandRegistry`——原子持久化、幂等播种、查询 |
| `migration.py` | `query_table.json → commands.json` 迁移逻辑 + 报告 |
| `storage.py` | 独立 `atomic_write_json(path, payload)` 工具 |

API 侧：`nanobot/api/robot_routes.py` 新增 `process_robot_library_*` 函数；`ws_http._dispatch_robot_routes` 的路径表（ws_http.py:396-403）新增 4 条 library 路径并加 GET dispatch 分支，**复用其中心 `check_api_token` 闸门**。`ws_http.py` 为后端文件（已被操作员台改动过），符合「不碰前端」约束。

## 4. 数据模型

### 4.1 Command

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `str` | 稳定 id，迁移时由 `query_key` 确定性归一化生成（lower + trim + 空白折叠为 `-`），保证重跑幂等 |
| `name` | `str` | 取自 `query_key`；**全局命名空间唯一**（见 §5） |
| `aliases` | `list[str]` | 取自 `keywords` 分词，去重，剔除 name 本身及与已入库命令冲突项 |
| `description` | `str` | 取自 `description` |
| `component_id` | `str` | 由 `func_num` 映射（仅 104/108/110/120） |
| `parameters` | `dict` | 取自 `params`，按组件 schema 校验类型与必填 |
| `risk_level` | `RiskLevel` | `safety_level` 映射（见 4.5） |
| `status` | `CommandStatus` | 迁入即 `published` |
| `version` | `int` | **前向兼容预留字段，A1 固定为 `1`**。A1 不维护版本集合 / 历史，每条命令仅存单条当前记录 |
| `source` | `str` | 迁入记录为 `legacy-import` |
| `created_at` / `updated_at` / `published_at` | `str` (ISO) | 时间戳 |
| `created_by` | `str` | 迁入为 `system:migration` |

**版本语义边界（本次修正）：** A1 只建模 `version` 字段以兼容阶段 B 的草稿→发布流程，**不建立独立版本集合、不提供历史版本读取、不提供 `?version=` 查询**。`GET /commands/{id}` 只返回当前唯一记录。

### 4.2 Component

平台受控的原子能力，4 个内置（与草案 §4.2 一致）：

| component_id | func_num | name | 参数 schema |
|---|---|---|---|
| `system_action` | 104 | 系统动作 | `stop_mode`(int 0-1)、`estop_ctrl`(int 0-2)、`pause_ctrl`(int 0-2)、`cancel_ctrl`(int 0-2)、`reset_ctrl`(int 0-1) |
| `linear_move` | 108 | 直线/位姿移动 | `target_x/y/z`(float, mm)、`target_rx/ry/rz`(float, deg)、`spd_pct`(float 0-100)、`acc_pct`、`dec_pct`、`move_type`(int 0-1)、`stop_cmd`(int)、`fuzzy_pos/spd/acc/dec`(int 0-1) |
| `delay` | 110 | 延时 | `delay_sec`(float, >0, sec) |
| `io_write` | 120 | IO 写 | `io_no`(int ≥0)、`io_action`(int 0-1) |

每个 `ParameterField` 带 `type` / `unit` / `range` / `default` / `required`。组件还带 `required_safety_state` 与 `flow_eligible`。`ComponentCatalog` 纯内置 Python dataclass，**不落 `components.json`**（组件平台受控、工程师永不可编辑，落盘为 YAGNI）。

### 4.3 AuditEntry

`audit.jsonl`，append-only，每行一条 JSON：

| 字段 | 说明 |
|---|---|
| `action` | 如 `legacy_import` |
| `actor` | 如 `system:migration` |
| `target` | 可选，`{id, version}`（命令级；迁移级用 `migration_id`） |
| `migration_id` | 可选，迁移级审计的稳定去重键（见 §6） |
| `before` / `after` | 摘要（迁移为汇总对象，见 §6） |
| `timestamp` | ISO |

A1 中唯一写审计的事件是迁移导入。

### 4.4 枚举

- `RiskLevel`: `low` / `medium` / `high` / `critical`
- `CommandStatus`: `draft` / `published` / `archived`（A1 仅用 `published`，其余为前向兼容）

### 4.5 risk_level 映射

legacy `safety_level` 全部为 `5` → 映射 `high`（保守）。映射规则集中在一个函数，便于阶段 B 调整。

## 5. CommandRegistry / ComponentCatalog

**CommandRegistry**（`~/.nanobot/robot_ai/commands.json`）：

- 原子写：`storage.atomic_write_json(path, payload)` —— temp + fsync + os.replace（独立实现，不改 FlowRegistry）。
- payload：`{version:"1.0", updated_at, commands:[...]}`。
- 幂等播种：迁移对已存在 `id` 的已发布记录为 no-op，不覆盖、不重复。
- 查询：`get(id)` 返回当前单条记录；`list(*, component_id, risk_level, status, q)` 按 component_id/risk_level/status 精确过滤，`q` 在 name+aliases 上子串匹配。
- 不变量：`id` 唯一；**全局命名空间唯一**——任一命令的 `name` 及其 `aliases` 不得与任何其他命令的 `name` 或 `aliases` 冲突（否则名称/别名查询歧义）。`add(command)` 强制校验，冲突即拒绝。

**ComponentCatalog**：内存只读，`list()` / `get(id)` 直接返回内置 dataclass。

## 6. 迁移：`query_table.json → commands.json`

CLI `tools/migrate_robot_commands.py`（镜像 `tools/migrate_robot_flows.py`）→ 调 `robot_ai.library.migration`。

**映射：**

| legacy | Command |
|---|---|
| `query_key` | `name`；`id` = 归一化 slug |
| `keywords` | `aliases`（分词、去重、剔除 name 与跨命令冲突项） |
| `func_num` | `component_id`（仅 104→system_action / 108→linear_move / 110→delay / 120→io_write） |
| `params` | `parameters`，按组件 schema 校验：必填字段缺失或类型不符 → 该记录 skip |
| `safety_level` | `risk_level`（5→high） |

**落库：** `status=published`、`source=legacy-import`、`version=1`、`created_by=system:migration`（审计见下）。

**命名空间去重（全局唯一）：** 迁移按确定性顺序处理记录，维护全局已用集合 `seen = ⋃({name} ∪ aliases)`。若记录 `name` 已在 `seen`（含与既有 alias 冲突）→ 整条 skip 并报告；否则登记 `name`，再逐条登记未冲突的 alias（冲突 alias 丢弃并计数）。

**不可映射记录处理（决策 a：跳过 + 报告）：** func 106（关节点动）/ 107（虚拟轴相对移）/ 109（T0 延时，delay 仅映射 110）/ 11（连续插补）的记录**跳过**，不伪装成可用命令。21 条中 16 条迁移为 published，5 条跳过：

| 跳过 func | 记录 | 原因 |
|---|---|---|
| 106 | J1到10度、J2回正 | v1 组件集不含 joint_move |
| 107 | X前进50 | v1 组件集不含虚拟轴相对移 |
| 109 | T0延时1秒 | delay 仅映射 Func110，109 不映射 |
| 11 | 连续插补示例 | v1 组件集不含连续插补 |

**报告：** 迁移命令向 stdout 打印人读报告，完整记录迁移结果——migrated N（逐条 `id`+`name`）与 skipped M（逐条 `func_num`+原因），使报告本身即迁移结果凭证。

**审计与两文件失败语义：** `commands.json` 与 `audit.jsonl` 是两个文件，无法跨文件原子提交。规则：

1. `migration_id = "legacy-import:" + sha256(query_table.json 字节)[:12]`——源不变则 id 不变。
2. 顺序：先原子写 `commands.json`（幂等播种，已存在 id 跳过），再追加 `audit.jsonl`。
3. 追加前扫描 `audit.jsonl`：已存在同 `migration_id` 条目则跳过（去重）。
4. 审计条目：`{action:"legacy_import", actor:"system:migration", migration_id, after:{migrated:16, skipped:5, skipped_by_func:{106:2,107:1,109:1,11:1}, skipped_reasons:[...]}, timestamp}`，单行 append + flush + fsync。
5. **失败语义：** `commands.json` 写成功但审计追加失败 → 迁移返回失败（非零退出），提示「命令已入库但审计写入失败，重跑补审计」。重跑时 commands 幂等 no-op、扫描无该 `migration_id` → 补追加审计。**不出现「命令已迁入却永久无审计」状态。**

**幂等：** 成功重跑对 commands 为 no-op、审计因 `migration_id` 去重不再追加；报告仍如实输出当前库状态与本次实际新增/跳过数。

## 7. 只读 API

```
GET /api/robot/library/commands            ?component_id&risk_level&status&q
GET /api/robot/library/commands/{id}       只返回当前唯一已发布记录（无 ?version=）
GET /api/robot/library/components
GET /api/robot/library/components/{id}     含参数 schema
```

- 信封：`{ok:true, data:{...}}`；错误走 `_error_json`（`404` 未找到 / `400` 非法筛选参数），格式与现有 robot 路由一致。
- `GET /commands` 的 `data` 为 `{items:[...], total}`；`GET /commands/{id}` 的 `data` 为单条命令；components 同理。
- 挂载于 `ws_http._dispatch_robot_routes` → 自动 token 闸门；GET 无 body，在 body 解析前 dispatch（与 `/api/robot/status` 同款）。
- **A1 不提供 `?version=` 查询、不返回历史版本。**

## 8. 安全

1. 所有 library 端点经 `ws_http._dispatch_robot_routes` 的中心 `check_api_token` 验证（bearer header 或 `?token=`）；无 token → 401。
2. 只读端点仍校验查询参数（非法枚举值 → 400），不信任客户端传入的任意字段。
3. 本地写入（迁移）使用 `atomic_write_json`（temp + fsync + os.replace）；审计 append-only。`commands.json` 与 `audit.jsonl` 跨文件失败语义见 §6（`migration_id` 去重 + 重跑补审计）。
4. 迁移写入 `~/.nanobot/robot_ai/commands.json` 与 `audit.jsonl`，不动 `flows.json`。
5. 工程师写鉴权不在 A1（只读无需）；`created_by` 字段预留以兼容阶段 B。

## 9. 测试（pytest + `tmp_path`，无真机无前端）

镜像 `tests/robot_ai/test_flow_*.py` 范式：

- `test_library_models.py`：Command/Component/AuditEntry 往返序列化；`version` 字段存在且默认 1；枚举取值。
- `test_command_registry.py`：原子写+重载、幂等播种（重跑 no-op）、重复 id 拒绝、**全局命名空间唯一**（name 与其他命令 name/alias 冲突 → 拒绝；alias 与其他命令 name/alias 冲突 → 拒绝）、筛选查询（component_id/risk_level/status/q）。
- `test_component_catalog.py`：4 组件齐全、每组件 schema 字段完备、`get` 不存在返回 None/抛错。
- `test_library_migration.py`：16 条迁为 published、5 条按策略跳过、id 确定性、name 冲突整条 skip + alias 冲突丢弃、审计落盘且汇总正确、stdout 报告内容；**两文件失败语义**：模拟审计追加失败 → 迁移返回失败、重跑补审计且 commands 不重复、成功重跑 `migration_id` 去重不产生重复审计。
- `test_robot_library_routes.py`：无 token → 401；list/detail/筛选；`{id}` 不存在 → 404；非法筛选参数 → 400；稳定错误格式；`?version=` 不被实现 → 400「unsupported parameter」。

## 10. 验收标准

- `robot_ai/library/` 子包 + `tools/migrate_robot_commands.py` 存在且 `ruff check` 通过。
- 迁移 21 条 legacy → 16 条 published 入 `commands.json`、5 条跳过、审计汇总正确、重跑幂等、`migration_id` 去重。
- 4 个只读 API 经 token 闸门可用，返回稳定信封与错误格式；不提供 `?version=`。
- 命令命名空间全局唯一（name ∪ aliases 无跨命令冲突）。
- 全部新增 pytest 通过；不触碰 `App.tsx` / `RobotOperatorApp.tsx` / 任何前端文件。
- 不驱动真机、不改执行链路、不改 FlowRegistry 行为。

## 11. 决策记录

1. **第一刀范围**：A1（纯后端数据层）优于 A2（含前端库页面）/ A3（先收口操作员台）。理由：可独立 pytest 验证、最低风险、不与 28 个未提交前端改动耦合、是 A2/B/C 共同地基。
2. **legacy 迁移落库**：`published` + `source=legacy-import` + `version=1` + 完整审计；日后改动走新草稿版本，不原地改。
3. **不可映射记录**：跳过 + 迁移报告 + 审计汇总（func 106/107/109/11 共 5 条）。不伪装成可执行命令。
4. **原子写**：新增独立 `atomic_write_json()`，**不改 FlowRegistry**，避免无关回归。
5. **ComponentCatalog**：内置只读、不落盘，符合「平台受控组件」边界。
6. **版本语义（本次修正）**：A1 `version` 仅作前向兼容字段（固定 1），不建独立版本集合 / 历史查询 / `?version=`；这些留阶段 B。
7. **命令命名空间全局唯一**：`name` ∪ `aliases` 跨所有命令不得冲突；`add` 强制校验，迁移按确定性顺序去重（name 冲突整条 skip、alias 冲突丢弃）。
8. **两文件失败语义**：`commands.json` 与 `audit.jsonl` 无法跨文件原子提交；用稳定 `migration_id`（源内容哈希）去重，命令先写、审计后追，失败则重跑补审计——杜绝「命令已迁入却永久无审计」。
