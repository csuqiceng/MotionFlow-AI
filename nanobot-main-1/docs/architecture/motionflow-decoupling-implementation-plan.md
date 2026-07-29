# MotionFlow 解耦组件化实施计划

状态：执行中  
架构基线：`motionflow-decoupling-componentization-master-plan.md`  
执行原则：安全债务优先、一次迁移一个用例族、唯一硬件写入者、所有切片可回滚。

## 1. 总体门禁

每个切片开始前和完成后至少执行：

```powershell
desktop\.build-venv\Scripts\python.exe -m pytest tests\architecture tests\robot_ai tests\robot_server -q
cd webui
npm test -- --run
npm run build
cd ..\desktop
npm run build
node electron\tests\before-pack.test.js
node electron\tests\packaged-robot-server-launch.test.js
```

测试 TEMP/TMP 必须指向仓库外目录。真实硬件写入测试不进入普通自动化；使用 SDK fake 断言写入次数，现场测试按发布清单执行。

## 2. 阶段 -1：安全债务封堵

### 切片 -1.1：可信主体和执行许可基础（已完成）

目标：建立不依赖 HTTP body、AI 参数或静态口令的安全基础类型和线程安全状态机，暂不切换生产流量。

新增：

- `robot_platform/application/principal.py`
- `robot_platform/execution/permit.py`
- `tests/robot_ai/test_execution_permit.py`

实现：

- `AuthenticatedPrincipal`
- `ExecutionScope`
- 服务端 opaque `ExecutionPermit`
- `ExecutionPermitStore.issue/reserve/mark_executing/complete/fail/mark_outcome_unknown`
- 原子状态转换、TTL、scope hash、部署实例绑定和幂等结果读取

门禁：

- 两个并发 reserve 只有一个成功；
- scope 任一字段变化均拒绝；
- consumed/failed/unknown 不得重新 reserve；
- executing 崩溃恢复为 `OUTCOME_UNKNOWN`；
- unknown 禁止自动重发；
- permit handle 不包含主体或 payload 明文。

回滚：删除新增模块和测试即可；尚未接入生产入口，无运行时数据迁移。

完成记录（2026-07-29）：

- 新增 `AuthenticatedPrincipal`、`ExecutionScope`、opaque `ExecutionPermit` 和线程安全 `ExecutionPermitStore`。
- 授权 `scope_hash` 与稳定物理 `execution_identity_hash` 分离；更换 session、principal、部署实例或版本不能解锁 unresolved 物理计划。
- 完成 ISSUED/RESERVED/EXECUTING/CONSUMED/FAILED/EXPIRED/OUTCOME_UNKNOWN 状态转换。
- 明确未下发失败、控制器确定失败和不确定结果；unknown 只能凭控制器证据 reconcile，不能自动重发。
- 结果读写采用深复制，防止调用者修改幂等结果。
- 新增并发、TTL、跨身份/重启、reconcile、深复制和新计划版本测试。
- 验证：`39 passed`；`py_compile` 和 `git diff --check` 通过。
- 独立代码复审：最终 `APPROVE`。

### 切片 -1.2：HTTP 身份边界（已完成）

目标：Robot HTTP handler 从认证上下文构造 `AuthenticatedPrincipal`，停止信任 body 中的身份和 session。

修改：

- `robot_server/request_context.py`
- `robot_server/identity_api.py`
- `robot_server/robot_api.py`
- `robot_server/app.py`
- 对应 Server 安全负向测试

流量开关：`MOTIONFLOW_TRUSTED_PRINCIPAL_V1`，默认测试环境开启；兼容窗口内旧 body 字段仅忽略并记录弃用，不参与授权。

回滚：关闭开关恢复旧解析；任何真实写入仍保持现有确认链，不允许双写。

完成记录（2026-07-29）：

- UserSessionStore 为每次登录签发内部 session ID；它与 token 分离，不接受请求 body 输入。
- Robot mutation routes 默认要求有效 `X-Robot-User-Token`，并绑定可信 `AuthenticatedPrincipal`/ContextVar。
- plan/confirm/execute/flow/legacy/emergency 路由全部忽略 body 中的 session、actor 和 role。
- WebUI transport 同时发送 gateway Bearer 与用户 token；SidePanel 和 ControlPanel 已接入真实 user token。
- 兼容开关保留在 `RobotServerConfig.trusted_principal_v1`，默认启用，关闭时使用固定兼容主体而非 body 身份。
- 验证：相关 Python `63 passed`；WebUI 全量 `550 passed, 33 skipped`；生产 build 通过；独立代码复审 `APPROVE`。
- 已知既有基线问题：`test_product_profile_is_engineer_only...` 期待 simulation，但当前默认 Profile 返回 `zmotion_readonly`；与本切片无关，未用于证明本切片通过。

### 切片 -1.3：一次性 PendingPlan/ExecutionPermit 接入

状态：**已完成并通过四轮独立安全复审，最终 `APPROVE`。**

目标：将 plan/confirm/execute 接入原子 permit，替换可重放 `verify()`。

修改：

- `robot_platform/execution/pending_plan.py`
- `robot_platform/execution/confirm_code.py`
- `robot_server/robot_api.py`
- `robot_platform/backends/zmotion_adapter.py`
- execution gate/wiring/server tests

规则：

- permit 只在服务端保存；
- 普通 execute 原子 reserve；
- SDK 写入前进入 EXECUTING；
- 确定结果进入终态；不确定结果进入 OUTCOME_UNKNOWN；
- 同一幂等键只返回已有确定结果；
- 删除源码 secret 和静态 `EXECUTE_ZMOTION_REAL` 路径。

