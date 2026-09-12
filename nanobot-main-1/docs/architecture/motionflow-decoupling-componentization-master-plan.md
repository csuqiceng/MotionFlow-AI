# MotionFlow 完全解耦与组件化总体方案

状态：已批准（主 Agent + 独立架构评审 Agent，第三轮）  
适用分支：`codex-bendi`  
目标：在不破坏当前产品、安全链和发布能力的前提下，将 MotionFlow 建设为可替换机器人 Backend、AI Provider、Tool、Flow Node、WebUI 与桌面产品壳的可扩展平台。

## 1. 执行摘要

MotionFlow 采用“模块化单体 + 稳定契约 + 受控插件”的演进路线。当前阶段不拆仓库、不发布独立 PyPI/npm 包，也不引入分布式微服务。先在单仓内完成依赖反转、唯一组合根、统一 Application API、插件生命周期、契约测试和发布门禁；只有第二个真实产品验证边界稳定后，才允许物理拆包。

完全解耦不等于模块之间没有依赖，而是：

1. 依赖方向固定且可自动验证；
2. 上层只依赖稳定契约，不依赖具体实现；
3. 具体实现只在 Composition Root 中被选择和实例化；
4. 新增 Backend、Provider、Tool 或产品 Profile 时不修改无关层；
5. 所有真实动作始终经过同一安全、确认、状态回读和审计链。

## 2. 现状评审

### 2.1 已具备的正确基础

- `robot_platform` 已形成硬件中立核心，并有 simulation、ZMotion、Backend registry 和 plugin manifest 基础。
- `ai_runtime` 已定义 `AgentEngine`、`AiProvider`、Tool Contract 和 Tool Manifest。
- `robot_server` 已成为唯一 HTTP/WebSocket 服务。
- `webui/src/transport` 已形成协议兼容层。
- Electron 已有 ProductManifest 与打包、启动烟测。
- 安全闸门、确认码、dry-run、状态回读、审计和兼容性矩阵已有较完整测试基础。

### 2.2 剩余关键耦合

1. `robot_server/app.py` 同时承担组合、路由、协议适配和部分业务编排，是过大的组合根。
2. `robot_platform/application` 尚未形成真正统一的用例层；当前主要是请求 DTO。
3. `RobotBackend` 契约覆盖面不足，生命周期、诊断、IO、取消、完整运动和统一结果仍不完整。
4. 部分 AI Tool 自行创建 `RobotPlatform` 或直接访问 Registry/Store，绕过统一 Application Port。
5. `robot_server/runtime.py` 和 `ai_runtime` 仍直接组装或导入 Nanobot 的 AgentLoop、消息总线、Session 与 Cron。
6. Tool Registry 目前主要完成“是否展示”的资格筛选，执行入口的二次授权、超时、取消、幂等和审计契约仍需统一。
7. Product Profile、Backend、Tool、Provider、Flow Node 尚未使用统一插件生命周期和兼容版本策略。

## 3. 架构原则与不可破坏约束

### 3.1 依赖方向

```text
WebUI / Electron / CLI
          |
Interface Layer: HTTP / WS / CLI adapters
          |
Application Layer: use cases / command handlers
          |
Domain Layer: models / policies / state machines
          |
Ports: backend / repository / audit / events / agent / tools
          ^
Adapters: ZMotion / Simulation / Nanobot / JSON / OS credentials
```

强制规则：

- Domain 不得导入文件系统、网络框架、Nanobot、ZMotion、WebUI 或 Electron。
- Application 不得判断 `backend_id == "zmotion"`，只能判断 capability。
- Interface 不得直接调用厂商 SDK、Store 或安全确认实现。
- Tool 不得直接访问 Backend、Registry、确认码 Store 或持久化实现。
- Backend adapter 不得决定用户角色、Tool 权限或产品页面行为。
- 急停 Interface 只能调用 `EmergencyStopApplicationService`，不得直接持有 Backend 或 `EmergencyStopPort`。
- 只有 Composition Root 可以知道并实例化具体实现。

### 3.2 安全不变量

