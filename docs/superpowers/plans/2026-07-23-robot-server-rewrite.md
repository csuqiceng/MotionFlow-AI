# Robot Server 重写方案

日期：2026-07-23  
状态：待实施（已完成外部评审修订）

## 目标

以单端口、本地运行的 `robot-server` 替代 nanobot 的多渠道 `gateway`。

- 保留 Python 的机械手控制、AI Agent、Electron 与 React WebUI。
- 删除聊天渠道、DM pairing 与多渠道路由等不属于机械手产品的能力。
- 将机械手平台核心与 AI、Web 服务、桌面壳解耦，使其可复用于不同厂商和型号。

不直接采用 pi-web 的 TypeScript/Next.js 技术栈；借鉴其“一个本地应用服务、按功能 API 组织”的运行模型。

## 目标运行结构

```text
Electron / 浏览器
        │ HTTP + WebSocket
        ▼
robot-server（Python，localhost，一个端口）
  ├─ /health
  ├─ /api/auth/*
  ├─ /api/robot/*
  ├─ /api/library/*
  ├─ /api/flows/*
  └─ /ws/agent
       ├─ ai_runtime
       └─ robot_platform
```

## 目标目录

```text
nanobot-main-1/
├─ robot_platform/       # 当前 robot_ai 演进而来；不依赖 Web、AI 或 nanobot
│  ├─ backends/
│  ├─ safety/
│  ├─ execution/
│  ├─ flow/
│  ├─ positions/
│  └─ library/
├─ ai_runtime/           # Agent、Provider、Session、Tools
│  └─ tools/robot_*.py   # AI → robot_platform 的适配器
├─ robot_server/         # 本地 Web 服务
│  ├─ app.py
│  ├─ api/
│  ├─ ws/
│  ├─ auth/
│  └─ static/
├─ webui/
├─ desktop/
└─ tests/
```

目录改名不是第一阶段工作。先完成依赖解耦和运行时迁移，再统一命名。

## 安全与兼容性不变量

- 真实控制器写入默认关闭。
- 确认码、工作区清空确认、急停确认和审计记录不得弱化。
- 本地服务默认绑定 `127.0.0.1`，保留登录、用户与工程师权限控制。
- 保留现有运行数据的读取能力；迁移前创建备份，禁止静默丢失配置、流程或命令库。
- 每一阶段必须可独立运行、可测试、可回退。

## nanobot 子系统去向

| 子系统 | 处理策略 | 最终归属 |
|---|---|---|
| Session、memory、自动压缩 | 保留 | `ai_runtime` |
| Dream 记忆整理 | 保留为可选 AI 能力，可配置关闭 | `ai_runtime` |
| cron 与定时执行 | 保留调度能力，去除渠道投递语义 | `robot_server` |
| 本地 triggers | 只保留流程自动化需要的部分 | `robot_server` |
| MCP | 保留为可选 AI 扩展，默认最小权限 | `ai_runtime` + `robot_server/api/ai` |
| skills | 保留加载机制，产品默认只启用机器人相关 skills | `ai_runtime` |
| email、pairing、渠道插件发现 | 删除 | 无 |

本表是删除遗留代码的依据。未在表中认领的子系统不得直接删除。

## 阶段 1：基线与范围冻结

在独立分支 `codex/robot-server-rewrite` 上工作。

先运行完整的 Python、WebUI、桌面与打包检查，并将失败明确分为：修复、显式 `xfail`、或已知非阻断问题。不得把未分类的既有失败作为回归基线。

建立回归基线：

1. 登录、用户管理与工程师权限。
2. 机器人状态、模拟执行和真实控制器只读诊断。
3. AI 对话、流程库、命令库和位置库。
4. Electron 首次启动、关闭清理和 Windows 打包。

输出：基线测试清单与已通过的测试记录。

同时输出：

1. 本文“nanobot 子系统去向”表的逐项确认。
2. 当前配置字段到目标配置字段的迁移映射。
3. 现有 WebSocket 事件、HTTP 路由和前端调用点清单。

## 阶段 2：解耦机械手核心

