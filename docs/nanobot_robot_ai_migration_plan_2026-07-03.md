# nanobot 工厂机械手语音 AI 迁移分析与实施计划

> 日期：2026-07-03  
> 状态：GitHub 直连克隆失败，本文档先记录已验证阻塞、旧 Qt 需求映射、目标架构和待 nanobot 源码落地后的最小闭环计划。  
> 边界：旧 Qt 项目仅作为需求参考，禁止修改旧 Qt 项目文件。

## 1. 当前执行结果

- 目标独立目录：`C:\Users\KY\Desktop\nanobot_robot_ai`
- 已创建：`docs/`
- 未完成：`git clone https://github.com/csuqiceng/nanobot`
- 失败原因：本机无法连接 `github.com:443`
- 已尝试：
  - `git clone https://github.com/csuqiceng/nanobot ...`
  - `git clone --depth 1 https://github.com/csuqiceng/nanobot ...`
  - `git -c http.version=HTTP/1.1 ... clone --depth 1 ...`
  - `curl.exe -L https://github.com/csuqiceng/nanobot/archive/refs/heads/main.zip ...`
  - `Test-NetConnection github.com -Port 443`
- 验证结论：`TcpTestSucceeded=False`，当前网络环境无法直连 GitHub。

## 2. nanobot 当前架构：待源码复核

由于 GitHub 不可达，尚未能读取 nanobot 仓库的 `README.md`、`工厂机械手语音AI-改造方案与计划.md`、核心代码、WebUI、SDK、Tool、STT 文件。

根据用户目标描述，迁移前必须重点复核 nanobot 的这些能力边界：

- Agent：是否已有会话编排、工具调用、LLM provider 抽象、system prompt 和 tool result 消费逻辑。
- Tool：是否支持 Python 侧注册工具、schema 描述、同步/异步调用、错误结构和权限边界。
- Memory：是否已有短期会话、长期记忆、向量/SQLite/文件存储，以及可审核的 memory 写入接口。
- WebUI：是否可以静态构建后由 pywebview 直接加载，是否依赖 gateway 端口。
- SDK：是否提供从 Python 直接调用 Agent/Tool/Memory 的 API，避免通过 HTTP gateway。
- STT/TTS：是否已有云端语音接入点，或仅有 Web 端浏览器语音能力。

源码落地后，本节必须替换为基于真实文件路径的架构说明。

## 3. 旧 Qt 项目可参考能力

旧 Qt 项目的需求和能力只能作为参考，不迁移原代码。

可参考能力：

- 语音入口：讯飞 IAT、本地麦克风采集、录音耗时日志、代理转写模式。
- 自然语言链路：AgentOrchestrator、CommandUnderstandingAgent、ParameterCompletionAgent、SafetyReviewAgent、ConfirmationAgent。
- 工具化原则：ToolResult 统一返回 `ok/state/message/data/errors`。
- 安全策略：唤醒词、权限、参数完整性、边界检查、安全预检、pending confirm、确认消费、执行门禁。
- 状态查询：位置、轴状态、报警、dashboard 查询。
- 流程能力：流程草案、流程命名、追加步骤、登记流程、复合指令。
- 模拟控制器：本地 mock controller 支持状态位、回显、确认和回归测试。
- 打包经验：Windows EXE、资源目录、环境变量密钥、日志目录。

不可直接复用：

- Qt GUI 代码。
- 旧 Modbus/ZMotion 写控制器实现。
- 旧项目内部多路 fallback 主链路。
- 任何会让 LLM 直接声明“已执行/已保存/已创建”的回复路径。

## 4. 迁移目标架构

目标是一个基于 nanobot 的工厂机械手语音 AI 桌面 EXE。

```text
pywebview Desktop EXE
  -> local HTML/JS WebUI
  -> Python Api bridge
  -> nanobot Agent SDK
  -> nanobot Tool registry
  -> robot tools
       -> SimulationRobotBackend
       -> SafetyPolicy
       -> ToolResult
  -> Agent final answer
  -> WebUI chat/status rendering
```

