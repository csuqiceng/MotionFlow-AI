# 模块化迁移进度

本文件记录每个可独立验收的迁移成果。只有列出的验证命令实际通过后，状态才可标记为完成。

当前总体进度：**约 90%**。已完成当前简化 UI 基线、服务端真实 import 门禁、Backend registry 初版、ZMotion 可选插件化、完整 Robot Tool Contract 迁移、AgentEngine 服务端契约与 Nanobot 反向依赖清理、WebUI transport v1、Electron ProductManifest/打包冒烟、Python 全量回归，以及可执行的只读数据迁移演练工具；尚待在受控现场完成真实脱敏数据副本、回滚和硬件发布演练。

| 序号 | 成果 | 状态 | 验证证据 | 下一步 |
|---:|---|---|---|---|
| 1 | 恢复现有 WebUI Settings 与工程师工作台的服务端兼容基线 | 已完成 | `66 passed`：安全、平台、ZMotion 写入保护与 `tests/robot_server/test_app.py` | 添加架构依赖与 WebSocket frame 门禁 |
| 2 | 兼容性门禁：架构依赖、WS frame、关键页面旅程 | 进行中 | WebUI `528 passed`；WS `13 passed`；后端精选 `80 passed, 1 xfailed` | 审计剩余 Python 全量失败并执行 Electron 门禁 |
| 3 | Backend Contract 与显式 registry | 初版完成 | `tests/architecture/test_backend_registry.py`: `3 passed` | 将 ZMotion 从 application/core 调用路径迁出 |
| 4 | ZMotion adapter 隔离 | 已完成 | 核心路径 `163 passed`；simulation 与 server 的独立进程组成均不加载 ZMotion | 提取 Robot Tool Contract |
| 5 | Robot Tool / Agent 边界 | 已完成 | Tool 与核心安全/服务端门禁 `166 passed` | 定义稳定 AgentEngine 边界 |
| 6 | AgentEngine / WebUI / Electron 契约化 | 已完成 | fake engine WebSocket 与核心门禁 `166 passed`；Cron/Trigger/依赖门禁 `118 passed`；WebUI 全量 test/build 通过；Electron `build/dist/verify/smoke` 通过 | 全量回归与数据演练 |
| 7 | 全量回归、数据演练、拆包判定 | 进行中 | Python `3583 passed, 23 skipped`；Electron 发布物门禁通过；只读迁移演练工具与自动化迁移回滚保护已覆盖 | 完成现场脱敏数据/硬件演练后才可发布 |

## 成果 1：兼容性基线恢复

日期：2026-07-26

修复内容：

- 重新注册已有实现但遗漏的 Settings、CLI Apps 和 MCP Presets HTTP 路由，恢复当前 Settings 页面依赖的 API 表面。
- 让工程师命令/流程的旧 `validate` 与 `publish` 路由对“直接保存后已发布”的资源保持幂等成功；不重复创建版本，也不削弱未发布草稿的错误处理。
- 说明：全量 Python 测试的临时目录必须放在 **worktree 外**。放在 worktree 内会让 GitStore 测试把它识别为嵌套 Git 仓库而产生假失败。

验证命令：

```powershell
$env:TEMP = '.pytest-tmp-baseline-final'
$env:TMP = $env:TEMP
D:\learn\yjcao\nanobot-robotic-arms\nanobot-main-1\desktop\.build-venv\Scripts\python.exe -m pytest `
  tests\robot_ai\test_execution_gate.py `
  tests\robot_ai\test_pending_plan.py `
  tests\robot_ai\test_platform_use_cases.py `
  tests\robot_ai\test_zmotion_sdk_write_guard.py `
  tests\robot_server\test_app.py -q
