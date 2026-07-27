# 可配置机器人 AI 平台实施说明

日期：2026-07-27
适用分支：`codex/modular-migration`

## 1. 要实现的产品能力

系统最终不是只服务一台 ZMotion 机械手，而是一个可配置的平台：

- 可接入不同厂商、不同通讯方式的机械手；例如 ZMotion、Modbus TCP、串口、ROS2、厂商 HTTP API。
- 工程师可在受控页面选择已批准的机器人 backend，并启用或禁用已批准的 Tool；控制器地址、SDK 路径和安全策略仍只由部署配置管理。
- Tool 根据机械手能力、登录角色和产品启用集决定是否可用。
- 可由部署管理员在底层配置不同 AI Provider、模型、地址和凭证；不同 AI 共用相同的 Tool、安全闸门与审计链路，UI 不提供 AI 配置或切换入口。
- WebUI、Electron 和 `robot_server` 通过稳定协议组合成不同产品，而不是为每个项目重写控制系统。

## 2. 当前实现到什么程度

当前分支已完成“逻辑模块化”，可以作为平台底座，但尚未完成“可独立安装的插件生态”。

| 已有能力 | 当前位置 | 结论 |
|---|---|---|
| 机器人通用后端接口 | `robot_platform/backends/contracts.py::RobotBackend` | 已有基础：模型、能力、读状态、点动、回零、停止；公开 capability 为 vendor-neutral v1。 |
| 后端注册与按需装配 | `robot_platform/backends/registry.py`、`product_wiring.py` | 已有带 ID/版本的 plugin manifest；ZMotion 只在选择时延迟加载。 |
| 仿真和 ZMotion | `simulation_backend.py`、`zmotion_plugin.py` | 仿真可不加载 ZMotion 运行。 |
| 安全动作后端入口 | `RobotBackend.execute_system_action()`、`backends/wiring.py` | 急停、暂停、继续、取消和复位先进入当前 profile 选择的 backend，再由该 backend 调用厂商适配器；不再由 Web/API 旁路直接挑选 ZMotion。 |
| Agent 引擎接口 | `ai_runtime/engine_contract.py::AgentEngine` | 已抽出生命周期、会话、事件和连通性检查；当前 Nanobot 位于可替换 adapter 后。 |
| Tool 接口与资格筛选 | `ai_runtime/tool_contracts.py`、`ai_runtime/tool_manifest.py`、`robot_server/tool_registry.py` | SDK 无关 Tool contract 已有 manifest、能力/角色/启用状态筛选。 |
| 工程师产品配置 | `robot_server/product_profile.py`、`ProductProfileSettings.tsx` | 已可持久化批准的 backend 和 Tool 启用集；保存后重启使 backend 与新 AI runtime 同步生效。 |
| AI 部署配置 | `ai_runtime/provider_config.py`、`provider_contract.py` | Provider、模型、凭据引用只在底层加载；不在用户 API 或 UI 返回。 |
| WebUI 通讯层 | `webui/src/transport/` | HTTP、WS 和业务 transport 已从页面兼容层拆出。 |
| Electron 产品配置 | `desktop/electron/product-manifest.ts` | 已抽出名称、运行目录、服务端启动命令等产品参数。 |

当前仍存在的边界：

- ZMotion 是可选 plugin，但仍在 `robot_platform` 同一 Python 包内，不是独立安装插件。
- 产品 profile 目前只允许静态批准的 `simulation` / `zmotion_readonly` 和既有 Tool catalog；新协议或 Tool 必须先随代码和测试发布，不能由用户输入任意 Python 模块路径。
- 当前已有一个 `NanobotProvider`；新增第二种 Provider adapter、实际连通性策略和 fallback 仍待实施。
- Electron 仍固定使用 `motionFlowManifest()`，尚未支持读取多个产品 profile。
- WebUI bootstrap 与 capability 已采用 v1；完整插件/Tool 配置的对外兼容协商仍待扩充。
- 控制器地址、SDK 路径、AI 密钥和 endpoint 仍只能在部署配置管理，工程师页面不会显示或修改它们。

### 2.1 本轮补强：下位机探测与安全按钮回归