切换：先 simulation 和 SDK fake；真实生产路径需经过完整回归与人工批准后切换。旧新路径禁止同时写硬件。

完成记录（2026-07-29）：

- 删除硬编码 HMAC、静态 `EXECUTE_ZMOTION_REAL`、AI 自动凭证和旧真机矩阵脚本；CLI/Bridge/Library 旧真实执行入口稳定返回 `staged_execution_required`。
- Backend 使用实际 `request.command + request.parameters` 重建 scope，并通过 `ExecutionPermitVerifierPort.claim_dispatch` 原子、单次 claim；Protocol 不再暴露可重复的只读 verify。
- permit 使用 fsync + atomic replace 持久化；重启时 `RESERVED/EXECUTING -> OUTCOME_UNKNOWN`；同 controller 未 reconcile 时禁止签发新 permit。
- runtime permit store 持有生命周期跨进程独占锁，第二个 Server 不能共享同一运行数据目录；独立进程测试覆盖。
- `RobotPlatform` 冻结 Backend config，controller identity 绑定 mode + host fingerprint；非确定平台失败进入 `OUTCOME_UNKNOWN`。
- 真实 Flow 在切片 -1.5 完成前明确 fail-closed，不允许顶层 permit 泛化为任意子步骤写权限。
- 最终门禁：Python 全量 `3642 passed, 23 skipped, 1 deselected`；WebUI 全量 `550 passed, 33 skipped`；独立架构/安全复审最终 `APPROVE`。

### 切片 -1.4：急停独立 Application Service

状态：**已完成并通过四轮独立安全复审，最终 `APPROVE`。**

新增 `EmergencyStopApplicationService` 和 `EmergencyStopPort`。HTTP/CLI 只调用 Service；Service 绕过普通 plan/permit/队列，但保留入口身份边界、独立限流和不阻塞审计补写。

验收：普通审计故障时急停仍到达 SDK fake；解除急停、复位、继续不能走该例外。

完成记录（2026-07-29）：

- 新增 `EmergencyStopApplicationService`、`EmergencyStopPort`、one-use `EmergencyStopAuthority` 与产品 Adapter。
- 急停与普通 permit/队列分离，但仍使用受信任 principal；解除急停、pause/resume/release 等不接受该例外。
- Composition Root 将同一个冻结 `RobotBackendConfig` 注入普通平台与急停 Adapter，禁止 Adapter 重新读取环境选错设备。
- 本地 JSONL outbox 使用 correlation/operation ID；请求线程仅复制到预分配 mmap spool 并非阻塞唤醒 worker，后台执行 append/fsync，任何慢盘或阻塞 I/O 都不能延迟物理急停。
- spool 容量内提供重启后 at-least-once 补写；容量耗尽时持久化 `emergency_stop_audit_overflow` 数量并明确进入 best-effort 告警态，禁止为了审计完整性阻塞急停。
- 测试覆盖环境/Profile 冲突、审计异常、审计 I/O 阻塞、并发急停、worker 延迟退出 lease 释放、容量边界 overflow 与重启补写。

### 切片 -1.5：不可变 Flow 快照

状态：**已完成并通过独立架构/安全复审，最终 `APPROVE`。**

Pending flow 保存发布 ID、版本、内容 hash、展开节点和依赖版本。执行阶段禁止按 name/alias 重新解析。覆盖修改、删除、重发、alias 改向和跨 Profile 负向测试。

完成记录（2026-07-29）：

- 新增不可变 `FlowExecutionSnapshot`/`FlowSnapshotStep`；规划时将每一步展开为最终 `command + parameters` 规范 JSON，并冻结 flow ID、发布版本、内容 SHA-256、Profile/Capability/Core 依赖及解析 alias。
- `PendingPlanStore` 对 create/get 返回深拷贝，外部不能修改存储中的快照；snapshot 反序列化强制校验内容 hash、连续步骤和支持的操作类型。
- confirm 为整个 Flow 签发 orchestration parent permit，并为每个快照步骤签发独立 child permit；opaque handles 均不返回浏览器。
- 执行仅调用 `run_flow_entry(snapshot)`，不再读取 Registry/name/alias；每一步先 reserve/EXECUTING，再由 Backend 对实际 command/parameters 原子 claim 唯一 dispatch ID。
- 要求真实写 permit 在至少一次 Backend claim 后才能进入 `CONSUMED`；子结果未提交时 parent 进入 `OUTCOME_UNKNOWN`。
- 测试覆盖 authoring 数据修改/删除、插入/重排、alias 改向、alias/schema/hash 篡改、依赖版本变化、重复 execute、重复 child dispatch 和快照对象外部篡改；扩大回归 `104 passed, 1 known deselected`，独立复测 `6 passed`。
- 切片最终 Python 全量门禁：`3650 passed, 23 skipped, 1 deselected`（另有 2 个既有 Windows asyncio transport 清理 warning）。

## 3. 阶段 0：架构和协议门禁

状态：**已完成并通过四轮独立架构复审，最终 `APPROVE`。**

1. 扩展 `tests/architecture/test_dependency_rules.py`。
2. 增加 Application、Tool、Provider、Composition Root 禁止依赖规则。
3. WebUI 增加 feature/transport ESLint boundary。
4. 为 capability、Backend manifest、Tool manifest、Agent event、HTTP/WS 建立 versioned fixtures。
5. 将所有安全负向测试参数化覆盖 HTTP、AI、Flow、CLI 和 Legacy 入口。

完成记录（2026-07-29）：