- 除急停外，所有真实动作必须携带可信主体、会话、目标机器人、不可变计划、一次性执行许可和幂等标识。
- 人工按钮、AI Tool、Flow、HTTP 和 CLI 必须经过同一 Application API。
- 身份与角色只能由受信任 Interface adapter 形成 `AuthenticatedPrincipal`；不得相信请求 body、Tool 参数或模型输出中的 actor、role、session。
- 急停保持独立、最短、可达的安全通道，并采用不阻塞急停的审计策略。
- 解除急停、报警复位、继续和解除取消必须以控制器真实状态回读判定成功。
- Provider、Prompt 和模型输出不得承担真实安全职责。
- simulation 自动化测试不能替代脱敏数据回滚和真实硬件验收。

### 3.3 双层安全职责

- Application/Domain 负责：认证主体、角色授权、产品策略、计划不可变性、确认、幂等、一次性许可和审计。
- Backend 负责：设备实时状态、能力、软硬限位、生命周期、协议合法性和最后一道写入保护。
- 两层之间传递 `ExecutionPermit`，不得传递静态口令、可伪造布尔确认值或从用户请求直接取得的角色信息。
- Backend 拒绝没有有效 permit 的普通真实写入；permit 验证不能替代 Backend 对设备状态和限位的再次检查。

### 3.4 Emergency Stop Exception Policy

急停是普通执行链的明确例外：

- 不要求 dry-run、PendingPlan、工作区清空、普通确认码或“急停就绪”；
- 不进入 Agent、Flow 或普通任务队列，不等待普通审计服务成功；
- 只允许来自明确配置的本机/受控网络入口，并保留可信主体或受控设备身份；
- 通过 `EmergencyStopApplicationService -> EmergencyStopPort -> Controller` 到达当前控制器安全通道；急停绕过普通计划、permit 和任务队列，但不绕过 Application 边界；
- 审计先写入预分配、本地持久 spool，审计服务不可用时后台补写且不能阻塞急停；spool 是有界 best-effort 安全机制，容量耗尽时宁可继续急停也不能阻塞，必须持久记录 overflow 计数并触发运维告警，禁止静默丢失；
- 解除急停、报警复位、继续和解除取消不属于例外，必须经过完整授权、许可和状态回读。

## 4. 目标组件模型

### 4.1 Domain

保留在 `robot_platform` 内，逐步整理为：

```text
robot_platform/domain/
  models/
  capabilities/
  safety/
  flows/
  library/
  identity/
  errors.py
```

Domain 只包含不可变模型、值对象、业务规则、状态机和领域错误。

### 4.2 Application

```text
robot_platform/application/
  contracts.py
  robot_operations.py
  diagnostics.py
  flow_execution.py
  library_management.py
  position_management.py
  identity_management.py
  events.py
```

Application 对外暴露稳定用例，不暴露 Registry、JSON 路径、SDK 对象或厂商响应。

统一操作请求至少包含：

- `operation_id`
- `idempotency_key`
- 由 Interface adapter 注入的 `AuthenticatedPrincipal`，包含 `actor_id`、`role`、`session_id` 和认证来源
- `robot_id`
- `operation_type`、版本化参数
- `execution_mode`
- `pending_plan_id` 与确认凭据
- deadline 和 cancellation token

### 4.2.1 ExecutionPermit 与原子执行状态机

普通真实写入必须使用一次性 `ExecutionPermit`。Permit 至少绑定：

- actor、role、session；
- robot/controller；
- operation type、规范化 payload hash 和 schema version；
- Product Profile、capability、部署实例和核心版本；
- plan ID、plan version、签发时间、TTL 和 nonce。

Permit 状态机：

```text
ISSUED -> RESERVED -> EXECUTING -> CONSUMED
               |          |  \
               +-------> FAILED \
               +-------> EXPIRED +-> OUTCOME_UNKNOWN
```