登录页的“检测连接”现在对输入的私网/回环 IP 创建**临时只读**后端并读取一次状态；它不修改当前运行中的控制器地址、不复用或重配运行中的共享 ZMotion 连接，也绝不写入下位机。页面返回值会携带实际检测的 `host`，避免把“当前配置的设备状态”误报成“输入 IP 的检测结果”。控制器地址、SDK 路径仍只能由部署配置修改并在重启后生效。

ZMotion Func104 的安全动作保持与旧 Qt 版本同一寄存器协议，并有回归测试保护：

| 动作 | VR2 急停 | VR4 暂停 | VR6 取消 | VR8 复位 | 完成判定 |
|---|---:|---:|---:|---:|---|
| 急停 | 1 | 0 | 0 | 0 | 急停位已置位 |
| 解除急停 | 2 | 0 | 0 | 0 | 仅主机急停请求解除；报警可能仍锁存 |
| 暂停 | 0 | 1 | 0 | 0 | 暂停位已置位 |
| 继续 | 0 | 2 | 0 | 0 | 暂停位已清除 |
| 停止当前 | 0 | 0 | 1 | 0 | 取消位已置位 |
| 解除取消 | 0 | 0 | 2 | 0 | 取消位已清除 |
| 报警复位 | 0 | 0 | 0 | 1 | **报警位已清除且 Ready 位已恢复** |

其中“报警复位”明确恢复旧版的双条件验收，不能因为报警位暂时清零就向页面报告成功。

## 3. 目标架构

```text
底层部署配置（不暴露给 UI）
  ├─ 机器人 profile：驱动、连接、能力、安全策略
  ├─ Tool profile：已安装、启用、权限、配置
  └─ AI runtime：Provider、模型、地址、密钥引用、默认策略
           ↓
robot_server（配置读取、鉴权、HTTP/WS、应用编排）
  ├─ AI Provider / Agent Engine
  ├─ Tool Registry
  └─ Robot Application API
           ↓
Robot Backend Registry → Simulation / ZMotion / ROS2 / Modbus / 其他插件
```

所有真实动作必须维持同一安全路径：

```text
人工按钮 或 AI Tool
        ↓
计划 / 能力校验 / 权限校验 / 确认码 / 审计
        ↓
Robot Application API
        ↓
选中的 Backend 插件
```

AI、WebUI 和 Electron 均不得直接调用厂商 SDK，也不得绕过急停、暂停、确认码和安全预检。

紧急动作的用户体验可以只显示 Tip，但后端仍要记录操作者、目标控制器、动作、写入结果和状态回读。急停本身必须保持独立可达；解除急停、解除取消和报警复位必须按控制器状态验收，不能把“请求已发出”当作“设备已恢复”。

## 4. 关键设计规则

### 4.1 机械手与协议：插件负责翻译，核心只认能力

每个机器人插件实现统一后端和诊断接口，声明 `ControllerCapabilities`。上层只能询问“是否支持”，不能根据 `backend == "zmotion"` 写分支。

建议能力至少包含：轴数、关节移动、笛卡尔移动、回零、急停、暂停/继续、报警复位、数字 IO、模拟 IO、流程执行和只读诊断。

新增 ROS2 或 Modbus 时，只新增插件与 profile，不修改 Agent、Tool、WebUI 的业务逻辑。

### 4.2 Tool：声明需求，而不是假定所有机械手都支持

每个 Tool 要有 manifest，至少声明：唯一 ID、版本、参数 schema、所需 capability、风险等级、允许角色和配置 schema。

例如“视觉抓取 Tool”可要求 `cartesian_motion`；若当前机械手不支持，UI 隐藏或禁用，Agent 也不会把它注册到可调用 Tool 列表。

Tool 的执行必须经 `RobotApplicationApi`；Tool 不直接读写 `robot_platform` 的存储、确认码或厂商实现。

### 4.3 AI：Provider 可替换，安全执行链不可替换

新增 `AiProvider` 层，用统一配置创建不同 `AgentEngine` 实现。Provider 可以是 OpenAI 兼容 API、DeepSeek、Qwen、私有 API 或本地模型。