目标：当前 `robot_ai/` 不再 import `nanobot.*`。

1. 将 TTS、当前会话 ID 等外部依赖改为明确参数或注入接口。
2. 将机械手能力收敛为公开用例，例如：
   - `get_status`
   - `plan_motion`
   - `execute_confirmed_plan`
   - `run_flow`
   - `emergency_stop`
3. 保留 `nanobot/agent/tools/robot_*.py` 作为临时 AI 适配层，但它们只能调用公开用例。
4. 新增 import 边界测试，保证机械手核心不依赖 AI、Web 服务或 UI。
5. 完成厂商耦合审计：列出 ZMotion、功能号、轴数量、坐标系、运动原语和安全限位的硬编码；将其抽象为控制器能力与机械手模型配置。六轴位姿和 ZMotion `func 108` 等现有假设必须被显式处理。

`emergency_stop` 是平台级安全用例，不得依赖 AI Agent、WebUI 或单一厂商适配器；具体控制器实现由 backend 提供，调用与审计路径由平台统一保障。

验收：模拟控制与真实只读诊断行为不变；`robot_ai` 对 `nanobot` 的 import 为零。

## 阶段 2.5：AgentRuntime 可行性 spike

这是进入服务迁移前的硬性前置验证，预计 1–2 个工作日；它不是生产代码重写阶段。

1. 构造最小 `web` 来源适配器，直接向 `MessageBus` 投递 `InboundMessage`，并订阅 `OutboundMessage`。
2. 不启动 `ChannelManager`、`BaseChannel` 或任何外部聊天渠道。
3. 验证 AgentLoop/Runner 的单轮对话、流式输出、工具调用、取消、会话历史和错误返回。
4. 记录仍携带渠道语义的字段、分支和元数据，并决定是保留为临时兼容字段还是重构为运行时事件契约。

输出物：`AgentLoop 渠道耦合清单与去渠道化改造方案`，其中包含字段/分支/元数据清单、临时兼容策略、目标运行时事件契约和需要修改的模块；它是阶段 6 的实施依据。

通过标准：Web 来源可以独立驱动 AgentLoop，且无渠道管理器参与。若验证失败，先重构 AgentLoop 的消息契约；不得继续机器人服务迁移。

## 阶段 3：服务选型、单进程并存与 robot-server 骨架

先完成简短 ADR，再选定服务框架：

| 选项 | 优点 | 风险 |
|---|---|---|
| aiohttp | 复用现有 API 服务与依赖；单进程迁移成本最低 | OpenAPI/Pydantic 体验较弱 |
| FastAPI + Uvicorn | REST、Pydantic、OpenAPI 与 WebSocket 支持完整 | 需要改写 aiohttp handler，并重新验证 PyInstaller 行为 |

默认优先选择 aiohttp 单进程单端口；只有当最小验证证明其无法满足协议或维护需求时才引入 FastAPI。

并存期规则：Electron 始终只启动一个 Python 子进程。新路由在该进程中与旧 WebSocket/HTTP 路由共存；禁止启动两个后端、两套运行数据或让前端按端口分流。

1. 新建 `robot_server` 组合根和 CLI 入口。
2. 实现 `/health`、静态 WebUI 托管、认证 bootstrap、机器人状态 API。
3. API 改为标准 `POST + JSON`；淘汰现有因 websockets HTTP 限制形成的 GET + 自定义请求头传 JSON 的模式。
4. 新服务在同一进程中与旧 gateway 路由并存，暂不切换用户流量。

验收：新服务以一个端口启动；`/health`、登录 bootstrap 和状态读取可用。

## 阶段 4：迁移机器人 API

将当前过大的 `nanobot/api/robot_routes.py` 分拆并逐类迁移：

```text
robot_server/api/
├─ status.py
├─ execution.py
├─ flows.py
├─ library.py
├─ positions.py
├─ diagnostics.py
├─ engineer.py
└─ users.py
```

每迁移一类 API：

1. 添加接口测试。
2. 前端改用新 API。
3. 旧 gateway 路由仅保留同进程内的短期兼容层。

