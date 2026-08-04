# PyBullet 多机械臂数字孪生实施设计

## 目标

新增可配置的 PyBullet 仿真后端，并在模型和打包条件满足后取代当前仅维护
内存坐标的 `simulation` 默认用途，使同一套位置库和流程可以对多个六轴机械臂模型进行离线运行、关节
限位检查和碰撞预检。此能力用于开发、演示和执行前风险提示；它不控制真实
机械臂。

## 不变的安全边界

1. 真实写入只允许经现有 ZMotion 组合根、身份权限、参数校验、安全预检、
   操作员双确认与一次性执行许可链路完成。
2. PyBullet 模式的 `ControllerCapabilities.supports_real_writes` 永远为 `false`。
   仿真通过不产生或消费真机 permit，也不可以提升真机流程为已确认。
3. ZMotion 真实反馈可以在未来镜像到仿真画面，但 PyBullet 不得持有 ZMotion
   SDK、控制器地址、写入凭据或任何真机写入端口。
4. 未安装 PyBullet、模型无效、IK 无解、越关节限位、发生碰撞或模型资源越界
   时必须失败关闭，并带稳定错误码；不得静默退回为“仿真成功”。

## 组件与依赖方向

```text
robot_platform/simulation/catalog.py       模型发现、严格 manifest 校验
robot_platform/simulation/engine.py        仿真端口和稳定结果 DTO
robot_platform/simulation/pybullet_engine.py  PyBullet DIRECT 实现
robot_platform/backends/simulation_backend.py  旧 Backend Contract 适配器
robot_platform/backends/simulation_plugin.py   插件注册和配置声明
robot_platform/backends/wiring.py          组合根仅按 selected mode 调度

WebUI / AI / Flow / Application
          -> RobotOperationRequest -> Backend adapter -> SimulationEngine
ZMotion adapter 与 SimulationEngine 互不导入。
```

`catalog` 不导入 PyBullet；`engine` 只定义协议和纯数据；只有
`pybullet_engine` 允许导入可选依赖 `pybullet`。这样模型校验可在没有图形或
PyBullet 的开发机和打包检查中独立测试。

## 模型包约定

每个机械臂模型位于 `robot_platform/simulation/models/<robot-id>/`：

```text
manifest.json      robot_id、URDF 相对路径、六个关节名、关节限位、工具帧
robot.urdf         机械臂运动学、可视与碰撞几何
meshes/            可选 visual/collision 网格
scene.json         可选的静态工作台、围栏、夹具及禁区
```

manifest 必须：

- `robot_id` 仅使用小写字母、数字、`-`、`_`；
- 只允许指向模型包内的相对文件，拒绝绝对路径、`..` 和符号链接逃逸；
- 精确列出六个可动关节，且关节名不重复；
- 以度记录可配置的下/上限，且下限小于上限；
- 通过 `base_to_world`、`tool_link`、joint direction/offset 处理不同厂商的
  坐标与零位，不把标定散落到流程或 UI。

第一版随产品提供一个 `generic-six-axis` 示例模型，仅用于软件演示和回归。
它绝不能代表现场真实机械臂，部署必须安装该设备经过校准的模型包。

第一版的 `scene.json` 只允许静态长方体障碍物，格式为
`{"obstacles":[{"size_mm":[x,y,z],"pose_mm_deg":[x,y,z,rx,ry,rz]}]}`。
坐标相对于模型基座；引擎会应用 `base_to_world_mm_deg` 后才创建碰撞体。最多
64 个障碍物，任何多余字段、非有限数、非正尺寸或非法 JSON 都会使模型加载失败。

## 仿真执行语义

1. PyBullet 始终以 `DIRECT`（无 GUI）创建独立物理客户端，固定步长运行。
2. `linear_move` 将位置库的毫米/度目标转换到模型基座坐标，先做 IK，再检查
   每个候选关节、关节限位、自碰撞和环境碰撞。
3. 验证通过后按关节插值采样执行；任一采样点碰撞或越限立即返回失败。
4. `delay` 在仿真时间上推进；`stop` 中止当前仿真路径并使状态为 `stopped`。
   IO 和真实急停按钮不伪造真机效果，而是返回明确的 simulation 状态。
5. 返回值包含 model ID、目标关节、末端位姿和稳定错误码；不包含 PyBullet
   对象 ID、绝对路径或控制器信息。

## 后端选择与兼容

- 本切片以受控的 `ROBOT_SIMULATION_ENGINE=pybullet` 激活，避免将尚未安装 native 依赖的
  既有 `simulation` 部署错误地标为仿真成功；后续发布在支持运行时后再迁移
  `simulation` / `sim` 到该实现。真机产品 profile 的固定 `zmotion_readonly`
  内部标识不变。
- `ROBOT_SIMULATION_MODEL_ID` 选择模型，默认 `generic-six-axis`；仅在
  `ROBOT_SIMULATION_ENGINE=pybullet` 时生效。它只影响显式构造的
  controller-free simulation graph，不修改生产真机 profile。
- `RobotBackendConfig` 只携带模型 ID 等非敏感仿真配置。模型目录由代码常量
  或受控部署目录决定，不能由 API、AI 对话或流程参数指定。
- PyBullet 是 `simulation` 的 optional dependency。开发与桌面打包安装
  `simulation` extra；生产真机部署不因它缺失而无法连接 ZMotion。

## 验收标准

1. catalog 对合法模型、未知模型、路径逃逸、六关节缺失和非法限位有单测。
2. engine 以临时合法 URDF 在 `DIRECT` 模式运行，能返回六个关节状态、成功
   执行安全目标，并拒绝越限与碰撞目标。
3. simulation backend 仍满足现有 Backend Contract 与系统动作/IO 契约；其
   仿真执行没有真机写入能力。
4. ZMotion 组合根不导入 PyBullet；PyBullet 组合根不导入 ZMotion SDK。
5. 打包检查覆盖 optional 依赖和模型资产；未安装依赖时失败信息明确。
6. 现有权限、确认、permit、执行恢复和 Tool operation 相关回归全部通过。
7. 由独立 Agent 审查实现、依赖方向、打包和安全回归；若有阻塞问题则修复后
   新建独立 Agent 重新评审，直至批准。

## 分阶段交付

本次实现覆盖模型 catalog、默认模型、DIRECT 引擎、`pybullet` Backend
适配和定向回归。三维 WebUI 展示、现场环境资产编辑器、真实反馈镜像以及
将历史 `simulation` mode 迁移为 PyBullet 属于后续
独立切片；它们必须复用本设计中的 catalog/engine DTO，不能重新实现运动学或
越过 Application/Backend 边界。
