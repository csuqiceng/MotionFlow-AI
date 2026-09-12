# ROSA 经验与 MotionFlow 模块化路线图

## 1. 目标

MotionFlow 的目标不是只控制当前的 ZMotion 机械手，而是形成一个可复用的机器人应用平台：

- 可替换 AI Agent；
- 可添加、禁用和移植 Tool；
- 可接入不同机械手、控制器和通信协议；
- 保持 WebUI、Electron、登录和安全流程稳定；
- AI Provider、密钥、模型、控制器 SDK 路径等部署配置不暴露给普通用户。

最终新增一个机械手时，应主要新增一个 Backend 插件、一份机器人 Profile，必要时再新增专属 Tool；不应修改 WebUI、聊天协议或 Agent 主循环。

## 2. ROSA 可借鉴的经验

[ROSA](https://github.com/nasa-jpl/rosa) 是面向 ROS1/ROS2 的自然语言机器人 Agent。它不是控制器协议框架，因此不应替换 MotionFlow 的下位机后端；但以下设计值得借鉴。

| 经验 | MotionFlow 的落地方式 |
| --- | --- |
| Tool 可组合 | 每个 Tool 声明 ID、版本、所需能力、允许角色和风险等级。 |
| Tool 可禁用 | 根据用户角色、机器人能力和部署 Profile 决定 Tool 是否可用，不把权限交给模型判断。 |
| 机器人专属上下文 | 每台机械手使用底层 `robot-profile` 描述型号、协议、限制、可用 Tool 和安全策略。 |
| 先探测再行动 | Agent 请求动作前读取真实连接、报警、急停、暂停、Ready 和能力状态。 |
| 流式可观测性 | 统一输出 Tool 开始、进度、成功、失败、状态变更和最终回复。 |
| Agent 可替换 | 通过 `AgentEngine` 接口保留 Nanobot；以后可新增 LangChain 等实现，而不影响下层。 |

ROSA 把黑名单和 Tool 包作为 Agent 的可配置部分，这一点可用于 MotionFlow 的 Tool Runtime。ROSA 还要求先查询真实 ROS 状态再执行动作；在 MotionFlow 中应把这一原则升级为后端强制校验。

> 重要：ROSA 的一部分约束来自 Prompt。Prompt 只能辅助 Agent，不能作为真机安全措施。急停、限位、报警复位、速度限制、角色权限和真实写入授权必须由后端代码强制保证。

## 3. 目标架构

```text
WebUI / Electron
        |
Robot Server
  - 登录、角色、HTTP/WS、审计
        |
Robot Application API
  - 检查 -> 校验 -> 执行 -> 回读 -> 记录
        |
Tool Runtime
  - Tool 注册、角色/能力/风险过滤
        |
AgentEngine
  - Nanobot（当前）/ 未来可选实现
        |
RobotBackend
  - probe(host)
  - get_status()
  - capabilities()
  - system_action()
  - execute_motion()
        |
ZMotion / Modbus / ROS2 / ABB / KUKA / Simulation
```

依赖方向只能向下：UI 不得依赖协议；Agent 和 Tool 不得直接写寄存器；`robot_platform` 不得依赖 UI、`robot_server` 或 Agent。

## 4. 运行模式与权限

| 模式 | 用途 | 下位机写入 |
| --- | --- | --- |
| `simulation` | 开发、演示、自动化测试 | 不写真实控制器 |
| `diagnostic` | 检测连接和读取状态 | 只读 |
| `production_control` | 已验收的现场真机控制 | 允许，仍需安全门和审计 |

普通用户只能操作已允许的 Tool 并查看状态。工程师负责下位机检测、选择已部署的机器人 Profile 和诊断。AI Provider、模型、密钥、SDK 路径和安全上限只存在于部署配置，不出现在普通用户 UI。

## 5. 统一安全动作状态机

所有动作走以下闭环：

```text
请求 -> 连接检测 -> 状态读取 -> 能力/角色/安全校验
     -> 协议执行 -> 控制器状态回读 -> Tip/事件/审计
```

急停拥有最高优先级，应有独立、最短的安全通道；不得依赖 AI、普通任务队列或复杂页面状态。解除急停、报警复位、继续和解除取消必须按控制器真实状态验证。

| 动作 | 期望控制器结果 |
| --- | --- |
| 急停 | 急停状态位已置位 |
| 解除急停 | 只解除主机侧急停请求，不代表自动恢复 |
| 报警复位 | 报警已清除，且控制器 `Ready` 已恢复 |
| 暂停 | 暂停位已置位 |
| 继续 | 暂停位已清除 |
| 停止当前 | 取消位已置位 |
| 解除取消 | 取消位已清除 |

## 6. 当前实现完成度

以下为架构评估，不代表真机现场验收已经完成。

| 能力 | 当前状态 | 估计完成度 |
| --- | --- | ---: |
| WebUI / Electron / Server 分层 | 已具备清晰边界 | 80% |
| Tool 注册与角色/能力过滤 | 已有 Registry 和 Manifest 基础 | 70% |
| Tool 外部插件化和独立发布 | 尚未形成即插即用机制 | 35% |
| Agent 可替换 | 有 `ai_runtime` 边界，核心仍偏整体 | 55% |
| 机器人 Profile | 有产品/环境配置，缺完整机器人 Profile | 40% |
| 多协议 Backend | 已有仿真和 ZMotion 骨架 | 50% |
| 下位机能力协商 | 有 `ControllerCapabilities` 基础 | 45% |
| 六个安全动作协议映射 | 基本与旧版 Func104 对齐 | 80% |
| 安全动作状态回读 | 已有基础；报警复位 Ready 校验需补齐 | 60% |
| Tool 流式过程事件 | 已有聊天/工具事件基础 | 70% |
| 真机操作完整审计链 | 有身份和部分审计，尚未全链统一 | 45% |
| AI 配置不暴露给普通用户 | 基本实现 | 85% |

总体：架构骨架约 65%；真机安全控制闭环约 60%；多协议、可插拔机械手平台约 45% 到 50%。

## 7. 实施顺序

1. **安全等价**：下位机检测必须检测页面指定的地址；报警复位必须验证 `alarm=0 && ready=1`；为六个安全动作建立协议与状态回归测试。
2. **后端收口**：把探测、状态、安全动作和运动执行收进统一 `RobotBackend` 接口，消除绕过后端能力声明的写入路径。
3. **机器人 Profile**：加入每台机械手的协议、能力、限制、允许 Tool 和安全策略配置。
4. **Tool Runtime**：完善 Tool Manifest、能力协商、角色控制、风险级别和审计。
5. **Agent Engine**：把 Nanobot 继续收敛到 `AgentEngine` 契约；LangChain 仅作为未来可选实现，不进行整体迁移。
6. **物理拆包**：只有边界稳定、测试覆盖后，再考虑发布独立 Python 包或拆仓库。

## 8. 验收标准

项目达到目标的标志是：

1. 替换 ZMotion 为 Modbus Backend 时，WebUI、Electron、登录、聊天协议和 Agent 主循环无需改动。
2. 新 Backend 只需实现统一接口并声明能力；Tool 自动按能力启用或禁用。
3. 所有真机动作均有操作 ID、用户、Tool、控制器、请求、协议结果、状态回读和时间戳。
4. 仿真、诊断、真机控制三种模式行为明确，且默认不会误写真机。
5. 急停、解除急停、报警复位、暂停、继续、停止当前、解除取消均通过协议回归测试和现场真机验收。