```

结果：`66 passed in 5.15s`。

## 成果 2：兼容性门禁（进行中）

已完成的页面/协议子门禁：

- 修复了主侧栏“自动任务”入口：该入口原本能导航到 `/automations`，但 Settings 的白名单会把它静默重定向到“外观”。现在它作为独立工具页保持可访问，而不会出现在简化后的 Settings 导航中。
- 已将布局回归的基线切换到当前发布的简化 UI：Appearance、Voice、System 和工程师 Security 页面，以及 240px 侧栏宽度。
- 已生成 `robot_platform/graphify-out/graph.json` 的有向依赖基线（1,012 nodes / 3,632 edges），用于后续验证 ZMotion 解耦；该产物为本地分析文件，不纳入版本控制。
- 已新增兼容性矩阵 `modular-migration-compatibility-matrix.md`：当前简化 UI 为唯一基线；已删除的历史 Nanobot 页面只保留跳过测试作为历史记录，绝不在迁移中恢复。

已通过的验证命令：

```powershell
npm test -- --run src/tests/app-layout.test.tsx
```

结果：`43 passed, 1 skipped`。跳过项仅记录已从机器人产品移除的旧版全量 Nanobot Settings 控制台；当前受支持的 Settings 页面由新的旅程测试覆盖。

WebUI 全量门禁（2026-07-26）：

```powershell
npm test -- --run
npm run build
```

结果：`47 files, 528 passed, 33 skipped`；生产 TypeScript/Vite 构建通过。33 个跳过项均是已从当前发布的机器人产品移除的历史功能（旧完整 Settings、旧 Workbench 草稿/归档工作流、复制按钮、文件选择图片附件、旧项目/工作区选择及长按语音工作流）；保留功能已用当前页面旅程、工程师命令/流程直存、自动任务、听写和消息队列测试覆盖。

服务端边界测试已从全文字串扫描改为 AST import 扫描。`robot_server/identity_api.py` 保留对相邻 `robot_ai/users.json` 的一次性**数据迁移**读取：这不是代码依赖，删除它会让早期桌面版本中的有效账户无法从禁用占位账户恢复。以下命令通过：

```powershell
pytest tests\robot_server\test_robot_platform_boundary.py tests\robot_server\test_app.py -q
```

结果：`32 passed`。迁移测试也已改为从 `robot_platform` 构造旧目录中的数据；只保留目录名 `robot_ai` 来模拟旧数据，而不再通过兼容 Python 包导入测试辅助对象。

构建观察项（不阻塞本阶段）：Vite 报告 Markdown 相关的循环分块，且主 bundle 为 1.13 MB（gzip 357.60 KB）。在 WebUI 契约化阶段应将其作为独立的性能优化任务处理，不能与行为迁移混在一起。

### 成果 3：Backend Contract 与显式 registry（初版完成）

日期：2026-07-26

实现内容：

- 新增厂商无关的 `RobotBackend` Protocol 和可注入的 `BackendRegistry`；registry 负责名称、别名、重复注册和未知 backend 拒绝。
- 兼容入口 `create_robot_backend()` 不再直接 import Simulation/ZMotion；默认产品装配迁至 `robot_platform.backends.wiring`，厂商 SDK import 被限制在该装配模块。
- 保留原有配置字段与 `client_factory` 注入方式，避免修改当前部署配置和测试替身。
- 首次登录必须改密的会话不能再创建 Cron，避免在重构期间绕过安全闸门。后续应把该会话策略改为注入 port，避免 Agent Core 直接了解身份实现。

验证命令与结果：

```powershell
pytest tests\architecture\test_backend_registry.py -q
```

结果：`3 passed`。

```powershell
pytest tests\architecture\test_dependency_rules.py tests\architecture\test_backend_registry.py tests\robot_ai\test_execution_gate.py tests\robot_ai\test_pending_plan.py tests\robot_ai\test_platform_use_cases.py tests\robot_ai\test_zmotion_sdk_write_guard.py tests\robot_server\test_app.py tests\robot_server\test_websocket_frame_contract.py -q
```

结果：`80 passed, 1 xfailed`。唯一 xfail 明确记录 ZMotion 仍被 `platform.py`、`bridge.py` 和 flow 路径直接引用；它是下一阶段必须转绿的门禁，而非可长期豁免项。

### Python 全量回归（已完成）

使用 worktree 外的临时目录执行全量收集后，结果为：`3583 passed, 23 skipped`。迁移期间更新的测试均改为覆盖**当前**产品契约：不再要求暴露原始模型 reasoning、外部聊天频道配置、LLM 新建流程、历史禁用占位账户、旧 Electron 路径字符串，或依赖公共 DNS 不可达的 MCP 探测。

输出仍含两条 Windows Python 3.14 Proactor transport 析构 warning；测试断言全部通过。该 warning 需在 Python 运行时升级或 async 资源清理专项中处理，不能被误报成页面/机械手功能回归。

### 成果 4：ZMotion 核心路径逻辑隔离（已完成子阶段）

日期：2026-07-26

实现内容：

- 新建 `robot_platform.application.RobotOperationRequest`：`RobotPlatform` 和 flow executor 现在只创建厂商无关的操作意图；确认参数、待执行计划 ID 和确认码保持原语义。
- `robot_platform.backends.wiring` 成为 ZMotion 适配点。它把中立请求转为当前 `ZMotionOperatorRequest`，并以惰性导入方式加载 operator 与只读诊断；核心模块不再直接 import 厂商实现。
- `platform.py`、`flow/executor.py` 和 `bridge.py` 已移除直接 ZMotion import。flow 的执行 seam 改为 `run_operator_command`，测试也改为注入该中立 seam。
- 清理导入期耦合：`robot_platform` 的安全默认 store 移至中立 `execution.defaults`，工具 facade 改为首次使用时再创建默认 backend。新的独立进程门禁证明仅 `import robot_platform` 时不会加载 `robot_platform.zmotion*`。
- 更新一项过时 flow 测试：当前 Robot Tool 不再允许 LLM 通过 `register` 创作流程；测试改为由 `FlowRegistry` 预置已保存流程，再验证仍支持的别名运行路径。

验证命令：

```powershell
pytest tests\architecture tests\robot_ai\test_platform_use_cases.py tests\robot_ai\test_flow_executor.py tests\robot_ai\test_flow_aliases.py tests\robot_ai\test_zmotion_operator_safety_integration.py tests\robot_ai\test_zmotion_write_executor.py tests\robot_ai\test_execution_gate.py tests\robot_ai\test_execution_gate_wiring.py tests\robot_ai\test_pending_plan.py tests\robot_ai\test_zmotion_sdk_write_guard.py tests\robot_ai\test_desktop_bridge.py tests\robot_ai\test_robot_tools.py tests\robot_server\test_app.py tests\robot_server\test_websocket_frame_contract.py -q
```

结果：`145 passed in 6.82s`。

未完成范围（明确保留）：当前只完成了核心路径隔离；默认 registry 仍会在装配时加载厂商 backend 类，尚未证明删除 ZMotion adapter 后 simulation/server 仍可启动。

### 成果 5：ZMotion adapter 物理迁移（已完成子阶段）

日期：2026-07-26

- 真实 operator 实现已移至 `robot_platform.backends.zmotion_adapter`；只读诊断已移至 `robot_platform.backends.zmotion_readonly_diagnostics`。
- 根目录的 `zmotion_operator_control.py` 与 `zmotion_readonly_smoke.py` 保留为**模块对象别名**，不是普通 re-export。这保证旧测试/扩展对模块级安全 store 的 monkeypatch 仍作用于真实 adapter。
- 默认 product wiring 改为直接使用 backend 目录中的 adapter；根路径只承担兼容职责。

新增兼容门禁验证旧、新导入路径是同一模块对象。完整核心安全回归：`147 passed in 6.51s`。

该阶段已由下述“可选插件装配”成果完成；根目录兼容模块仍会保留到对外 API 的弃用窗口结束。

### 成果 6：可选 ZMotion 插件装配（已完成）

日期：2026-07-26

- `create_default_backend_registry()` 现在只包含 simulation；核心 `factory.py` 不再 import 或注册任何 ZMotion 类。
- 新增 `backends.product_wiring.create_product_robot_backend()`：只在配置选择 `zmotion_readonly`（或其别名）时惰性注册 `zmotion_plugin`。`RobotToolFacade`、desktop bridge 与只读诊断产品路径均使用该显式装配入口。
- 新增独立进程门禁：创建 simulation backend、组成 Robot Server 时，`sys.modules` 中均不存在 `robot_platform.backends.zmotion*`；真实 ZMotion 只读回归仍通过。
- 测试 seam 已随架构更新：SDK client 的替身注入从 core factory 移至 `zmotion_plugin`。

完整核心验证：`163 passed in 9.07s`。

### 成果 7：Robot Tool Contract 与兼容迁移（已完成子阶段）

日期：2026-07-26

- 新增 `ai_runtime.tool_contracts`：定义 SDK 无关的 `ToolContext`、`ToolInvocation`、`ToolResult` 和 `Tool` Protocol。
- 新增 legacy adapter，可将当前 `execute(**kwargs)` 工具保持原名称、JSON schema 和 JSON 结果地映射为结构化 Tool Contract。
- `robot_arm`、`robot_flow`、`robot_knowledge`、`robot_library`、`robot_position` 的实现移至 `ai_runtime.robot_tools`；旧 `nanobot.agent.tools.robot_*` 路径为模块对象别名，不维护第二套业务代码。
- `ai_runtime.tool_loader` 现从新的 runtime 路径装载 Robot Tool。已删除的 LLM flow authoring 行为不再被测试恢复；回归改为工程师/Library 预置流程后的 list/get/run。

综合验证：`165 passed in 9.66s`。

该阶段的 Nanobot Tool base/context 依赖已由下述 Runtime 脱钩成果清除；旧路径仅保留到兼容窗口结束。

### 成果 8：Robot Tool Runtime 脱离 Nanobot（已完成）

日期：2026-07-26

- 新增 `ai_runtime.robot_tools.base` 和 `context`，为 Robot Tool 提供独立的 Tool base、schema 装饰器与请求上下文。
- `ai_runtime.robot_tools` 目录已不存在任何 `nanobot.*` import；新增 AST 依赖门禁。
- 通用 Nanobot ToolLoader 不再自动发现 Robot Tool；只有产品 `RobotToolLoader` 显式注册，保持“通用 Agent 可不加载 Robot Tool”的边界。
- legacy 路径继续作为模块别名，现有调用、schema 和安全行为不变。

综合验证：`166 passed in 8.70s`。

### 成果 9：稳定 AgentEngine 服务端边界（已完成子阶段）

日期：2026-07-26

- 新增 `ai_runtime.engine_contract`，将现有 request/event wire model 固化为 `AgentRequest`、`AgentEvent`，并定义 `AgentEngine` Protocol。
- `robot_server.app` 与 WebUI compatibility adapter 只依赖 AgentEngine；不再 import `AgentRuntime` 具体实现。
- 新增 `NanobotEngine` 命名 adapter，产品 composition root 由它包装当前 `AgentLoop`；Server 的 fake runtime 可直接注入。
- fake engine 真实 WebSocket 测试覆盖 ready、message→submit、delta frame 和 cancel，全程不构造 NanobotEngine。

综合验证：`166 passed in 9.71s`。

未完成范围：`AgentRuntime` 仍包含 Nanobot loop 适配实现，且 Nanobot 内部仍需审计/移除对 `ai_runtime` 或 `robot_server` 的反向生产 import；下一子阶段处理这些方向约束。

### 成果 10：Nanobot 反向依赖清理（已完成）

日期：2026-07-26

- 新增中立 `agent_contracts.turn_metadata`，承载 runtime turn ID、消息来源和主动推送 metadata；`ai_runtime.turn_metadata` 与 `robot_server.scheduler_metadata` 保留为兼容层。
- `nanobot.triggers.local_runner` 与 `nanobot.cron.bound_runner` 已不再导入 `ai_runtime` 或 `robot_server`。Cron 主动推送保留新的 turn ID、来源标记和既有 session metadata 清理语义。
- 架构门禁现在解析 `Import` 与 `ImportFrom`。只有六个明确的历史兼容入口可导入高层模块：`nanobot.__main__` 的 `robot_server.cli`，以及五个 Robot Tool 的 `ai_runtime.robot_tools` 模块别名；这些文件中的任何额外高层依赖都会失败。
- 修复了 bootstrap 密码安全闸门的空 ContextVar 回归：未绑定请求上下文时，Cron 继续正常展示或保护系统任务；绑定了 bootstrap token 的会话仍不能新增或删除 Cron。

验证命令：

```powershell
$env:TEMP = 'C:\Users\a\AppData\Local\Temp\nanobot-migration-pytest'
$env:TMP = $env:TEMP
& D:\learn\yjcao\nanobot-robotic-arms\nanobot-main-1\desktop\.build-venv\Scripts\python.exe -m pytest `
  tests\architecture\test_dependency_rules.py::test_nanobot_core_does_not_depend_on_product_runtime_or_server `
  tests\triggers\test_local_triggers.py `
  tests\cron -q
```

