# 机器人本地知识库与工程师后台：完整设计方案（草案）

日期：2026-07-11  
状态：待确认；本文件只定义设计与实施边界，不包含实现代码。

## 1. 目标与边界

将当前通用 nanobot WebUI 中的“应用”和“技能”入口从机器人操作语境中移除，建立两个清晰、隔离的工作面：

- **操作员台（Operator）**：只读查看本地命令库与组件库，并通过既有聊天/确认链路发起操作；不允许修改知识或绕过安全门禁。
- **工程师后台（Engineer）**：创建、编辑、校验、发布、归档命令和流程；任何编辑行为都不直接驱动真实机器人。

本次范围不包括旧 Qt 工程的 GUI 或控制器写入代码迁移，也不包括安全中间点、系统参数、授权管理和日志中心的完整重建。这些可在工程师后台稳定后单独规划。

## 2. 现状与可复用基础

当前项目已具备：

- 操作员入口 `#/operator`，复用聊天流并显示机器人状态、位姿与紧急系统操作。
- 流程模型 `robot_ai.flow.FlowEntry` / `FlowStep` 和带原子写入的 `FlowRegistry`。
- 本地知识 `KnowledgeStore`，以及历史命令数据 `data/legacy/query_table.json`。
- 后端机器人 API、执行门禁、干跑、确认、真实执行的既有链路。
- 支持的受限 ZMotion 功能组件：104（系统动作）、108（直线/位姿动作）、110（延时）、120（IO）。

旧项目的工程师后台可以借鉴其“模板列表 + 参数编辑 + JSON 预览 + 流程步骤增删/排序”的信息架构，但不复用其 Qt、自由文本参数或旧写控制器代码。

## 3. 推荐的信息架构

### 3.1 操作员台：三项专用导航

保留现有操作对话/运行中心，并在左侧新增专用机器人导航；不再显示通用的“应用”和“技能”。

| 入口 | 路由 | 目的 | 权限 |
|---|---|---|---|
| 操作台 | `#/operator` | 聊天、设备状态、待确认计划、系统快捷操作 | 可发起操作；仍受门禁控制 |
| 命令库 | `#/operator/commands` | 查询已发布的业务命令、别名、参数摘要、风险级别和关联流程 | 只读 |
| 组件库 | `#/operator/components` | 查询平台支持的原子组件、字段、范围、前置状态和安全语义 | 只读 |

命令库采用“左侧筛选/搜索 + 中间表格或卡片 + 右侧详情抽屉”的三栏模式。组件库复用该框架，但详情展示参数 schema、单位、取值范围、默认值、是否需要确认，以及示例。

### 3.2 工程师后台：独立的受控工作面

新增 `#/engineer`，默认不从操作员台直接暴露；桌面端由工程师入口或受保护的切换动作进入。页面包含：

| 页面/工作区 | 关键能力 |
|---|---|
| 命令管理 | 新建、克隆、编辑草稿、搜索、查看版本、校验、发布、归档；编辑别名、描述、组件选择、结构化参数和安全等级 |
| 流程管理 | 新建/编辑流程、从已发布命令选择步骤、拖动或按钮排序、设置节拍和演练速度、校验、发布、创建新草稿版本 |
| 发布与变更 | 展示当前草稿校验结果、引用关系、版本差异和发布记录；第一版可作为两个编辑页的侧栏/抽屉，而非独立路由 |

工程师后台不提供“执行”按钮。校验只做结构、范围、引用和安全规则检查；真实执行必须回到操作员链路，走既有 dry-run → 明确确认 → execute 流程。

## 4. 本地数据模型与存储

不再让前端直接写 `data/legacy/`。历史文件只作为一次性导入源；运行时唯一权威数据存于用户本地目录：

```text
~/.nanobot/robot_ai/
  commands.json        # 命令版本与别名
  flows.json           # 已存在的 FlowRegistry 目标文件
  components.json      # 组件定义；第一版可由内置 schema 生成后落盘
  audit.jsonl          # 发布、归档、导入、迁移等不可变审计记录
```

### 4.1 命令（Command）

每条命令使用稳定 `id`，包含 `name`、`aliases`、`description`、`component_id`、`parameters`、`risk_level`、`status`（`draft` / `published` / `archived`）、`version`、时间戳与创建/发布人。发布后的版本不可原地修改；编辑会产生同一命令的下一个草稿版本。

### 4.2 组件（Component）

组件是受平台控制的原子能力，而不是任意脚本。第一版仅允许：

- `system_action` → Func104；
- `linear_move` → Func108；
- `delay` → Func110；
- `io_write` → Func120。

组件定义维护字段 schema、单位、范围、默认值、必填字段、所需安全状态、是否可进入流程。工程师只能选择组件并填写其受约束的参数，不能通过 UI 自定义底层 VR 地址、函数号或任意 shell/控制器调用。

### 4.3 流程（Flow）

流程步骤引用已发布命令的 `{command_id, command_version}`，而不是复制自由文本或裸 `query_key`。已发布流程不可编辑；修改自动创建新草稿版本。若待归档命令仍被已发布流程引用，系统拒绝归档并列出引用方。

## 5. 后端 API 与安全设计

新增一个独立的机器人知识/工程师 API 层，复用 gateway token 检查，不把编辑能力混进聊天工具或执行端点。