- Python 依赖门禁已覆盖 Application、AI Provider、Tool Adapter 和具体运行时构造位置；共享 scanner 跟踪普通/alias/literal dynamic import，对受控层无法静态求值的动态 import fail-closed；构造点 detector 同时覆盖 qualified call、赋值 alias、subclass/getattr 所依赖的 concrete import site。现存 concrete import/构造点使用显式 ratchet allowlist 固定，只允许后续迁移时减少。
- Backend、Tool、Agent event 均增加 `protocol_version: 1` golden fixture；health 使用无版本字段的精确响应 fixture，既有 capability 与 WebSocket fixture 一并纳入兼容门禁。
- WebUI ESLint boundary 禁止 transport 通过相对路径或 `@/*` alias 反向依赖 feature/provider，并禁止机器人 feature 绕过专用 facade 直接导入原始 HTTP/WebSocket transport；受控 lint fixture 同时证明 alias/relative 越界会失败。
- 跨入口真实执行安全矩阵使用 v1 inventory 与 case ID 等值门禁，覆盖真实 CLI、公开 Backend runner（SDK fake 零触达）、Legacy Bridge、Flow executor、RobotArmTool、RobotFlowTool、staged HTTP、旧 Flow HTTP 和 library command/flow HTTP，全部 fail-closed。
- 完整 `tests/architecture`：`53 passed`；WebUI boundary fixture：`3 passed`。
- WebUI：lint `0 errors`；全量 `553 passed, 33 skipped`；production build 通过（仅保留既有 circular chunk 与 bundle size warning）。
- 独立架构复审先后发现并关闭 Python import alias/dynamic import、WebUI `@/*` alias、公开入口假覆盖及旧 AST 分支未复用 scanner 等 P1；最终结论 `APPROVE`，无 P0/P1。

## 4. 阶段 1：唯一组合根

状态：**首个完整对象图切片已完成并通过独立架构复审，最终 `APPROVE`。**

1. 新增 `robot_server/container.py`，定义 `RuntimeContainer`。
2. 新增 `robot_server/bootstrap.py`，成为唯一具体实现装配位置。
3. `create_robot_server_app` 接受 container；旧 `platform/config` 参数保留兼容 shim。
4. 将 service、Backend、Agent、Store 构造逐步迁出 `app.py`。
5. 架构测试禁止业务模块创建 `RobotPlatform`、Backend、Store、Provider。

首个切片只搬运现有实例，不改变路由和业务行为；失败时恢复旧构造分支。

完成记录（2026-07-29）：

- 新增 `RuntimeContainer` 与唯一 `robot_server/bootstrap.py`；`app.py` 只发布已构造依赖和注册路由，旧 `platform/config` 参数仅作为一次委托的兼容 shim。
- 产品 CLI 通过 bootstrap 构造 Profile-selected Backend、共享 `RobotPlatform`、Agent runtime 与容器；RobotArm/RobotFlow Tool 在产品路径复用同一 platform，不再暗建第二 Backend。
- PendingPlan、SessionGate、ExecutionPermit 均为 per-container 实例；删除模块导入期 default store，双容器 plan/session/permit 状态互不串扰。
- ProductProfile 使用受 parity test 约束的 capability catalog，请求期不再创建临时 Backend。
- 明确资源所有权：外部注入 platform 不由容器关闭；内部或产品自建 platform/backend 由容器拥有。permit 加载失败、后续 service/Agent 构造失败、Agent start/stop 失败均执行逆序、幂等、best-effort cleanup。
- 定向整改门禁：`68 passed`；扩大 Server/RobotAI/architecture 回归：`661 passed, 1 deselected`；WebUI production build 与 desktop before-pack/packaged-launch 契约测试通过。
- 独立复审整改后的最终 Python 全量：`3693 passed, 23 skipped, 1 deselected`（仅 2 个既有 Windows asyncio transport 清理 warning）。
- 独立复审经过两轮故障注入整改，最终 `APPROVE`，无 P0/P1。

## 5. 阶段 2：统一 Application API

状态：**阶段 2 已完成；`status`、`diagnostics`、`dry-run`、`emergency stop`、`single motion`、`IO`、`position/library`、`flow` 用例族均已迁移。按最新执行规则，中间切片不再单独评审，整个目标完成后统一总评审。**

迁移顺序固定为：

```text
status -> diagnostics -> dry-run -> emergency stop
       -> single motion -> IO -> position/library -> flow
```

每个用例族均执行：

1. 定义 request/result/error/event；
2. 新 Application handler；
3. 只读 shadow compare 或写入 dry-run parity；
4. 切换唯一入口；
5. 观察并满足退出门禁；
6. 删除旧路径。

`status` 完成记录（2026-07-29）：

- 新增 vendor-neutral `RobotStatusQuery/Response/Error`、Reader/Application ports 与 `RobotStatusApplicationService`；成功/失败 DTO 强制 exactly-one 不变量。
- capability v1 兼容归一化从 HTTP adapter 下沉到 Application；保留 legacy `controller_capabilities` 与原 HTTP 成功/503 形状。
- bootstrap 创建单一 status service，并将同一实例注入 Server container 与 Agent ToolLoader；HTTP/RobotArm status 均禁止直接调用 Platform。
- reader 异常、畸形结果、normalize/deepcopy 失败均脱敏；非合规未来 Port 的空 error 由 HTTP/Tool 二次 fail-closed。
- 定向/扩大回归：`127 passed, 1 deselected`；独立复审整改 DTO Optional P1 后最终 `APPROVE`，无 P0/P1。

`diagnostics` 完成记录（2026-07-29）：