结果：`118 passed in 6.18s`。注意必须使用项目桌面构建虚拟环境；系统 Python 会缺少 asyncio pytest 插件，导致异步用例被错误跳过，不能作为验收依据。

下一步：执行 Task 6，将当前简化 UI 的 HTTP/WS 访问集中为 transport contract。迁移只替换客户端实现，不恢复任何已删除的旧 Settings、工作区、草稿或附件页面；每一条现有页面旅程仍以兼容性矩阵和 Vitest 为准。

### 成果 11：WebUI transport 兼容 seam（已完成子阶段）

日期：2026-07-26

- 新增 `webui/src/transport/http.ts`、`websocket.ts`、`client.ts` 与 `events.ts`。Transport Client 接受 base URL、可注入 fetch 与 WebSocket factory，便于在未来产品或测试中替换通信实现。
- 当前 HTTP API helper 仍保留全部公开函数、URL、header、timeout 和错误语义；旧 `lib/http.ts` 已变为向新 transport 的兼容 re-export，故现有 Settings、工程师工作台、资产库、用户和自动化页面无需改组件代码。
- `NanobotClient` 的普通 WebSocket 创建已通过 transport，Electron host socket 继续走已有 native adapter。接收帧先检查稳定 `event` 信封：无效 JSON 或无事件名的帧安全忽略；未来事件名称保留给老客户端忽略，避免因服务端增量升级导致页面崩溃。
- 新增 transport contract 测试，覆盖 base URL、注入 fetch、注入 socket factory、无效帧与前向兼容事件。没有恢复任何已删除的旧页面或工作流。
- `GET /webui/bootstrap` 现声明 `protocol_version: 1`；WebUI 类型将该字段保持为可选，因此尚未升级的服务端与已发布的客户端都不会因字段缺失失败。
- `fetchBootstrap()` 将缺失版本视为 v1，并拒绝高于当前支持版本的服务端。初始 bootstrap 若不兼容，App 停止连接流程并明确提示“更新桌面应用”，不再把这种升级问题伪装成普通连接失败。
- 机械手状态、dry-run 计划、确认、执行、flow 计划及急停/暂停等系统动作的 REST helper 已物理迁入 `transport/robot.ts`；`lib/robot-api.ts` 只保留兼容 re-export。请求路径、认证、30 秒 timeout 和完整确认链均未改变。
- 已发布资产库的命令/流程读取、执行记录和执行控制已物理迁入 `transport/library.ts`；`lib/robot-library-api.ts` 只保留兼容 re-export。执行读取和控制继续传递 gateway token 与 `X-Robot-User-Token`，不改变现有角色/安全边界。
- 用户列表、新建、角色/启用状态更新、重置密码与删除已物理迁入 `transport/users.ts`；`lib/users-api.ts` 只保留兼容 re-export。所有账户写操作继续要求 gateway token 与用户身份 token，保持既有角色权限路径。
- 工程师工作台的命令/流程直存、草稿兼容操作、校验、发布、归档、导入导出、诊断与审计已物理迁入 `transport/engineer-workbench.ts`；`lib/engineer-workbench-api.ts` 只保留兼容 re-export。冲突响应仍保留 `EngineerConflictError` 的 revision/code 细节。