验收：所有机器人 WebUI 页面可由 robot-server 提供服务。

## 阶段 5：WebUI 传输层兼容迁移

WebSocket 协议当前使用 JSON 文本帧，而非 msgpack；但包含会话、流式输出、reasoning、tool、progress、文件编辑、转录、token 使用量和会话操作等丰富事件。

1. 建立完整的前端入站/出站事件清单与契约测试。
2. 兼容层先对接旧 gateway 的 Agent 事件流验证，确保当前 WebUI 可以零改动地连接新服务。
3. 保持旧事件名称和负载格式，先完成端到端回归。
4. 阶段 6 建立 `AgentRuntime` 后，将兼容层事件数据源从旧 gateway 切换到 `AgentRuntime`，保持前端契约不变。
5. 兼容层稳定后，再单独设计并版本化简化后的新协议；前端协议升级不与服务端替换绑定在同一个阶段。

验收：当前 WebUI 无功能回退地连接 robot-server，且协议契约测试通过。

## 阶段 6：迁移 Agent 通信

1. 新增 `/ws/agent`，会话标识使用 `session_id`，不再使用 `websocket:<chat_id>`。
2. 建立 `AgentRuntime`：接收对话请求，发布 token、tool、progress、final 与 error 事件。
3. 初期复用 nanobot 的 AgentLoop、Runner、Provider 与 Session；不再经过 ChannelManager、BaseChannel 或渠道消息对象。
4. 接入阶段 5 已完成的服务端协议兼容层；不在本阶段重写前端协议。

验收：AI 对话、流式输出、工具提示、会话历史与取消操作正常。

## 阶段 7：切换桌面端与打包

1. 将 `GatewaySupervisor` 改为 `RobotServerSupervisor`。
2. Electron 启动一个 `robot_server.exe`，使用一个随机本地端口。
3. 将 PyInstaller 入口从 `nanobot_gateway.py` 改为 `robot_server.py`。
4. 更新 Windows 打包和冒烟测试，并逐项对照 `desktop/PACKAGING-ISSUES.md` 中的现有打包风险，形成可执行的回归清单。

验收：安装包首次启动、登录、模拟执行与退出清理均正常；关闭后没有残留子进程。

## 阶段 8：删除遗留并模板化

新服务稳定并完成回归后删除：

- `nanobot/channels/email.py`
- `nanobot/channels/base.py`
- `nanobot/channels/manager.py`
- `nanobot/channels/registry.py`
- `nanobot/channels/websocket.py`
- `nanobot/pairing/`、`/pairing` 命令、渠道插件发现和聊天 onboarding
- gateway 后台服务、双端口、`channels.*` 配置和对应测试

最后才进行命名迁移：

- `robot_ai` → `robot_platform`
- `nanobot` → `ai_runtime`

## 配置迁移

目标配置按运行职责组织：

```text
server / auth / agent / providers / tools / scheduler / robot
```

迁移规则：

1. 旧 `channels` 与 `gateway` 仅在迁移读取期兼容，不再作为新配置写回。
2. 旧 `gateway` 的本地监听、健康检查等字段迁入 `server`。
3. `robot_ai` 配置迁入 `robot`；厂商驱动和机械手模型配置显式分层。
4. providers、agent、tools、MCP、skills 和 scheduler 分别保留独立配置边界。
5. 每次配置迁移必须保留原文件备份，并提供可验证的迁移报告。

## 完成标准

- 产品运行时不再出现 gateway、channel、pairing 等多渠道聊天概念。
- 只有一个本地服务端口。
- `robot_platform` 不 import `ai_runtime`、`robot_server` 或 UI。
- WebUI、Electron 和浏览器开发模式都可运行。
- 模拟控制、真实只读、真实写入安全闸门与工程师权限均有回归测试。
- 新机械手厂商只需新增 `robot_platform/backends/<vendor>`，不修改 AI、WebUI 或服务协议。
- AgentRuntime spike、WebUI 协议兼容和配置迁移均有独立的自动化验证。