- 新增 engineer-scoped Diagnostics Query/Response/Error、Application port/service；角色检查严格早于任何 Status 读取。
- service 只依赖统一 Status Application port；HTTP 仅解析可信 principal、调用 service 并映射既有 403/503/成功响应。
- query、port 校验、整棵 status payload deepcopy、规范化和 projection 位于统一脱敏边界；position/io/alarms/task/command_echo 不共享嵌套可变引用。
- HTTP 测试禁止直接 Platform/Status 旁路；权限、畸形 Port、恶意 `__str__` 和嵌套反向 mutation 均覆盖。
- 定向回归：`116 passed, 1 deselected`；独立复审两轮整改后最终 `APPROVE`，无 P0/P1。

`dry-run` 完成记录（2026-07-29）：

- 新增 vendor-neutral `RobotDryRunResponse/Error`、Platform/PendingPlan/SessionGate/Application ports 与单一 `RobotDryRunApplicationService`；成功、失败与 staged 状态执行严格不变量检查。
- command preview/stage、Flow entry preview/stage 与 named Flow preview 统一走 Application；HTTP plan/plan_flow/legacy run_flow 及 RobotArm/RobotFlow Tool 不再直接调用 Platform 规划入口。
- Product bootstrap 构造并向 Server、Agent 注入同一 dry-run service；所有预演强制 `execute_real=False`，confirm/execute/permit 写入链保持独立且未绕过。
- command parameters 在入口只冻结一次，Platform preview 与 PendingPlan 均从同一快照派生，消除并发修改导致的 TOCTOU；Flow 在解析后冻结快照、别名与依赖。
- stage 部分失败会删除孤儿 PendingPlan，并仅在失败 plan 仍为 current 时原位恢复旧 `pending_plan_id/confirmed`；不会覆盖并发新 plan、复活已收回权限或破坏 session 对象身份。
- Platform、Flow resolve/snapshot 与回滚异常统一脱敏；定向架构回归 `93 passed`，扩大 Server/RobotAI/architecture 回归 `688 passed, 1 deselected`。
- 独立复审先后关闭参数快照 TOCTOU、Flow 异常泄露与 rollback 并发权限风险，最终 `APPROVE`，无 P0/P1。

`emergency stop` 完成记录（2026-07-29）：

- 新增 immutable `RobotEmergencyStopCommand/Response/Error` 与 Application port；仅接受可信 `AuthenticatedPrincipal`，畸形 Port、SDK 异常和 vendor host/path 统一映射为稳定脱敏 503。
- HTTP 认证后直接调用独立 AppKey/service，完全不读取 request body；Container、HTTP 与兼容 Operation shim 共享同一实例，worker/outbox 生命周期由 Container 托管。
- ZMotion dedicated Adapter 不再进入普通 operator/status/L1/permit/Flow 链；连接成功后在按 controller host 共享的事务锁内 issue/claim one-use authority，并原子提交最小 Func104 六写。
- 普通参数/echo/trigger 提交强制实现 `write_transaction`；缺失事务能力零写 fail-closed。normal permit、Platform、Flow authoring/snapshot、AI Tool 和 vendor CLI 均不能执行 `emergency_stop`，release/reset/resume 仍走普通授权链。
- `release_emergency_stop`、`release_cancel`、`resume`、`alarm_reset` 仅在控制器真实目标状态位回读成立后成功，不再把 pending/error/残留状态误报为完成。
- 审计采用预分配 mmap spool：请求线程仅内存复制与非阻塞 wake，后台 JSONL fsync；容量内重启后 at-least-once 补写，timeout 后迟到终态沿用 operation ID。容量耗尽按文档降级为 best-effort，但 overflow 数量持久化并恢复告警，禁止静默丢失或审计反压急停。
- worker 在自身 `finally` 释放 mmap/file，同路径进程 lease 防止双 writer；阻塞 append、延迟退出、重开恢复、capacity+1、并发双 SDK client 原子性均有故障注入测试。
- 修改完成后的扩大 Server/RobotAI/architecture 回归：`711 passed, 1 deselected`；本切片期间 Python 全量门禁：`3740 passed, 23 skipped, 1 deselected`（仅 2 个既有 Windows asyncio transport 清理 warning）。
- 独立评审多轮关闭零 body、最小写路径、normal 旁路、事务可选退化、真实状态判定、审计恢复/overflow/lease 等问题，最终 `APPROVE`，无 P0/P1。

`single motion` 完成记录（2026-07-29）：

- 新增 `RobotMotionExecutionCommand/Response/Error`、PendingPlan/SessionGate/Permit/Platform/Application ports 与统一 `RobotMotionApplicationService`，覆盖 `linear_move` 和 `linear_path`。
- Application 从不可变 PendingPlan 读取 command/parameters，验证 operator/engineer trusted principal、session confirmation 与 server receipt；execute body 中的 command/parameters 永不参与真实调度。
- ExecutionScope 绑定 actor/session/auth source、robot/controller、Profile/Capability/deployment/core、plan ID/version 与 payload hash；permit 依次执行 reserve、EXECUTING、Backend 原子 claim、CONSUMED 或 OUTCOME_UNKNOWN。
- replay 使用 `definite_result_for_exact_execution` 在 PermitStore 锁内精确匹配 handle、idempotency key、scope hash 和 physical execution identity；actor、controller、所有版本或 permit handle 变化均拒绝回放。
- 成功和失败结果均从零构造公开 DTO；首次 HTTP、permit 持久结果与 replay 共用同一白名单净化路径，Backend host、SDK path、异常、未知顶层与嵌套 secret 均不越过 Application 边界。
- 并发 execute 最多一次 Platform dispatch；无 Backend dispatch claim 的伪成功不能 commit；Platform 异常/畸形/非确定失败、commit 失败和 `mark_executing` 持久化异常均保守收敛且脱敏。
- bootstrap 构造 per-container motion service，Operation compatibility shim 对 motion 只调用该 service，测试证明不直接调用 Platform；该切片完成时其余尚未迁移用例保持原路径且不误路由。
- 修改完成后的扩大 Server/RobotAI/architecture 回归：`741 passed, 1 deselected`；独立评审两轮关闭 exact-scope replay 与成功结果泄露问题，最终 `APPROVE`，无 P0/P1。