- `reserve` 必须使用锁或事务原子完成；两个并发 execute 只能有一个成功保留许可。
- `RESERVED` 和确定终态必须可恢复；进程崩溃后不得据此自动重新产生硬件写入。
- 如果 SDK 已发送写入但结果尚未持久化时崩溃，operation 必须进入 `OUTCOME_UNKNOWN`，禁止自动重发。
- `OUTCOME_UNKNOWN` 必须优先使用控制器 operation ID、序列号或状态回读进行 reconcile；只有 Backend 原生支持幂等 operation ID 时才允许安全查询或受控重试。
- 无法确定结果时保持阻塞，要求人工确认设备状态并重新规划。
- 同一幂等键只有在已有确定终态时才返回原结果；不得把 unknown 当成普通失败后重试。
- cancellation 只是取消请求；只有 Backend 状态回读确认停止后才能进入 `CANCELLED` 终态。
- 普通审计 write-ahead 失败时必须 fail-closed。
- 禁止硬编码 HMAC secret、静态真实执行口令，以及 AI/Tool 自动取得内部真实执行凭据。
- Permit 是仅存在于服务端的 opaque handle，不返回给 WebUI、模型或外部客户端。Application 签发并保留 permit，Backend 只能通过受信任的 `ExecutionPermitVerifierPort`/store 验证，不能相信调用者提交的自包含字段。
- 如 permit 使用签名，密钥必须来自受控部署配置或 OS credential store，支持轮换，禁止源码 secret。

统一操作结果至少包含：

- `status`: accepted/running/succeeded/failed/cancelled
- 标准错误码和是否可重试
- 执行前后状态摘要
- Backend 回执摘要
- `audit_id`
- 结构化事件列表

### 4.3 Ports

将大接口拆成职责明确的 Protocol：

```text
RobotLifecyclePort
RobotDiagnosticsPort
RobotMotionPort
RobotSystemControlPort
RobotIoPort
EmergencyStopPort
ExecutionPermitStorePort
ExecutionPermitVerifierPort
OperationStorePort
RobotRepositoryPort
AuditPort
EventPublisherPort
AgentProviderPort
ToolRuntimePort
```

不要求每个 Backend 实现所有 Port；插件通过 versioned capability 声明支持范围。

### 4.4 Adapters

```text
robot_platform/backends/
  simulation/
  zmotion/
  future_ros2/
  future_modbus/

ai_runtime/providers/
  nanobot/
  fake/
  future_openai_compatible/
```

当前保持单仓目录，不立即提取 wheel。

### 4.5 Interface 和 Composition Root

```text
robot_server/
  bootstrap.py
  container.py
  modules/
    robot/
    flows/
    library/
    identity/
    settings/
    automations/
    media/
```

`bootstrap.py` 是唯一 Composition Root，创建一个 `RuntimeContainer`：

```python
@dataclass
class RuntimeContainer:
    robot_application: RobotApplication
    emergency_stop_application: EmergencyStopApplicationService
    backend_manager: BackendManager
    tool_manager: ToolManager
    agent_engine: AgentEngine
    repositories: Repositories
    audit_log: AuditPort
    event_bus: EventPublisherPort
```

旧 `RobotPlatform` 暂时作为兼容 facade，内部委托给 `RobotApplication`；调用迁移完成后再删除。

## 5. Backend 插件模型

### 5.1 生命周期

```text
DISCOVERED -> CONFIGURED -> CONNECTED -> READY -> ACTIVE
                    |           |          |
                    +--------> ERROR <-----+
                                 |
                              SHUTDOWN
```

- `READY`：允许状态读取、诊断和 dry-run。
- `ACTIVE`：允许经授权的真实运动写入。
- `ERROR`：禁止普通写入，保留明确允许的安全动作。
- 生命周期转换由 BackendManager 管理，不能由页面或 AI 自行改变。
- 每个转换必须定义合法来源状态、幂等性、超时、失败回滚和 supervisor owner。
- BackendManager 在加载时构造并验证明确的 port bundle；不得在运行期依赖 `getattr` 猜测可选能力。
- manifest 声明的 capability 与实际 port 不一致时，插件加载必须失败。
- 契约必须明确单位、坐标系、精度、速度/加速度约束、状态新鲜度、deadline、取消、并发、资源锁、线程安全、重连和 shutdown 超时。

### 5.2 Manifest

Backend manifest 包含：