验证命令：

```powershell
cd webui
npm test -- --run
npm run build
```

结果：`48 files, 531 passed, 33 skipped`；TypeScript/Vite 生产构建通过。33 个跳过项仍仅对应已从当前发布产品移除的历史功能。

补充协议验证：`tests/robot_server/test_app.py` 的 bootstrap/路由契约 `2 passed`；`webui/src/tests/bootstrap.test.ts` 与 `app-layout.test.tsx` `57 passed, 1 skipped`。

Robot transport 验证：`robot-api`、状态 hooks 与操作员页面 `14 passed`。现存 `RobotOperatorApp` 测试的 React `act(...)` warning 是既有异步测试告警，不影响断言结果；后续测试清理阶段单独处理，避免将其与协议迁移混合。

Library transport 验证：资产库 API、library hook、命令/流程页面与执行监视器 `22 passed`。

Users transport 验证：账户 API 与当前简化应用布局回归 `47 passed, 1 skipped`。

Engineer transport 验证：工程师 API、工程师工作台和命令库页面 `17 passed`。

### 成果 12：WebUI transport v1（已完成）

日期：2026-07-26

- HTTP transport、WebSocket factory、帧信封校验、protocol version 协商和所有当前产品 API 分类（机械手、资产库、用户、工程师工作台）均已迁入 `webui/src/transport/`；旧 `lib/*-api.ts` 路径全部为兼容 re-export。
- 当前已发布的简化 UI 仍是唯一契约：不恢复任何旧 Settings、工作区、草稿或附件页面。HTTP path、认证 header、错误形状、安全确认链、native host socket 和现有 WebSocket frame 均保持不变。
- 服务端 bootstrap 声明 v1；缺失字段的旧服务端兼容，较新不兼容版本会显示升级提示而不是继续发送控制命令。