Provider 只负责模型连接、流式事件和模型配置；它拿到的 Tool 列表由 Tool Registry 和用户权限共同决定。Provider、模型、地址和切换策略只由底层部署配置加载，UI 与用户 API 均不返回、编辑或选择这些字段。无论 AI 来自哪里，动作仍走相同安全 API。

### 4.4 产品配置：密钥不进入普通 JSON

AI runtime 配置只在服务端启动时从受控配置文件、环境变量和凭据库引用读取，不提供 WebUI 设置页或用户 API。API key、令牌和厂商密码应只保存为 OS 凭据库引用或环境变量引用，不写入 WebUI 响应、日志、导出文件或 Git。

## 5. 分阶段实施

### 阶段 A：冻结现有边界（先做）

- 扩充 `tests/architecture/test_dependency_rules.py`：禁止 `robot_platform` 反向导入上层，禁止页面直接调用 HTTP/WS，禁止厂商判断进入应用层。
- 为 HTTP/WS 增加 `protocol_version`，连接建立时返回支持的事件和功能。
- 为 `ControllerCapabilities` 和 Tool 结果建立 JSON fixture 兼容测试。
- 发布前持续跑 simulation、数据迁移 rehearsal、前端构建和 Electron 打包烟测。

完成标准：旧产品行为不变，所有现有安全操作在 simulation 下可回归，API 变更会被契约测试阻止。

### 阶段 B：机器人插件与能力协商

- 将 backend 从已完成的 `execute_system_action()` 继续扩展到完整运动/IO 动作集合，避免其他动作绕开后端。
- 新增 `RobotBackendPlugin` manifest：插件 ID、版本、factory、配置 schema、能力来源和诊断入口。
- 首先把现有 ZMotion 注册为该 manifest；simulation 作为参考实现。
- 将插件发现限定为产品配置显式允许的模块，不执行来自数据目录的任意 Python。
- 新增 ROS2 或 Modbus 插件时，以 simulation 契约测试复用为验收模板。

完成标准：删除或不安装 ZMotion 插件时，系统仍可用 simulation 启动；换插件只改 profile，不改服务端路由、WebUI 页面或 Agent Tool。

### 阶段 C：Tool Registry 与权限模型

- 新增 Tool manifest、Tool Registry 和启用状态持久化。
- 根据当前机器人 capability、登录角色、产品策略筛选可用 Tool。
- Tool 的参数 schema、风险级别和审计事件由 manifest 统一定义。
- 保留 `LegacyRobotToolAdapter`，以渐进方式迁移旧 Tool，禁止一次性删除兼容层。

完成标准：工程师可启用或禁用 Tool；不满足能力或权限条件的 Tool 不会暴露给 AI，也无法通过 API 直接执行。

### 阶段 D：多 AI Provider

- 新增 Provider contract 与配置解析；`NanobotEngine` 作为第一个 Provider adapter。
- 将 URL、模型、超时、流式能力、最大并发和密钥引用放入受控底层配置。
- 增加 Provider 连通性检查、失败提示和可选 fallback，不把 Provider 异常伪装成机器人错误。
- AI 切换只能由部署管理员修改底层配置，并且只能影响“理解和决策”，不能改变 Tool 权限、安全策略或执行审计。

完成标准：部署管理员修改受控配置后，可以切换至少两个 AI Provider；用户 UI 中没有 Provider、模型、URL、密钥或切换入口，且聊天历史、Tool 审计和安全行为保持一致。

### 阶段 E：WebUI 与 Electron 配置产品化

- WebUI 不新增 AI 配置页，也不返回 AI Provider、模型、URL 或密钥信息；机器人和 Tool 的工程师配置页只调用 versioned transport API。
- Electron 用 profile 选择产品 manifest、默认配置和可选 vendor 资源；保留当前 MotionFlow profile 作为默认值。
- 任何配置修改需校验、审计，并在必要时要求重启受影响服务。

完成标准：不改代码即可通过受控底层配置切换 simulation/ZMotion、启用 Tool、选择 AI；桌面端与浏览器端不显示 AI 配置，且看到一致的可用功能状态。

### 阶段 F：第二项目验证后才物理拆包

