# 模块化迁移：兼容性基线与 Backend Contract 设计

## 背景

MotionFlow 需要在不破坏现有桌面产品的前提下，将 WebUI、Electron、Agent、Robot Tool、机器人应用逻辑和厂商通讯适配器逐步分离。当前 `robot_platform` 的 `platform.py`、`bridge.py`、`flow/executor.py`、包导出和 backend factory 直接了解 ZMotion；这使新增厂商、替换仿真实现和独立测试都存在高风险。

本设计只批准第一条垂直迁移线：建立兼容性门禁，并提取厂商无关的 Backend Contract 和显式装配机制。它不迁移 ZMotion 代码、不修改 WebUI 页面、不重写 AgentLoop。

## 目标

1. 将迁移风险转化为可重复执行的安全、协议、页面和打包门禁。
2. 定义由 Simulation 与 ZMotion 共同验证的最小 Backend Contract。
3. 使 backend 选择可通过显式 registry 和构造注入完成，而非在核心 factory 中硬编码厂商实现。
4. 保持现有 `create_robot_backend()` 调用方、外部 API、WebUI 事件和桌面启动路径兼容。

## 非目标

- 本阶段不使用 Python entry points 或发布独立 PyPI 包。
- 本阶段不把 ZMotion SDK/DLL、读写计划或诊断文件移出当前目录。
- 本阶段不改任何 WebUI 页面布局、路由或交互文案。
- 本阶段不拆分 `AgentLoop`，不变更 LLM provider、cron、session 或 memory 行为。
- 本阶段不连接真实硬件做自动化 CI；真实设备只在受控人工窗口验证。

## 设计决策

### 1. 先用显式 registry，不使用动态插件发现

`BackendRegistry` 以 backend 名称注册一个 factory。`robot_server` 的运行时装配模块注册产品可用的 Simulation 和 ZMotion factory；`create_robot_backend()` 保留兼容入口，但转发至 registry。

这样能在保留当前部署路径的同时解除 factory 对具体厂商实现的硬编码。动态 `entry_points` 延后到至少有第二个外部 backend 包、PyInstaller 收集策略和版本兼容策略后。

### 2. Contract 使用厂商无关命令与能力模型

核心接口包含：读取状态、声明能力、生成 dry-run 计划、带授权执行计划和急停。`RobotCommand`、`MotionPlan`、`ExecutionAuthorization` 和 `RobotCapabilities` 不能包含 ZMotion VR、DLL、func_id、SDK 类或厂商异常。

ZMotion adapter 未来负责将这些模型转换为 ZMotion SDK 操作；Simulation adapter 是默认测试参考实现。安全策略与确认票据的判定留在 Robot Application，而不是由 UI、Tool 或 backend factory 负责。

### 3. 兼容性门禁先于运行逻辑改变

迁移前固定如下行为：HTTP 路径/响应、WebSocket frame、Robot Tool schema 与结果、关键 WebUI 旅程、机械手安全负向行为、桌面打包和数据恢复。每阶段结束必须重新运行相关门禁；失败不得继续下一阶段。

## 数据流

```text
HTTP / WebSocket / Tool
          ↓
Robot Application（现有 Platform façade 保持兼容）
          ↓
Backend Contract
          ↓
BackendRegistry（由 robot_server 装配）
          ↓
Simulation 或 ZMotion adapter
```

现有 `RobotPlatform` 的公开方法暂不删除。它将逐步成为兼容 façade，使服务端、Tool 和测试可以在接口稳定后分批切换。

## 验收标准

### 必须自动通过

- `tests/robot_ai` 中 execution gate、pending plan、ZMotion SDK 写入保护与平台 use case 测试。
- WebSocket frame fixture 与既有 WebUI stream reducer 测试。
- WebUI Vitest 与生产构建。
- Electron TypeScript 构建、release 验证和 packaged robot-server smoke test。
- Simulation 与 fake ZMotion adapter 针对同一 Backend Contract 的测试。

### 必须人工确认

- 受控环境下的 ZMotion 只读状态检查。
- 受控环境下的 dry-run。
- 获批准的最小真实动作，且急停可达、操作者在场。
- 登录、会话、主控制台、机器人操作、设置、工程师工作台、资产库、用户与自动化的页面验收。
- 脱敏数据副本的启动、读取、回滚演练。

## 风险与控制

| 风险 | 控制 |
|---|---|
| Backend Contract 只适配 ZMotion | 由 Simulation 和 fake ZMotion 共同执行契约测试 |
| 重构绕过真实执行确认 | 先写负向执行门禁；每阶段运行 execution gate 和 SDK write guard |
| WebSocket 事件微小变化导致 UI 损坏 | 固定 RuntimeEvent 到 WebUI frame fixture，并由前端 reducer 消费 |
| PyInstaller 无法发现未来插件 | 第一阶段不用动态发现；打包 smoke 是每阶段门禁 |
| 数据丢失或路径变化 | 不做数据格式迁移；每阶段使用数据副本和回滚演练 |
| 架构重构影响页面 | 页面组件不改；新增端到端关键旅程作为迁移门禁 |

## 继续条件

只有在兼容性基线和 Backend Contract 门禁均通过后，才批准下一设计：将 ZMotion 从 `platform.py`、`bridge.py` 和 flow 执行路径中迁出。任何基线失败都先修复或明确记录为迁移前问题，不能带入下一阶段。