全量前端门禁：

```powershell
cd webui
npm test -- --run
npm run build
```

结果：两条命令均以 exit code `0` 完成。测试输出包含已有的 KaTeX quirks-mode、React `act(...)` 和 Vite chunk-size/circular-chunk 告警，但没有测试或构建失败；这些告警是后续独立质量任务，不能作为页面/协议迁移通过的替代证据。

下一步：执行 Task 7，将 Electron 主进程、服务监督和首次启动行为整理为 `ProductManifest`，确保当前 MotionFlow 包的启动命令、health check、数据目录和单服务约束保持不变。

### 成果 13：Electron ProductManifest 与发布物门禁（已完成）

日期：2026-07-26

- 新增 `desktop/electron/product-manifest.ts`，以 `motionFlowManifest()` 集中描述产品 ID、显示名、health path、数据目录、UI loopback 来源、配置模板、首次启动种子目录、默认数据目录、ZMotion vendor 目录及 dev/packaged robot-server 命令。
- `main.ts` 现在通过 manifest 创建 server supervisor；开发模式保持 `python -m robot_server.cli`，打包模式保持 `resources/py-runtime/robot_server.exe`，参数仍为 `--port` 与 `--config`。
- 主进程的 health probe、主窗口 URL、首次配置/机器人默认数据种子和 vendor SDK 环境路径也只消费 manifest；页面路由和首次启动语义没有改变。
- 便携模式 `--portable` 与正常 `%APPDATA%\motionflow-ai\runtime` 数据目录均被 manifest 单测固定。现有 portable marker 兼容仍在主进程保留。
- 补回并纳入版本控制 `desktop/pyinstaller/robot_server.spec`。该 spec 显式收集配置驱动的 ZMotion 插件，并明确排除已删除的多通道、gateway 与配对模块；PyInstaller 启动器优先当前 worktree，避免 build venv 的 editable 安装打入其他工作树源码。
- 发布校验改用 .NET SHA-256，避免依赖可选的 `Microsoft.PowerShell.Security` 模块。可用时仍报告可执行文件签名状态；本机模块不可用时只给出警告，因为本地产品构建未配置代码签名。

验证（2026-07-26）：在 desktop 工作树执行 `npm run build`、`node electron/tests/product-manifest.test.js`、`node electron/tests/before-pack.test.js`、`node electron/tests/packaged-robot-server-launch.test.js`、`npm run dist`、`npm run verifyRelease` 与 `npm run smokePackagedRobotServer` 均以 exit code 0 完成。smoke 从 `win-unpacked` 复制带空格路径的应用，启动实际 `robot_server.exe`，并验证 `/health` 与当前 WebUI HTML。

说明：本次本地安装包采用占位组织密钥，只能作为结构和启动回归证据，不能代替带正式组织密钥的发布签名/人工首启验收。

渲染检查：本地 Vite 首屏显示当前简化登录页和下位机连接区，无框架错误遮罩。由于本次检查未启动 Robot Server，连接检测显示“无法建立控制台连接”并在 console 记录 `bootstrap unavailable`；这符合无后端环境，不能替代已登录后的真实服务端/机械手集成验收。

待完成：

- 依照 [`release-checklist.md`](release-checklist.md) 完成脱敏数据副本、回滚和受控硬件演练。任何阶段都以当前已发布的简化 UI 为基线，只更新覆盖它的测试，绝不恢复已删除的历史页面或功能；物理拆包仍按 [`package-extraction-decision-record.md`](package-extraction-decision-record.md) 暂缓。

### 最终自动化回归快照

日期：2026-07-26

- Python：`3584 passed, 23 skipped`；仅有两条 Windows Python 3.14 Proactor 资源清理 warning。
- WebUI：`48 files, 537 passed, 33 skipped`，并完成生产构建。测试/构建输出保留既有 KaTeX、React `act(...)`、连接测试和 chunk-size/circular-chunk warning。
- Electron：TypeScript build、manifest/before-pack/启动参数测试、NSIS 打包、`verifyRelease` 和实际 `robot_server.exe` packaged smoke 均通过。签名状态在本机因缺失 PowerShell Security 模块只作 warning；本地安装包使用占位组织密钥，不能代替正式签名发布。
- 数据保护：legacy `robot_ai` → `robot_platform` 复制保留源目录和迁移报告，身份恢复、架构依赖及数据迁移精选回归 `17 passed`。

### 成果 14：可执行只读数据迁移演练（已完成）

日期：2026-07-26