核心原则：

- pywebview 加载本地 WebUI，不开放 gateway 端口。
- WebUI 不直接调用控制器，只调用 Python Api bridge。
- Agent 负责理解、追问和选择 tool。
- Tool 负责产生事实、执行模拟动作或拒绝。
- LLM 只能基于 tool result 回复用户。
- 真实下位机接口未提供前，全部走模拟 backend。
- 安全限位和拒绝原因先放在 tool 层。
- 后续真实 Modbus/串口接入必须经过同一 SafetyPolicy 和 ExecutionGate。

## 5. 可直接复用与必须新建

可直接复用 nanobot 的部分，待源码确认：

- Agent 编排与 tool calling。
- Tool schema/registry。
- Memory 基础设施。
- WebUI 基础组件或静态构建产物。
- LLM provider 配置。
- STT/TTS provider 抽象。

必须新建：

- `desktop/`：pywebview 桌面入口。
- `robot_ai/bridge.py`：Python Api bridge，供 JS 调用。
- `robot_ai/tools/robot_tools.py`：机械手工具注册。
- `robot_ai/backends/simulation_backend.py`：模拟机械手 backend。
- `robot_ai/safety/policy.py`：限位、模式、拒绝原因。
- `robot_ai/models.py`：ToolResult、RobotState、MotionCommand 等数据模型。
- `webui/robot/` 或 nanobot 既有 WebUI 扩展页：按钮、状态、对话最小 UI。
- `tests/robot_ai/`：tool、backend、bridge、Agent 调 tool 的最小测试。
- `.env.example`：云端 LLM/STT/TTS 配置模板。
- `docs/`：架构、实施、测试和真实下位机 TODO。

## 6. 与旧 Qt 能力对应关系

| 旧 Qt 能力 | nanobot 新项目对应 |
|---|---|
| Qt 主窗口 | pywebview + WebUI |
| 语音按钮/输入框 | WebUI 语音/文本输入 + Python bridge |
| DeepSeek/LLM chat | nanobot Agent + 云端 LLM |
| AgentOrchestrator | nanobot Agent 主链路 |
| agent_tools ToolResult 设想 | nanobot Tool 返回统一结构 |
| SafetyReviewAgent/ConfirmationAgent | SafetyPolicy + pending confirm tools |
| Modbus/ZMotion 真实执行 | 暂不接入，先 SimulationRobotBackend |
| mock controller | simulation backend |
| data 配置和日志 | nanobot Memory + 本地 logs/config |
| PyInstaller 打包 | pywebview EXE 打包 |

## 7. 风险与阻塞项

当前阻塞：

- GitHub 直连失败，nanobot 源码未能克隆和读取。
- 因源码不可用，无法确认 nanobot 的真实目录结构、启动方式、SDK API、WebUI 构建链、Tool 注册方式、STT/TTS 接口。

技术风险：

- nanobot 如果强依赖 gateway HTTP 服务，会与“零端口 pywebview”目标冲突，需要改为 SDK 直连或本地进程内调用。
- WebUI 如果强绑定远端 API 路径，需要增加 pywebview bridge adapter。
- Agent tool result 如果不是强结构化，需要加 robot tool adapter，避免 LLM 自行生成事实。
- STT/TTS 如果只在浏览器端实现，桌面 EXE 需要额外处理麦克风、云端鉴权和音频播放。
- Windows EXE 打包可能涉及 pywebview runtime、WebView2、密钥配置、模型/资源路径。
- 真实控制器安全过滤接口未提供，必须只保留 TODO 和模拟结果，不能提前写真实协议。

需求冲突检查：

- 若 nanobot 只能通过 gateway 暴露 WebUI，则与零端口桌面目标冲突。
- 若 nanobot 的 Agent 无法在进程内调用 Tool，则需要新增本地 adapter。
- 若 nanobot WebUI 无法静态化，则 pywebview 方案需要重构 WebUI 加载方式。
- 若 nanobot STT/TTS 固定某一 provider，而项目需要云端可替换 provider，则需抽象 provider 配置。