`IO` 完成记录（2026-07-29）：

- 新增 `RobotIOExecutionCommand/Response/Error`、IO 专用 Ports 与 `RobotIOApplicationService`；抽取非公开 `ConfirmedPlanExecutionEngine`，由 motion/IO 各自的命令白名单、参数验证和结果净化策略复用同一 confirmation/permit/dispatch/replay 状态机，禁止形成可执行任意命令的通用入口。
- IO 仅执行不可变 PendingPlan；trusted principal、session confirmation、server receipt、exact scope、reserve/EXECUTING、Backend 原子 claim、CONSUMED/OUTCOME_UNKNOWN、并发单次调度及确定结果回放与单运动保持同一安全语义。
- Product Profile 新增工程师维护的 `allowed_io_output_channels`，默认空白名单并规范排序，拒绝 bool、负数、重复项和超出协议边界的通道；策略在进程启动时冻结进 Platform 与 BackendConfig。
- HTTP/AI dry-run 只接受 `io_number/enabled`，调用方不能提交 allowlist；Application 将服务端可信列表写入不可变计划，permit scope/payload 因而绑定完整策略快照。策略变化、计划列表不一致或通道不在可信集合时均在 reserve 前 fail-closed。
- `RobotPlatform` 在 dry-run、confirmed execute 与 Flow 路径覆盖请求列表，只使用自身冻结策略；ZMotion Backend 在 permit claim 和任何 SDK 写入前再次要求 request 策略与 BackendConfig 完全一致，caller 使用 `{io_number: 999, allowed: [999]}` 无法自授权。
- 成功/失败、持久结果和 replay 共用从零构造的 IO 白名单 DTO；通道/value 回显只取已验证的不可变计划，Backend 伪造 echo、host、SDK path、异常和未知嵌套字段均不能越过 Application 边界。
- Composition Root 为每个容器构造唯一共享 confirmed engine 和独立 motion/IO facade；HTTP IO execute 只路由到注入的 IO Application，execute body 中的 IO 字段被忽略，测试证明不直达 Platform。
- P1 整改后扩大 Server/RobotAI/architecture 回归：`778 passed, 1 deselected`；完整 Python 门禁：`3810 passed, 23 skipped, 1 deselected`（仅 2 个既有 Windows asyncio transport 清理 warning）；Ruff、compileall 与 `git diff --check` 通过。
- 独立复审先发现 caller-supplied allowlist 自授权 P1；完成 Product Profile 单一可信源、计划/scope 绑定及 Backend pre-claim 二次校验后复审最终 `APPROVE`，无 P0/P1。遗留 P2 仅为 CLI/Bridge 仍展示已无授权意义的旧 allowlist 参数，真实写保持 fail-closed；在兼容 facade 清理时删除。

`position/library` 完成记录（2026-07-29）：

- 新增 vendor-neutral Position Query、Library Catalog、两阶段 Library Mutation、Command Management、Library Transfer 与 Position Maintenance Application/Port/DTO；AI Tool 与 HTTP facade 只依赖注入的 Application，不再直接读取 Registry、JSON 或模块全局确认状态。
- 确认令牌按完整 `AuthenticatedPrincipal` 绑定、线程安全且一次性 claim；角色校验严格早于 Port 调用，operator 不能更新/删除，错误和成功 DTO 均脱敏并从零白名单构造。
- `/ws/agent` 在升级前校验服务器用户会话，运行时 actor 只从可信 principal 派生，客户端 envelope 的 `actor_id` 完全忽略；伪造 `engineer:*` 不能提升权限。
- 新增数据目录级共享 `library_transaction` 协调器，覆盖 Position/Command/Flow Mutation、命令管理、库导入、位置清理和所有文件型库读写；同目录嵌套使用 `RLock`，跨 Adapter 故障注入证明失败回滚不会覆盖随后成功的 Registry 提交。
- 多文件位置创建/更新对 `positions.json` 与 `commands.json` 使用 preimage 回滚；共享追加式 `audit.jsonl` 永不恢复旧快照，所有审计追加按绝对路径串行，并在 Registry 回滚后追加 `library_transaction_rollback` 补偿事件。并发成功的登录审计不会丢失。
- Product bootstrap 为每个容器注入同一 Position/Library Application 实例；架构门禁禁止 AI/HTTP 位置与库接口导入具体 Store，并约束所有生产文件写入口接入共享事务协调器。
- 定向回归 `34 passed`；扩大 Server/RobotAI/architecture 回归 `800 passed, 1 deselected`；完整 Python 门禁 `3832 passed, 23 skipped, 1 deselected`（仅 2 个既有 Windows asyncio transport 清理 warning）；Ruff、compileall 与 `git diff --check` 通过。
- 依照最新规则，本切片不做独立完成评审；待整个 MotionFlow 解耦组件化目标完成后统一总评审。

`flow` 完成记录（2026-07-29）：