- plugin ID、plugin version、API version；
- factory；
- 配置 JSON Schema；
- capability schema version；
- 支持的运行模式；
- health check；
- 厂商资源和可选依赖声明；
- 最低核心版本；
- 数据迁移版本。

### 5.3 发现与授权分离

```text
发现安装项 -> 读取静态 manifest -> 校验兼容性
          -> Product Profile 白名单批准 -> 自检 -> 实例化
```

当前只加载源码内显式批准的插件。未来物理拆包后可用 PyPA entry points 发现，但永远不得从用户数据目录导入任意 Python 模块。

## 6. Tool 组件模型

Tool Manifest 扩展为：

- stable ID、version、Tool API version；
- 参数与结果 JSON Schema；
- required capabilities；
- allowed roles；
- risk level；
- timeout、cancellation、idempotency；
- side-effect classification；
- audit event type；
- configuration schema。
- 核心兼容范围与弃用策略；
- 并发/独占策略和资源声明；
- 敏感配置字段标记；
- 标准结果/错误 schema 与 correlation ID。

Tool 可见性与执行授权必须分别校验：AI 看不到被禁用的 Tool；即使绕过 AI 直接调用 API，也必须在 Application 层再次验证角色、capability、计划和确认凭据。

Tool 只依赖 `RobotApplicationPort`，不依赖具体 Backend 或存储。

## 7. Agent Provider 模型

Nanobot 具体实现收口到：

```text
ai_runtime/providers/nanobot/
  provider.py
  engine.py
  session_adapter.py
  cron_adapter.py
  tool_adapter.py
```

`robot_server` 只依赖 `AgentProvider`、`AgentEngine`、`AgentEvent` 和 Session/Cron ports。新增一个可运行的 Fake Provider 和第二种真实 Provider，用于证明契约不是 Nanobot 私有接口的重命名。

Provider Contract 还必须定义 tool-call correlation ID、事件顺序、背压、取消、超时、会话 ownership、断线重连、重复事件处理和 usage/限额。Provider 故障或回合取消后，未获得 Application permit 的 Tool 不得继续执行。首轮迁移以 Fake Provider + Contract Test Kit + 最小第二 Provider PoC 为验收，不强制立即产品化第二 Provider。

AI Provider 只能影响理解、决策和事件生成，不能改变 Tool 资格、安全闸门、确认流程或审计链。

## 8. Flow Engine 组件化

Flow 节点采用版本化、类型化模型：

- ActionNode
- ConditionNode
- SequenceNode
- ParallelNode
- RetryNode
- TimeoutNode
- CompensationNode
- HumanApprovalNode

每个节点声明输入、输出、capability、timeout、取消支持、幂等性和副作用。运行时记录节点状态转换，支持停止、恢复、回放和失败补偿。保留现有 JSON Flow 兼容入口，通过显式 schema version 渐进迁移。

真实执行前必须固定不可变 Flow 快照：

- published flow ID、version 和内容 hash；
- 展开后的节点/步骤快照；
- 引用的命令、位置、Tool、Profile 和 capability 版本；
- 规范化输入和所有依赖 hash。

执行时不得按可变名称或 alias 重新解析 Flow。任一依赖发生变化必须拒绝旧计划并要求重新 plan。`CompensationNode` 默认不得自动反向运动；只有显式声明、经过安全评审的补偿动作才可启用。

### 8.1 审计与追踪

每个 operation 使用统一 correlation ID，审计至少记录：write-ahead intent、可信主体、目标设备、不可变计划/permit hash、Backend 结果、状态回读和最终状态。普通动作审计不可用时 fail-closed；急停使用不阻塞的本地补写策略。审计数据必须定义脱敏、保留期、篡改检测和失败恢复。

## 9. WebUI 与 Electron

WebUI 按 feature 组织，页面只使用 `transport`：

```text
webui/src/
  app/
  features/robot/
  features/flows/
  features/library/
  features/identity/
  features/settings/
  transport/
  shared/
```

Electron 只负责产品生命周期、端口、进程监督、资源和 ProductManifest。它不包含机器人业务、安全规则或 Provider 配置逻辑。