- 新增 `robot_platform.migration_rehearsal` 与 `tools/rehearse_runtime_migration.py`。工具将指定 runtime 复制到空 scratch 的 `runtime/`，并在隔离的 `legacy-replay/` 中执行 `robot_ai` → `robot_platform` 的首次迁移重放；不会启动 Robot Server、backend 或硬件连接。
- 报告同时记录 SHA-256、文件大小与 JSON 顶层记录信息，验证源 legacy 副本未改动、完整 runtime 副本保持原样，以及 replay 的 canonical 目录与 legacy 目录字节级等价。即使源 runtime 已有 canonical 数据，演练也不会覆盖它。
- 保护性拒绝：scratch 非空、scratch 是文件、源目录缺少 legacy 数据、或 scratch 位于源 runtime 内都会失败；不会合并、覆盖或删除用户数据。

验证：`tests/architecture/test_runtime_migration_rehearsal.py`：`5 passed`，包含源 runtime 已有 canonical 数据时仍保留完整副本的回归场景。

本机运行时演练（2026-07-26）：以 `%APPDATA%\\motionflow-ai\\runtime` 为只读源、空 scratch 为目标执行，报告 `ok: true`；源运行时已有 canonical 数据，完整副本保持原样，`legacy-replay` 中的 6 个 legacy 文件与迁移目标逐项 SHA-256/大小/JSON 顶层记录一致。完整 Python 回归随后为 `3584 passed, 23 skipped`。

安全面板交互复核（2026-07-26）：急停、解除急停、暂停、继续、报警复位、解除取消和停止当前移除了两层浏览器确认框，改为执行中/结果 Tip；它们仍调用同一条服务端计划、确认码和执行链。修复了 simulation 系统动作误路由到 ZMotion adapter 的缺口：simulation 现在完成七种系统动作且不加载厂商模块。组件回归 `8 passed`，全量 WebUI 回归 `49 files, 545 passed, 33 skipped`，隔离 simulation 逐项实测七个按钮均无弹框且返回成功 Tip。

下一步：在目标机器拿到经脱敏的真实 runtime 副本后，运行工具并按发布清单完成 simulation 启动、回滚和受控硬件验收。

### 成果 15：版本化、厂商无关的机械手能力契约（已完成）

日期：2026-07-26

- `ControllerCapabilities.to_public_dict()` 新增稳定的 `protocol_version: 1` 输出，包含当前全部非厂商字段：`supports_state_read`、`supports_real_writes` 与 `motion_primitives`；`vendor` 明确不属于新契约，避免上层代码按厂商名称分支。
- `RobotToolFacade.robot_get_status()` 同时输出新 `data.capabilities` 与旧 `data.controller_capabilities`。旧字段保持原样，避免破坏已发布客户端；新接入的 WebUI、Tool 与未来插件只依赖 versioned capability 字段。
- `/api/robot/status` 对仅返回旧字段的平台实现补齐新的 v1 字段，因此升级期间不会因为缓存/兼容 adapter 而缺失能力说明。
- 新增 fixture、模型契约测试、canonical facade 测试与 HTTP API 测试，覆盖新字段无厂商信息、旧字段兼容保留以及 legacy 服务端转换。

验证：先确认缺少序列化器和 HTTP 字段时测试失败；实现后运行 `tests/architecture/test_capability_contract.py`、完整 `tests/robot_server/test_app.py` 与 `tests/robot_ai/test_robot_tools.py`，结果 `41 passed`。`git diff --check` 通过。

下一步：实施 Task 2，把 simulation 与 ZMotion 从“按 mode 的产品 wiring”升级为显式 Backend Plugin manifest。目标是在不加载 ZMotion 的情况下运行 simulation，并为 ROS2、Modbus 等新协议提供同一种注册方式。

### 成果 16：显式 Backend Plugin manifest（已完成）

日期：2026-07-26

- 新增 `RobotBackendPlugin` 契约，插件必须声明稳定 ID、版本和可注册的 backend mode。
- `BackendRegistry.register_plugin()` 以事务方式注册插件：元数据缺失、重复 plugin ID 或声明的 mode 未实际注册时均会失败，并恢复注册前状态。
- simulation 迁入 `SimulationBackendPlugin`，成为核心参考插件；默认 registry 不再手工注册 simulation factory。
- ZMotion 迁入 `ZMotionBackendPlugin`；产品组合根只在明确选择 ZMotion mode 时延迟导入并注册该插件。旧 `register_zmotion_backends()` 保留为兼容 helper，但内部也走 manifest。
- registry 不接受配置文件或用户输入的 Python 模块路径；产品 wiring 只能从静态代码允许的插件集合装配。

验证：先确认缺少 `register_plugin()` 时新契约测试失败；实现后插件/无厂商依赖回归 `10 passed`、ZMotion 只读与 adapter 兼容回归 `16 passed`、完整 architecture suite `25 passed`。simulation 子进程验证继续证明未加载任何 `robot_platform.backends.zmotion*` 模块。

下一步：实施 Task 3，为 Tool 加入 manifest、能力需求、角色权限和启用状态。AI 只能看到并调用当前机械手能力与当前角色都允许的 Tool。

### 成果 17：Tool manifest 与资格筛选基础（已完成）

日期：2026-07-26

