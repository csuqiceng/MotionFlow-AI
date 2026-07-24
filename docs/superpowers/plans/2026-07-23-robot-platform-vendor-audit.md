# 机械手平台厂商耦合审计（阶段 2）

日期：2026-07-23
范围：`nanobot-main-1/robot_ai/`
结论：当前平台可拆出，但尚不能把 ZMotion、六轴与当前工艺坐标当作通用默认值。

## 发现与处置边界

| 耦合点 | 当前位置 | 风险 | 平台化处置 |
|---|---|---|---|
| ZMotion SDK、DLL、网络 host | `backends/zmotion_*`、`zmotion_operator_control.py` | 新厂商必须触碰业务/安全代码 | 收敛为 `backends/<vendor>` 的控制器能力；SDK 路径仅留在 vendor 配置。 |
| Modbus 状态读取、寄存器及取消 latch | `backends/zmotion_backend.py`、`zmotion_operator_control.py` | 将 ZMotion 状态字误当通用状态 | 定义标准 `RobotState` 与 backend capability；寄存器映射留在 ZMotion 实现。 |
| 功能号 `108` 及 v1 功能号映射 | `library/catalog.py`、`safety/sandbox.py`、`zmotion_write_plan.py` | LLM/流程语义与某控制器指令号绑定 | 将功能号迁入 ZMotion command mapper；平台只使用 `linear_move`、`io_write`、`system_action` 等语义动作。 |
| 固定六轴 `x,y,z,rx,ry,rz` | `models.py`、`positions/registry.py`、`safety/checker.py`、`zmotion_operator_control.py` | 非六轴或不同关节/笛卡尔模型不可接入 | 引入 `RobotModel` 配置（轴集合、单位、坐标系、姿态表示）；六轴为当前 ZMotion 型号 profile，而非平台常量。 |
| 工艺工作区 `r/z`、首次测试限值 | `zmotion_operator_control.py` | 特定工装/半径假设泄漏至通用控制 | 迁入型号 profile 的 workspace 与 commissioning limits；安全策略通过接口读取限位。 |
| 速度/加速度百分比、线性路径 | `zmotion_operator_control.py`、`zmotion_write_plan.py` | 并非所有控制器支持相同运动原语 | backend 声明 `motion_capabilities`；不支持的原语在规划阶段明确拒绝。 |
| 急停、复位、暂停等系统动作 | `zmotion_operator_control.py`、`robot_routes.py` | 供应商动作语义不同，且不能削弱安全闸 | 保留平台 `emergency_stop` 用例；backend 实现具体命令，平台统一确认、授权与审计。 |
| `~/.nanobot/robot_ai` 数据目录 | 原路径 helper 与库/流程注册表 | 产品数据随宿主框架命名耦合 | 阶段 2 已改为由宿主注入数据目录；保留旧目录作为迁移读取来源。 |

## 当前安全不变量

- 真实控制器写入仍默认关闭；未注入有效执行模式时回退 `dry_run_only`。
- WebUI 实际执行仍必须同时经过 pending plan、确认码、会话 gate 与密码 gate。
- `emergency_stop`、`release_emergency_stop`、报警复位等系统动作仍走同一审计/授权路径；不得由 AI 工具绕过。
- 厂商迁移不改变审计日志、流程/命令库和位置库的数据完整性。

## 阶段 2 后续实现顺序

1. 增加平台级 `RobotModel`、`ControllerCapabilities` 和用例接口。
2. 将 ZMotion 功能号、六轴坐标/单位、`r/z` 工艺区间迁入 `backends/zmotion` profile。
3. 让 `nanobot/agent/tools/robot_*.py` 仅调用平台用例，不直接构造厂商请求。
4. 对模拟 backend、ZMotion 只读诊断和写入安全门分别加契约测试。