HTTP、WS、capability、manifest 和事件都必须有协议版本与向后兼容 fixture。

## 10. 外部项目经验的采用边界

- ROSA：采用 Tool/Prompt/Agent 的组合式注入；不采用 Prompt 作为安全边界。
- ros2_control：采用硬件接口、管理器、生命周期、插件加载测试和 capability 思路；不把 MotionFlow 强制改造成 ROS 进程架构。
- ROS 2 Managed Nodes：采用明确生命周期和外部 supervisor；保留 MotionFlow 单进程产品模型。
- BehaviorTree.CPP：采用异步节点、类型化数据流、运行时组合、状态记录与回放；不直接引入 C++ 依赖。
- Pluggy/PyPA entry points：未来用于物理插件发现；当前仍使用显式白名单注册。

## 11. 分阶段实施计划

### 阶段 -1：安全债务封堵（任何结构迁移之前）

- 移除硬编码 HMAC secret、静态真实执行口令和 AI 自动获取真实执行凭据的路径。
- 新增可信 `AuthenticatedPrincipal`，禁止从请求 body 信任 actor/role/session。
- 实现一次性、强作用域、原子消费的 `ExecutionPermit` 与幂等 operation store。
- PendingPlan 改为不可变快照，并增加原子 reserve/consume 与崩溃恢复语义。
- 为急停建立独立策略和端口；解除/复位仍走普通安全链。
- 修复 Flow plan/execute TOCTOU，执行时禁止重新解析 alias。

完成条件：伪造身份、重放、并发双执行、跨会话/机器人/Profile/重启复用、Flow 变更后执行等负向测试全部通过；SDK mock 证明并发路径最多一次写入，并通过“SDK 已写入但结果未落库”的故障注入验证 `OUTCOME_UNKNOWN`、reconcile 和禁止自动重发。

### 阶段 0：基线与架构门禁

- 固化当前产品兼容矩阵和安全不变量。
- 扩充 architecture tests，验证禁止的 import 方向。
- 测试临时目录统一放在仓库和 worktree 外。
- 为 Backend、Tool、Agent、HTTP/WS schema 建立 versioned fixtures。

完成条件：架构越界和协议破坏能在 CI 中稳定失败。

### 阶段 1：唯一组合根与 RuntimeContainer

- 新建 `robot_server/container.py` 和 `bootstrap.py`。
- 将依赖构造从 `app.py`、Tool 和 runtime 移到 bootstrap。
- `create_robot_server_app` 接收已构造容器。
- 保留旧构造路径作为兼容 shim。

完成条件：同一进程只构造一个共享 RobotApplication/Backend/Agent runtime；测试可完全注入 fake。

### 阶段 2：统一 Robot Application API

- 定义统一请求、结果、错误和事件。
- 按 `status -> diagnostics -> dry-run -> emergency stop -> 单一运动 -> IO -> position/library -> flow` 逐个用例族迁移。
- 每次切片只允许一个硬件写入者；只读请求可 shadow compare，写入请求只能 dry-run 对比，禁止新旧路径双写。
- 旧 `RobotPlatform` 改为委托 facade。

完成条件：HTTP、Tool、CLI、Flow 均不直接调用 Backend 或 Store。

### 阶段 3：Backend 生命周期与契约测试套件

- 拆分 Backend ports，扩展生命周期与 capability。
- 建立可复用于所有 Backend 的 Contract Test Kit。
- 验证无 ZMotion 安装时 simulation、Server、WebUI、AI 仍可启动。
- 增加至少一个最小 Dummy/Mock Backend 证明扩展点。

### 阶段 4：Tool Runtime 收口

- 扩展 Tool Manifest。
- 将 Robot Tool 全部改为依赖 Application Port。
- 统一执行授权、取消、超时、幂等和审计。
- 保留 Legacy adapter 直到所有调用迁移完成。

### 阶段 5：Agent Provider 适配器化

- 将 Nanobot 具体依赖迁入 provider adapter。
- Server 不再导入 AgentLoop、MessageBus 等具体类型。
- 增加 Fake Provider 和第二种实际 Provider 验证。