- 新增 Flow Query/Preview、Flow Management、Tracked Library Execution 与 immutable staged Flow Execution Application/Port/DTO；新增 `FileRobotFlowAdapter` 与 `FileFlowManagementAdapter`，具体 Registry/Alias/文件实现只由 bootstrap 选择。
- `RobotFlowTool` 只依赖注入的 Flow Application；不再构造 Platform、FlowRegistry 或 FlowAlias，standalone 缺少注入时 fail-closed。产品 Agent、HTTP、工程师管理与库执行复用组合根中的同一 Flow Application。
- `robot_server` 的 Flow management、library execution 与 staged Flow facade 均改为薄身份/协议适配器；生产 Server/AI 中已无 `FlowRegistry`、`VersionedFlowRegistry`、`FlowAlias`、`run_flow_entry` 或 `resolve_flow` 的直接调用。
- Flow plan 通过 Catalog Port 解析一次并重建纯领域 `FlowEntry`，DryRun Application 从该固定 entry 创建不可变 snapshot；执行阶段不再解析 name/alias，authoring 文件被替换后仍只消费原 snapshot。
- Flow parent/child permit 在 Application 内绑定 principal/session、robot/controller、Profile/Capability/Core、snapshot hash、step payload 与 dispatch ID；exact replay 同时校验 handle、idempotency key、scope hash 和 physical execution identity，换 actor 即拒绝且不重复 Platform dispatch。
- Flow 与 tracked library execution 的成功/失败/持久 replay DTO 均脱敏；嵌套 host/path/token/permit/SDK/config 字段不会越过 Application 边界，后台 worker 异常不再把本机异常文本写入持久执行历史。
- Flow 文件写入继续受数据目录级共享 transaction coordinator 保护；架构门禁禁止 Flow Tool/HTTP facade 导入具体 Flow Store/Platform，并固定所有生产文件写 Adapter 的协调器依赖。
- Flow 全域回归 `88 passed`；扩大 Server/RobotAI/architecture 回归 `815 passed, 1 deselected`；完整 Python 门禁 `3847 passed, 23 skipped, 1 deselected`（仅 2 个既有 Windows asyncio transport 清理 warning）；Ruff、compileall 与 `git diff --check` 通过。
- 依照最新规则，本切片不做独立完成评审；待整个 MotionFlow 解耦组件化目标完成后统一总评审。

## 6. 阶段 3：Backend 生命周期与 Contract Test Kit

状态：**复审整改中；旧的完成结论已撤销。**

1. 拆分 Lifecycle/Diagnostics/Motion/SystemControl/IO ports。
2. BackendManager 验证 manifest 与 port bundle。
3. 实现状态转换、超时、断线、DEGRADED、ERROR 和 shutdown。
4. simulation、ZMotion、Dummy Backend 运行同一 Contract Test Kit。
5. 在无 ZMotion SDK/插件环境验证产品启动。

完成记录（2026-07-29）：

- 新增 vendor-neutral `BackendPortBundle`，按 Lifecycle、Diagnostics、Motion、SystemControl、IO 拆分运行时端口；`BackendManifest.required_ports` 声明插件实际所需能力，Manager 在启动前校验声明与 bundle 一致，缺失或非法端口 fail-closed。
- 新增 `BackendManager`，实现 `CREATED -> STARTING -> READY/DEGRADED/ERROR -> STOPPING -> STOPPED` 状态机；启动和关闭有界超时，断线诊断进入 `DEGRADED` 且可恢复，端口抛出 transport 异常统一进入脱敏 `ERROR`，关闭幂等并禁止 STOPPED 后复用。
- 产品唯一组合根改为构造并启动 Manager；旧 `create_product_robot_backend` 仅作为 CLI/Bridge/诊断兼容 API 保留。架构门禁将 `BackendManager` 与产品 Manager 工厂纳入 concrete runtime ratchet，业务层不能新增隐藏组合根。
- Simulation、ZMotion read-only 与显式 Dummy Backend 运行同一 `tests/contract/backend_contract_kit.py`；Dummy 不进入默认产品 Registry，证明新增 Backend 只需 plugin、manifest、port bundle 与契约测试。
- 未配置 ZMotion SDK 时，产品仍可创建 ZMotion Manager 并以 `DEGRADED` 启动；Simulation 为 `READY`。状态响应增加 vendor-neutral `backend_health`，不向上泄露厂商类型或连接细节。
- 生命周期/契约/组合根定向门禁 `50 passed`；扩大 Server/RobotAI/architecture/contract 回归 `826 passed, 1 deselected`；完整 Python 门禁 `3858 passed, 23 skipped, 1 deselected`（仅 2 个既有 Windows asyncio transport 清理 warning）；compileall 与 `git diff --check` 通过。
- 依照最新规则，本阶段不做独立完成评审；待整个 MotionFlow 解耦组件化目标完成后统一总评审。

## 7. 阶段 4：Tool Runtime

状态：**已完成。**

1. 扩展 manifest schema。
2. Tool 只依赖 RobotApplicationPort。
3. 统一可见性和执行授权二次校验。
4. 加入资源独占、timeout、cancel、idempotency 和审计。
5. 保留 Legacy adapter 至全部入口完成 parity。

完成记录（2026-07-29）：