## 8. 最小闭环实施计划

### Task 1：源码落地与架构复核

- 克隆 nanobot 到 `C:\Users\KY\Desktop\nanobot_robot_ai`。
- 阅读并记录：
  - `README.md`
  - `工厂机械手语音AI-改造方案与计划.md`
  - Agent 核心文件
  - Tool 注册/调用文件
  - Memory 文件
  - WebUI 文件
  - SDK 文件
  - STT/TTS 文件
- 输出真实文件路径级架构说明。
- 如果 gateway/SDK/WebUI 与目标冲突，先写冲突说明，不改代码。

验证：

```powershell
git -C C:\Users\KY\Desktop\nanobot_robot_ai status
rg -n "Agent|Tool|Memory|WebUI|STT|TTS|gateway|sdk" C:\Users\KY\Desktop\nanobot_robot_ai
```

### Task 2：pywebview 桌面入口

- 新建桌面入口，只加载本地 WebUI。
- 不启动 gateway 端口。
- 暴露最小 Python API：`health()`、`send_message(text)`、`get_robot_state()`。

验证：

```powershell
python -m pytest tests/robot_ai/test_desktop_bridge.py -v
python path\to\desktop_entry.py
```

### Task 3：模拟机械手 backend

- 实现 `SimulationRobotBackend`。
- 初始状态：`idle`、六轴位置为 0、无报警、未连接真实设备。
- 支持查询状态、移动单轴、回零、停止。
- 超限返回拒绝，不改变状态。

验证：

```powershell
python -m pytest tests/robot_ai/test_simulation_backend.py -v
```

### Task 4：机械手 tool 层

- 注册工具：
  - `robot_get_status`
  - `robot_move_axis`
  - `robot_home`
  - `robot_stop`
  - `robot_explain_limits`
- 统一返回 `ok/state/message/data/errors`。
- 安全拒绝由 tool 返回，Agent 只能解释结果。

验证：

```powershell
python -m pytest tests/robot_ai/test_robot_tools.py -v
```

### Task 5：WebUI 最小交互

- 增加文本对话框。
- 增加状态刷新按钮。
- 增加模拟动作按钮：查询状态、X 轴 +10、回零、停止。
- 所有按钮走 Python bridge，不走 HTTP 端口。

验证：

```powershell
python path\to\desktop_entry.py
```

手工检查：

- 桌面窗口可打开。
- 查询状态有返回。
- 点击 X 轴 +10 后状态变化。
- 超限动作显示拒绝原因。

### Task 6：LLM 调 tool 演示

- 配置云端 LLM。
- 用户输入“把 X 轴向前移动 10 毫米”。
- Agent 选择 `robot_move_axis`。
- Tool 返回模拟执行结果。
- Agent 基于 tool result 回答。
- 用户输入超限动作时，Tool 拒绝，Agent 解释拒绝原因。

验证：

```powershell
python -m pytest tests/robot_ai/test_agent_tool_demo.py -v
```

手工检查：

- Agent 不直接承诺执行，只有 tool 成功后才说已模拟执行。
- Tool 拒绝时，回复包含拒绝原因和当前限位。

### Task 7：云端 STT/TTS 占位接入

- 增加 provider 配置模板。
- 先实现文本输入闭环。
- STT/TTS 如 nanobot 已有 provider，复用其接口。
- 如未提供，新增 TODO stub 和配置文档，不阻塞最小文本闭环。

验证：

```powershell
python -m pytest tests/robot_ai/test_voice_provider_config.py -v
```

## 9. 下次继续前置条件

必须先解决 GitHub 访问或提供 nanobot 源码包。

可选方式：

- 在本机配置可访问 GitHub 的网络代理后重试 clone。
- 提供 nanobot zip 包到桌面。
- 提供可信内部镜像地址。
- 允许使用指定的代码镜像服务，但需要先确认供应链风险。

在 nanobot 源码真实落地前，不进入代码实现。