只有出现第二个真实项目、公开 API 已稳定、独立安装和 PyInstaller 收集已验证后，才提取：

- `robot-platform-core`
- `robot-backend-zmotion`、`robot-backend-ros2` 等可选插件
- `robot-tool-sdk` 与产品 Tool 包
- `agent-provider-*`
- 可选的 WebUI transport SDK

不要先拆 npm/PyPI 包再找使用场景；那会增加发布和兼容成本，未必降低耦合。

## 6. 验收矩阵

| 场景 | 必须结果 |
|---|---|
| 不安装 ZMotion | simulation、登录、WebUI、聊天、所有安全动作可用。 |
| 不同能力机械手 | 不支持的 Tool 和页面操作被禁用并说明原因。 |
| AI 切换 | 修改底层配置并重启/热加载后对话可用；UI 不显示 AI 配置；Tool 权限、确认码、审计、安全预检不改变。 |
| Tool 被禁用 | AI 不可见、API 不可执行、历史记录仍可查看。 |
| 通讯失败 | 明确显示 backend/Provider 连通性错误，不误报为执行成功。 |
| 数据升级 | 迁移 rehearsal 生成成功报告，原始运行时数据不被写入。 |
| 真实硬件 | 在受控工位逐项验证急停、暂停、继续、报警复位；simulation 通过不能替代现场认证。 |

### 6.1 下位机与安全按钮现场验收表

在受控工位、机械手工作区清空且实体急停可达的前提下，按以下顺序执行；每一步同时核对页面 Tip、HTTP 返回、控制器状态位和机械手实际状态：

1. 在登录页输入一个错误私网 IP，点击检测：必须明确显示未连接，且不得改变正在运行的控制器配置。
2. 输入已部署的控制器 IP，点击检测：返回 `host` 必须与输入值相同，且仅做状态读取。
3. 急停：确认 VR2=1、急停状态位置位、机械手停止。
4. 解除急停：确认 VR2=2，仅解除主机请求；机械手不得自动恢复运动。
5. 报警复位：确认 VR8=1，只有 alarm=0 且 Ready=1 时页面才可提示成功。
6. 暂停/继续：确认 VR4 依次为 1/2，暂停状态位正确置位/清除。
7. 停止当前/解除取消：确认 VR6 依次为 1/2，取消状态位正确置位/清除。

若任一步“接口成功”但状态位或实体行为不一致，立即停止后续验证，保留服务端审计与控制器日志，不得以页面成功提示作为放行依据。

### 6.2 位置、命令库和实时状态

桌面版首次启动和旧运行目录升级后，服务端状态、右侧状态栏与 Agent 都使用同一
`zmotion_readonly` 下位机连接配置；不再让右栏默认落到 simulation 而聊天读取真机。

- ZMotion 实时读数使用 VR1600–1605 的 J1–J6 关节反馈，以及 VR1612–1617 的末端位姿反馈。右栏以 `/api/robot/status` 为唯一来源轮询并展示两组数据；读失败时明确显示离线，不把 0 当作真机坐标。
- 项目原有 `home`、`休息姿态`、`位置A`、`位置B`、`位置C` 会从打包的旧项目命令表迁入位置注册表。已有运行目录只补不存在的名称，不覆盖工程师保存的坐标。
- 保存或更新一个命名位置会同步发布一条 Func108 `linear_move` 命令。因此位置仍是坐标的唯一来源，而命令库提供同一位置的可执行入口和审计版本。
- `tools.execution_mode=auto_after_safety_check` 是本产品的部署默认值。Agent 在每次调用时读取该运行时配置，不再把启动时的 `dry_run_only` 缓存为永久预览模式。真机动作会直接下发；但下位机未连接、控制器报警/急停、软限位或 L1 预检失败时仍返回错误且不写入控制器。

这些属于部署侧配置和运行行为，不向操作员 UI 暴露 AI Provider、模型或密钥。

## 7. 不做的事

- 不把厂商 SDK 暴露给 WebUI、AI 或 Tool。
- 不允许 AI 自行加载任意 Python Tool 或读取任意本地密钥。
- 不在没有第二个使用方时强行拆独立包。
- 不以 simulation 测试通过代替真实机械手的安全认证。