- Tool manifest 升级为 v2，声明 timeout、concurrency、resource claims、idempotency 与 audit policy；`to_public_dict(protocol_version=1)` 保留 v1 golden fixture，同时新增 v2 fixture，协议演进不破坏旧消费者。
- 新增 SDK-neutral `ProductToolRuntime`、Tool Registry、Context/Invocation/Result 与 Audit Port；每次执行均重新检查 enabled、trusted role 与 Backend capability，不能依赖模型可见性替代执行授权。
- Runtime 实现有界 timeout、async cancellation 传播、跨 Tool 资源锁、actor/exclusive 并发策略、exact-scope request idempotency、参数哈希审计以及 required audit 写前 fail-closed/终态 unknown 语义；异常统一脱敏。
- Legacy 同步工具由受监督 worker 执行；deadline/cancel 通过 `OperationControl -> BackendCallContext -> ZMotion executor` 逐层传播。物理调用超时后 Runtime 不释放 controller/resource lock，直到 worker 真正结束；fingerprint 被标记为 unresolved，即使换幂等键也禁止自动重试。
- Nanobot Registry 只注册 `NanobotToolRuntimeAdapter`，所有 Robot/Cron Tool 调用都穿过同一治理 Runtime；产品使用 JSONL Tool Audit Adapter，Legacy Tool 结果通过稳定 DTO 适配。
- Robot Knowledge 新增 Application/Port/File Adapter；RobotArm 的 standalone 兼容构造隔离到 `legacy_robot_arm.py`。产品 Robot Tool 源码只依赖 Application/Domain contracts，不再导入 Platform、Backend、Store 或具体 Adapter。
- Tool/manifest/Application/Provider 定向与扩大门禁包含在 `856 passed, 1 deselected`；完整 Python 门禁 `3882 passed, 23 skipped, 1 deselected`（仅 2 个既有 Windows asyncio transport 清理 warning）；compileall 与 `git diff --check` 通过。
- 依照最新规则，本阶段不做独立完成评审；待整个目标完成后统一总评审。

## 8. 阶段 5：Agent Provider

状态：**已完成。**

1. Nanobot 具体实现迁入 provider adapter。
2. Server 不再导入 AgentLoop、MessageBus、Nanobot Session/Cron 具体类型。
3. Fake Provider 通过完整 Contract Test Kit。
4. 完成最小第二 Provider PoC，验证事件、取消、背压、Tool correlation。

完成记录（2026-07-29）：

- Nanobot 的 `AgentLoop`、`MessageBus`、`SessionManager`、`CronService` 与 ToolLoader 具体装配全部迁入 `ai_runtime/providers/nanobot_runtime.py`；`robot_server` 只选择 `AiProvider -> AgentEngine` 合同，不再导入这些具体运行时类型。
- 保留 `NanobotProvider/NanobotEngine` 作为默认 Adapter；新增可实际启动、提交、发事件、读取/删除 session 的 `ScriptedProvider/ScriptedAgentEngine` 第二 Provider，部署可通过受保护的 `ROBOT_AI_ENGINE` 选择。
- 新增可复用 AgentEngine Contract Test Kit 与 Fake Provider；验证 lifecycle、connectivity、submit、request correlation、final/turn_end event、cancel、session read/delete 和 shutdown。
- RuntimeEvent 在合同边界深拷贝并校验；Provider 事件队列有界，慢消费者只淘汰最旧事件并记录 dropped count，避免无界内存；Nanobot runtime 异常不再把 provider/host/credential 异常文本发送给客户端。
- 架构门禁禁止 Server 重新导入 Nanobot AgentLoop/Bus/Session/Cron concrete runtime，并保持 Provider core 不依赖 Server/Backend。
- 阶段 4/5 扩大回归 `856 passed, 1 deselected`；完整 Python 门禁 `3882 passed, 23 skipped, 1 deselected`（仅 2 个既有 Windows asyncio transport 清理 warning）。
- 依照最新规则，本阶段不做独立完成评审；待整个目标完成后统一总评审。

## 9. 阶段 6-8：产品组件化

- 阶段 6：拆分 Server 路由模块，保持协议完全兼容。
- 阶段 7：Flow Node 类型化、快照、恢复、回放和受控补偿。
- 阶段 8：WebUI 按 feature 收口，Electron 保持 ProductManifest-only。

状态：**已完成。**

完成记录（2026-07-29）：

- Server 的所有 API/WS route ownership 从 `app.py` 抽取为 WebUI、Product/Identity、Management/Library 三个 feature catalog；通用 registry 保留 GET 自动 HEAD 语义，route key 唯一且 handler 存在由架构测试固定。`app.py` 只调用统一 feature registrar，全部原路径与 handler 行为不变。
- Flow snapshot step 暴露强类型 `FlowNodeType`；新增 versioned `FlowExecutionEvent`，真实 staged Flow 由 Composition Root 注入 JSONL event sink，事件绑定 execution ID 与 immutable snapshot hash。
- v2 `Action/Condition/Sequence/Parallel/Retry/Timeout/Compensation/HumanApproval` 图已接入 production `run_flow`；快照校验每个 Action 与不可变 step 的 index/ID/command/parameters 精确绑定。并行图禁止 motion/IO/system 副作用，Retry 禁止物理副作用，避免未知物理结果被重放。
- Product Feature Policy 已扩展到 Tool、注入的 Application port、HTTP route catalog、Platform/Flow 与兼容入口；arm、flow、knowledge、position、library、cron 任一禁用后均在对应边界 fail-closed。
- Library Execution Registry 启动时把遗留 queued/running/paused/stopping 记录收敛为 `reconcile_required/execution_outcome_unknown`，永不在进程重启后自动重放真实动作；暂停、单步、停止和确定结果历史继续兼容。
- 受控补偿只生成经可信操作者显式授权、且执行结果明确记录 previous state 的 IO 反向计划；motion/system/delay 永不自动补偿，规划组件自身不执行硬件写入。
- WebUI 新增 `@/robot` feature public API；应用壳改为只导入 barrel，ESLint 禁止 Host 跨入 feature internals，既有 transport v1 contracts 与 554 项前端测试保持通过。
- Electron 将 backend、controller、execution mode、首测阈值、vendor wrapper、data/UI/health/server command/icon 全部收口进 ProductManifest；main shell 不再含 ZMotion 产品选择分支。TypeScript build、manifest、before-pack 和 packaged-launch contracts 通过。
- 阶段 6-8 Python 扩大回归 `855 passed, 1 deselected`；WebUI lint `0 errors`、`554 passed, 33 skipped`、production build 通过（仅保留既有 circular chunk/bundle size warning）；Electron build 与三项 contract smoke 通过。
- 依照最新规则，本阶段不做独立完成评审；整个目标的软件门禁完成后统一总评审。