```text
GET  /api/robot/library/commands
GET  /api/robot/library/commands/{id}
GET  /api/robot/library/components
GET  /api/robot/library/components/{id}

GET  /api/robot/engineer/commands
POST /api/robot/engineer/commands                 # 创建草稿
PUT  /api/robot/engineer/commands/{id}/draft      # 更新草稿
POST /api/robot/engineer/commands/{id}/publish
POST /api/robot/engineer/commands/{id}/archive

GET  /api/robot/engineer/flows
POST /api/robot/engineer/flows                    # 创建草稿
PUT  /api/robot/engineer/flows/{id}/draft
POST /api/robot/engineer/flows/{id}/validate
POST /api/robot/engineer/flows/{id}/publish
POST /api/robot/engineer/flows/{id}/archive
```

安全约束：

1. 所有接口经 gateway token 验证；工程师写接口额外检查本地工程师会话/口令或未来的角色声明。
2. API 只接受白名单 schema；服务端忽略客户端给出的函数号、VR 地址、风险结论和发布时间。
3. 发布前必须服务端校验组件、参数范围、引用命令版本、别名冲突和流程步骤完整性。
4. 每次创建、编辑、发布、归档、导入均追加审计记录，包含操作者、前后版本摘要和时间。
5. 发布、归档和导入使用明确确认对话框；它们不等同于真实机械臂执行确认。
6. 本地写入使用临时文件 + fsync + replace，统一沿用 `FlowRegistry` 的原子持久化模式。

## 6. 前端组件边界

建议新增以下独立模块，避免继续膨胀 `App.tsx`：

```text
webui/src/robot/
  pages/RobotOperatorApp.tsx        # 只负责操作员路由外壳
  pages/EngineerApp.tsx             # 工程师路由外壳
  navigation/RobotNav.tsx           # Operator / 命令库 / 组件库
  library/CommandLibraryPage.tsx
  library/ComponentLibraryPage.tsx
  engineer/CommandManagerPage.tsx
  engineer/CommandEditor.tsx
  engineer/FlowManagerPage.tsx
  engineer/FlowEditor.tsx
  engineer/PublishReviewDrawer.tsx
  hooks/useRobotLibrary.ts
  hooks/useEngineerDrafts.ts
  lib/robot-library-api.ts
```

操作员和工程师共享只读的命令/组件详情组件与 TypeScript 类型；编辑器只出现在工程师入口。工程师入口不再回退到当前通用 nanobot `SettingsView`，而是独立应用壳，以避免 Apps/Skills/Automations 等通用导航污染机器人业务。

## 7. 实施顺序

### 阶段 A：数据与只读知识库（优先）

1. 定义 `Command`、`Component`、版本、校验结果和审计模型。
2. 建立原子 `CommandRegistry` / `ComponentCatalog`，将 legacy `query_table.json` 迁移为命令草稿或已发布初始数据。
3. 实现只读库 API 和操作员端“命令库 / 组件库”页面；移除该上下文下的 Apps/Skills。
4. 测试迁移、查询、筛选、详情、未认证访问和 API schema。

### 阶段 B：工程师命令管理

1. 新增 `#/engineer` 与本地工程师访问控制。
2. 完成命令列表、编辑器、参数表单、草稿保存、校验、发布、归档和审计。
3. 验证已发布命令能被操作员库查询，且编辑草稿不会影响正在使用的已发布版本。

### 阶段 C：工程师流程管理

1. 将流程步骤升级为发布命令引用，同时提供 legacy 流程迁移兼容层。
2. 完成流程编辑器、步骤选择/排序、校验、发布和引用保护。
3. 将操作员执行路径解析到固定的已发布命令版本，保留原有安全检查与确认链路。

### 阶段 D：验收与上线保护

1. Python 单元测试覆盖存储、并发/原子写入、权限、校验、版本与引用保护。
2. Vitest 覆盖所有页面入口、筛选、编辑、发布确认、错误展示和权限隐藏。
3. 用仿真后端做端到端：创建命令 → 发布 → 创建流程 → 发布 → 操作员查询 → dry-run → 确认执行。
4. 真实控制器仅进行单独批准的受控验收；工程师编辑工作流本身不得触发写控制器。

## 8. 方案选择与取舍

### 推荐：专用机器人知识库 + 专用工程师后台

这是本方案。它复用现有 React/WebUI、gateway token、流程注册与安全门禁；数据保持本地、结构化、可审计，且操作员与工程师权限明确。成本是需要新增 API、版本模型和两套页面壳。

### 备选 A：把命令/组件放入现有 SettingsView

开发较快，但操作员导航仍会混入通用 AI 配置，且工程师写入权限难以隔离；不推荐。

### 备选 B：直接编辑 JSON 文件

几乎零后端工作，但无法稳定处理 schema 校验、并发写入、引用关系、版本、审计和权限；不适用于可能连接真实机械臂的系统。

## 9. 验收标准

- 操作员台左侧只出现“操作台、命令库、组件库”，不再出现 Apps 或 Skills。
- 命令库和组件库均可离线查询、搜索、筛选、查看详情，且只读。
- 工程师能以草稿方式新增、编辑、校验、发布、归档命令及流程。
- 发布后的命令和流程有不可变版本；引用关系可追溯，破坏性归档被阻止。
- 所有写入有授权、服务端校验、原子持久化和本地审计。
- 新页面不提供任何绕过既有执行门禁的真实控制器写入路径。