### 阶段 6：Server 路由模块化

- 拆分 `robot_server/app.py` 为功能路由模块。
- 保持所有 HTTP/WS path、header、错误和事件兼容。

### 阶段 7：Flow Runtime 组件化

- 引入类型化 Flow Node 和状态事件。
- 完成不可变快照、取消、恢复、回放和受控补偿。

### 阶段 8：WebUI feature 化

- 前端按 feature 收口，保持 transport v1 兼容。
- Electron 继续只依赖 ProductManifest。

### 阶段 9：外部验收与物理拆包判定

- 完成脱敏 runtime 迁移和回滚演练。
- 完成受控工位 ZMotion 只读、dry-run、最小动作、急停和复位签核。
- 用第二个真实产品验证 Backend、Tool 或 transport API。
- 同时满足 ADR 门槛后，才提取独立 wheel/npm 包。

## 12. 全局验收标准

1. 删除或不安装 ZMotion 后，simulation、Server、WebUI 和 AI 对话仍可启动。
2. 新增 Backend 只需要插件、Profile 和契约测试，不修改 Server 路由、Tool 或页面。
3. 替换 Provider 不改变 Tool 权限、确认码、安全预检和审计。
4. Tool 被禁用后，AI、HTTP、Flow 和兼容入口均无法绕过。
5. Domain/Application import 图中不存在 UI、Server、Nanobot 或厂商 SDK。
6. 所有 Backend 通过同一 Contract Test Kit。
7. 所有动作都有 operation ID、操作者、目标、参数、执行前后状态和 audit ID。
8. 所有公开 DTO、事件、capability 和 manifest 都有版本及兼容 fixture。
9. simulation 通过不能替代数据回滚与真机签核。
10. PyInstaller、WebUI build、Electron package smoke 和当前产品旅程保持通过。
11. HTTP、AI、Flow、CLI 和 Legacy 入口运行同一套安全负向测试。
12. 并发 execute 最多产生一次 SDK 写入；崩溃后的确定终态不重写，未知终态进入 reconcile 并禁止自动重发。
13. Flow 在 plan 后修改、删除、重发或 alias 改指向时拒绝执行。
14. 普通动作在审计不可用时 fail-closed；急停仍可执行。spool 容量内保证重启后 at-least-once 补写；容量耗尽时持久化 overflow 数量并告警，明确降级为 best-effort，绝不以审计背压延迟急停。
15. 自动化证明所有实现组合只发生在 `bootstrap.py`，业务模块不能构造 Backend、Store、Provider 或 `RobotPlatform`。

## 12.1 每个迁移切片的强制模板

每个切片在实施计划中必须写明：

- 旧入口、新入口和流量开关；
- 唯一数据 owner 与唯一硬件写入者；
- shadow/dry-run parity 方式；
- 新旧结果 fixture；
- schema migration 与兼容窗口；
- rollback 命令、触发阈值和观测指标；
- 切换前门禁、切换后门禁和删除旧路径的条件。

## 13. 物理拆包门槛

只有同时满足以下条件才物理拆包：

- 至少两个真实产品或独立使用方；
- 稳定、版本化的公开 API 与弃用策略；
- 独立安装和 Contract Test；
- 可选厂商 SDK 在 wheel、PyInstaller 和无 SDK 环境均通过；
- 脱敏 runtime 迁移、回滚和真机安全签核完成；
- 至少一次跨项目升级演练成功。

## 14. 决策记录

- 采用模块化单体，暂不采用微服务。
- 采用显式依赖注入，暂不引入重量级 DI 框架。
- 当前插件显式注册，未来再引入 entry points。
- 保留兼容 adapter，按调用点渐进迁移。
- 安全链属于 Application/Domain，不属于 AI、UI 或厂商插件。
- 本文档是后续实施计划和架构评审的主基线；已有文档继续作为兼容、安全和发布证据。
- 2026-07-29：首轮评审发现静态凭据、身份信任、可重放计划、Flow TOCTOU、急停语义与回滚定义问题；第二轮补充真实硬件 `OUTCOME_UNKNOWN`；第三轮复审 `APPROVE`。