## 10. 阶段 9：外部验收和拆包判定

1. 脱敏目标 runtime 迁移、启动、回滚。
2. 受控硬件只读、dry-run、最小动作、急停/复位验收。
3. 第二个真实产品/Backend/Provider 使用验证。
4. 满足 ADR 全部门槛后才制定物理拆包计划。

状态：**软件整改与新鲜独立评审待完成；外部工位项目仍为 `READY_NOT_RUN`；物理拆包结论保持 `NO-GO`。**

完成记录（2026-07-29）：

- 新增 `motionflow-final-acceptance-and-split-decision.md` 与机器可读 `motionflow-acceptance-status.json`，列出脱敏迁移、ZMotion 只读、dry-run、最小动作、急停/复位、签名安装包和第二产品的证据要求。
- 复用已有 copy-only runtime migration rehearsal、ZMotion readonly verifier、release checklist、Electron package smoke 与真实执行负向矩阵；所有现场步骤明确禁止把 simulation/Dummy/Scripted 结果冒充真机签核。
- 当前缺少本次变更后的受控硬件签核和第二真实产品证据，因此按主方案门槛作出 `NO-GO`：保持模块化单体，不物理拆 wheel/npm/仓库。该判定是完成验收决策，不是隐藏或跳过外部门槛。
- 本轮整改后的新鲜软件门禁：Python 全量 `3951 passed, 23 skipped, 1 deselected`（仅 2 个已知 Windows asyncio transport 清理 warning），第八轮整改后的扩大架构/RobotAI/Server 回归 `864 passed`；WebUI lint `0 errors`、全量 `554 passed, 33 skipped`、production build 通过；Electron TypeScript build 与 3 项 ProductManifest/packaging contract test 通过；compileall 与 `git diff --check` 通过。
- 第二次独立复审新增的 4 个 P1 与 3 个 P2 已关闭：设备级 Tool effect embargo 独立于 actor/session/request key；非读 Tool 强制持久化 request 幂等；Flow 全图 node ID 唯一且 stop 不触发补偿；Flow Application Port 恢复完整生命周期；unknown Tool 提供工程师授权、服务端控制器读回证据与双审计事件的 reconcile API；审计升级为日志目录外密钥的 HMAC-SHA256 链并在读取时 fail-closed。
- 第三次独立复审新增的两个 P1 已关闭：Tool operation record 现在保存 controller identity、canonical effect payload 与 readback predicate，reconcile 结论由服务器证据计算而非工程师文本决定；审计 append 不再允许 SHA 降级或同目录 key，全部 audit ID/migration ID 去重路径统一在锁内验签且只信任 HMAC 记录。
- 第四次独立复审新增的公开 SHA 伪认证链 P1 与审计去重竞态 P2 已关闭：带 hash 的非 HMAC 记录一律拒绝；纯 legacy SHA 文件隔离后重建可信链；统一原子 append-once 在同一临界区完成验签、签名 ID 去重和追加。
- 第五次独立复审所覆盖的 legacy SHA 校验、Tool effect identity 与跨进程审计锁整改已保留；第六次复审指出第五次结论遗漏混合未链/SHA 格式，因此旧关闭表述已撤回并由下述更严格整改取代。
- 第六次独立复审的 legacy public-SHA P1 已关闭：隔离仅接受从第一条开始的完整纯 SHA 链，任何未链/SHA 混合文件均原地 fail closed。该轮关于 controller dispatch receipt 的初始整改被第七次评审证明证据强度不足，旧表述已撤回。
- 第七次独立复审的 unknown 状态机与 named-position TOCTOU 已关闭；第八次复审继续发现 effect claim TOCTOU、账本/审计回滚和截尾、Flow/Cron canonical 缺口及注册边界声明式问题，旧阶段性关闭表述已由下述整改取代。
- 第八次独立复审的 4 个 P1/2 个 P2 已整改、等待第九次全新复审确认：Tool store begin 原子认领 request/effect，schema v3 通过目录外单调 generation/sealed head 拒绝 v1/v2 降级、旧 MAC 快照和删除；审计增加目录外 sealed head 防任意尾部截断；RobotArm/Flow/Cron/Library 全部提供动作级 canonical effect 并实际消费冻结 payload；非 read Tool 只能通过受控 Application-only adapter 注册；reconcile 明确只证明 Tool effect，不再混用 controller evidence 术语。
- 旧的最终独立总评审结论已撤销；当前等待一个全新的独立 Agent 对持久化 Tool 操作账本、Flow v2 端到端链、可信审批/身份、Feature Policy、审计哈希链、唯一组合根及 Electron ProductManifest 边界作整体复核。

## 11. 当前执行点

切片 **-1.1 至 -1.5** 的历史证据保留用于追溯，但旧 `APPROVE` 已被后续独立评审撤销。当前执行点是完成 P1/P2 整改、重跑全部门禁并交由一个全新的独立 Agent 评审；只有评审无阻断项后才能恢复软件完成状态。物理拆包仍因外部门槛不足明确 `NO-GO`。