- 新增 `ToolManifest`：每个产品 Tool 可声明稳定 ID、版本、所需机械手 capability、允许角色和风险等级（`read` / `motion` / `system`）。无效元数据会在注册前失败。
- 新增独立于 Nanobot SDK 的 `robot_server.tool_registry.ToolRegistry`。它以能力、角色和启用集合评估 Tool，并返回明确的 `tool_disabled`、`role_forbidden` 或 `capability_missing` 原因，供未来 API/UI 显示。
- `LegacyRobotToolAdapter` 现在可携带 manifest；旧 Tool 能逐个迁移到新规则，而不需要停机重写现有 Tool。
- 该阶段只建立安全筛选核心，不改变当前已发布聊天运行时注册的 Tool 集合。后续产品配置阶段会把工程师启用状态接入 runtime；在那之前不会静默移除当前用户正在使用的能力。

验证：先确认 Tool manifest 和服务器筛选器模块缺失时测试失败；实现后 Tool manifest/registry/compatibility loader 相关 `9 passed`，完整 architecture suite 加现有 Tool loader 回归 `29 passed`，`git diff --check` 通过。

下一步：实施 Task 4，把当前 Nanobot 引擎包进只读底层 AI Provider 配置。Provider、模型、URL 和密钥不会新增任何 UI 或用户 API，只能由部署配置加载。

### 成果 18：底层 AI Provider 配置与 UI 隔离（已完成）

日期：2026-07-26

- 新增 `AiProviderConfig` 和 `AiProvider` contract。服务端从受控 `config.json`、环境变量和凭据引用解析引擎、Provider、模型与 `credential_ref`；运行时配置对象不保存 API key、endpoint URL 或 provider 实例。
- 当前 `NanobotEngine` 被 `NanobotProvider` 包装。`robot_server.runtime.create_agent_runtime()` 先解析底层 Provider 配置，再构造引擎；以后新增本地/私有/其他 AgentEngine 只需添加内部 Provider adapter。
- `/api/settings` 不再返回聊天 AI 的 Provider、模型、预设、密钥状态或 endpoint 信息；旧 AI 设置路由已保持未注册。
- WebUI 即使收到旧 `#/settings?section=models` 深链，也会回退到允许的操作员设置，无法渲染 Provider、模型或新增配置控件。
- 聊天 composer 将 `agent.configured: true` 解释为“AI 已由部署端配置”。因此公开 settings payload 刻意省略模型/Provider 明细时，发送消息仍会走正常聊天通道，不会错误跳转到已禁用的模型设置页；保留旧 payload 的未配置模型兜底行为。
- 登录页语音健康检查同样使用 CLI 传入的 `deployment_config_path`，与实际 AI runtime 读取同一份受控底层配置；不再因回退到默认用户目录而把已配置的语音服务误报为“未配置”。该检测只返回健康状态和错误类别，不会向 UI 返回凭据、Provider URL 或模型信息。
- 服务重启时若存在进行中的本地 Agent Tool 调用，下一次启动会把该调用收束成明确的中断说明，而不是把未完成的 Tool checkpoint 带入后续聊天。这样后续的“你好”等新消息不会被旧 `robot_arm` 调用反复污染；用户需明确重新发送被中断的操作。

验证：Provider 配置模块和 Engine Provider 缺失时测试先失败；实现后 Provider config/engine/runtime/API/architecture 回归 `32 passed`，SettingsView 定向回归 `4 passed, 17 skipped`。新增 composer 回归覆盖“AI 已在部署端配置、公开 payload 无模型/Provider”的发送路径，确认发送不跳转模型设置页。新增登录预检回归确认语音探测读取传入的部署配置且仅返回健康状态；完整 `tests/robot_server/test_app.py` 为 `34 passed`。新增 runtime 重启恢复回归：中断的 Tool checkpoint 会在启动时转为明确的终止说明，完整 Agent/runtime/server 定向套件为 `85 passed`。测试输出中的 `localhost:3000 ECONNREFUSED` 是既有 host bridge 探测 warning，断言均通过。

下一步：实施 Task 5，提供机器人和 Tool 的工程师配置 API 与页面；该页面只处理 backend、能力与 Tool 启用状态，绝不提供 AI Provider 或模型配置。

### 成果 19：工程师机器人 / Tool 产品配置（已完成）

日期：2026-07-26

- 新增持久化的 `product_profile.json`，只包含已批准的 `backend_mode` 和 `enabled_tools`；其余控制器连接参数、SDK 路径、安全策略、AI Provider、模型、地址、密钥均不属于该 profile。
- 新增工程师专属 `GET/PUT /api/management/product-profile` 与 WebUI “机器人与 Tool 配置”页面。响应明确提供 backend capability 和 Tool 资格原因，但不返回任何 AI 配置字段。
- CLI 组合根会在服务启动时读取 profile：backend 选择会用于 `RobotPlatform` 的状态、计划和执行路径；Tool 启用集会用于新建的 AI runtime。因此保存后**重启服务**才生效，运行中的会话不会被静默换后端或移除 Tool。
- 历史 `robot_library` 强制注册例外已删除；profile 禁用的任一 Tool 都不会注册到新的 AI runtime。
- profile 仅接受代码静态允许的 `simulation` / `zmotion_readonly` 和现有 Tool catalog；未知 backend 或 Tool 被拒绝，不能借配置加载任意 Python 插件。

