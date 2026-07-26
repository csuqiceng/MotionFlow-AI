# 可配置机器人 AI 平台实施说明

日期：2026-07-26
适用分支：`codex/modular-migration`

## 1. 要实现的产品能力

系统最终不是只服务一台 ZMotion 机械手，而是一个可配置的平台：

- 可接入不同厂商、不同通讯方式的机械手；例如 ZMotion、Modbus TCP、串口、ROS2、厂商 HTTP API。
- 可在工程师设置中选择机器人驱动、连接参数和安全策略。
- 可安装、启用、禁用并配置不同 Tool；Tool 根据机械手能力决定是否可用。
- 可由部署管理员在底层配置不同 AI Provider、模型、地址和凭证；不同 AI 共用相同的 Tool、安全闸门与审计链路，UI 不提供 AI 配置或切换入口。
- WebUI、Electron 和 `robot_server` 通过稳定协议组合成不同产品，而不是为每个项目重写控制系统。

## 2. 当前实现到什么程度

当前分支已完成“逻辑模块化”，可以作为平台底座，但尚未完成“可独立安装的插件生态”。

| 已有能力 | 当前位置 | 结论 |
|---|---|---|
| 机器人通用后端接口 | `robot_platform/backends/contracts.py::RobotBackend` | 已有基础：模型、能力、读状态、点动、回零、停止。 |
| 后端注册与按需装配 | `robot_platform/backends/registry.py`、`product_wiring.py` | 已有 registry；ZMotion 已延迟加载。 |
| 仿真和 ZMotion | `simulation_backend.py`、`zmotion_plugin.py` | 仿真可不加载 ZMotion 运行。 |
| Agent 引擎接口 | `ai_runtime/engine_contract.py::AgentEngine` | 已抽出生命周期、会话、事件和连通性检查。 |
| Tool 接口 | `ai_runtime/tool_contracts.py::Tool` | 已有 SDK 无关的输入、上下文和结构化结果。 |
| WebUI 通讯层 | `webui/src/transport/` | HTTP、WS 和业务 transport 已从页面兼容层拆出。 |
| Electron 产品配置 | `desktop/electron/product-manifest.ts` | 已抽出名称、运行目录、服务端启动命令等产品参数。 |

当前仍存在的边界：

- ZMotion 是可选实现，但仍在 `robot_platform` 同一 Python 包内，不是独立安装插件。
- Tool 已有统一执行接口，但没有 Tool manifest、能力匹配、启用开关和权限声明。
- `AgentEngine` 是引擎契约，不等于多 AI Provider 管理；模型/Provider 仍需要单独的配置与适配层。
- Electron 仍固定使用 `motionFlowManifest()`，尚未支持读取多个产品 profile。
- 协议尚未对外正式版本化；未来替换 WebUI、服务端或插件时缺少兼容协商。

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

- 将 backend 扩展为完整动作集合，避免系统动作绕开后端。
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

## 7. 不做的事

- 不把厂商 SDK 暴露给 WebUI、AI 或 Tool。
- 不允许 AI 自行加载任意 Python Tool 或读取任意本地密钥。
- 不在没有第二个使用方时强行拆独立包。
- 不以 simulation 测试通过代替真实机械手的安全认证。