验证：先新增“重启后 profile backend/Tool 生效”与“禁用 `robot_library` 不再注册”测试，确认组合根缺失和历史强制注册分别失败；实现后 Python 定向套件 `67 passed`。WebUI 新增配置页面保存/AI 字段缺失测试；完整前端回归和生产构建均以 exit code `0` 通过。全量 Python 回归为 `3608 passed, 23 skipped`；为消除 `tests/robot_server/test_tool_registry.py` 与 `tests/tools/test_tool_registry.py` 的同名模块收集冲突，pytest 默认改用 `importlib` 导入模式。全量前端输出仍保留既有 KaTeX、React `act(...)`、localhost host-bridge 探测和 Vite circular-chunk/chunk-size warning，均不影响断言或构建结果。

下一步：执行 Task 6 的发布安全验证：补齐 profile 的 simulation/角色/能力矩阵、确认 AI/Tool 不能绕过执行确认闸门，并在脱敏 runtime 和受控硬件环境完成迁移、回滚与真实安全动作演练。

### 成果 20：发布安全验证矩阵（自动化部分完成）

日期：2026-07-26

- 发布清单已按 Product Profile 列出四种独立情景：默认 simulation、仅知识 Tool、ZMotion 只读和非法 profile 拒绝；每种情景都明确 backend、AI runtime Tool 集、AI 配置不可见与验证要求。
- 发布清单新增统一的安全不变量矩阵，覆盖 AI Tool、HTTP API、资产库流程和人工操作：dry-run 默认、计划/双确认/确认码/会话绑定、跨计划/参数/会话复用拒绝、急停独立性和 Tool 禁用无旁路。
- 自动化证据已指向具体的 profile、runtime、Tool loader、确认闸门、pending plan 与 ZMotion 安全集成测试；完整 Python 回归 `3608 passed, 23 skipped` 和完整 WebUI test/build 为本阶段的本地基础证据。
- 明确保留的发布阻断项：脱敏真实 runtime 副本迁移/回滚演练，以及批准工位的真实硬件安全验证不能由 simulation 或自动化替代。

下一步：取得脱敏 runtime 副本后按发布清单完成迁移和回滚演练；随后在受控工位完成 ZMotion 只读、dry-run 和经批准最小真实动作的现场签核。物理拆包判定只能在这些证据齐全后进行。

### 成果 21：物理拆包决策复核（已完成）

日期：2026-07-26

- 基于当前 import 边界、Backend plugin、Tool contract、Provider adapter、WebUI transport 与 Electron manifest 重新审计 ADR；结论是继续保持模块化单仓，不发布空壳 PyPI/npm 包。
- `robot-platform-core`、ZMotion backend、Tool SDK、Provider、WebUI transport 和 Electron 壳均已逐项记录为“可候选但未满足提取门槛”或“尚未具备独立边界”。
- 重新评估改为可验证条件：第二产品使用方、版本化公开 API/弃用策略、独立安装测试、可选 SDK 打包验证、现场发布清单完成及跨项目升级演练。任何一项缺失都不触发物理拆包。

验证：`tests/architecture/test_dependency_rules.py` 和 `tests/architecture/test_backend_plugin_contract.py` 用于持续验证本次判定依赖的核心方向和 plugin 边界。

下一步：等待脱敏 runtime 副本与受控硬件条件，按发布清单完成外部验收；在外部验收完成前，继续以当前单仓的稳定契约支持新增 backend、Tool 和内部 Provider adapter。

### 成果 22：本机运行时只读迁移演练（已完成）

日期：2026-07-26

- 对当前 `%APPDATA%\\motionflow-ai\\runtime` 执行 `tools/rehearse_runtime_migration.py`；工具只复制到独立的临时 scratch，不启动 Robot Server、backend 或硬件，也不修改原 runtime。
- 演练报告为 `ok: true`：源 runtime 已有 canonical 数据；隔离 replay 完成 legacy `robot_ai` → `robot_platform` 迁移；legacy 保留；目标与 legacy 清单逐项字节数/SHA-256 一致。
- 本次重放核对了 6 个 legacy 文件：审计、命令、流程、执行记录、位置和用户数据；JSON 顶层记录数也已写入报告。
- 该证据仅证明本机数据结构的复制和迁移可重放，**不能替代**脱敏生产副本的回滚验收、不同版本升级演练或受控硬件验证。

下一步：使用经脱敏的目标运行时副本按发布清单完成升级后 simulation 启动和回滚；随后在批准工位完成 ZMotion 只读、dry-run、最小真实动作与急停签核。

### 成果 23：隔离 Simulation 启动烟测（已完成）

日期：2026-07-26

- 使用全新的临时 runtime 数据目录、当前受控底层配置和 `ROBOT_AI_BACKEND=simulation` 启动 `robot_server.cli`；服务的 `GET /health` 返回 `{"status":"ok","service":"robot-server"}`。
- 该 smoke 没有发送聊天消息、没有执行 Tool、没有打开 ZMotion backend；健康响应取得后立即停止子进程。
- 这证明当前组合根可以在空数据目录用 simulation 启动，但不替代“经脱敏目标 runtime 副本升级后启动”的发布演练，也不替代硬件验证。

下一步：在经脱敏目标 runtime 副本上重复迁移、升级 simulation 启动与回滚；现场条件满足后完成 ZMotion 只读和受控硬件签核。
