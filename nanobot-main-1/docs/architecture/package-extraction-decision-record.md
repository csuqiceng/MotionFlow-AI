# ADR：暂不物理拆包

日期：2026-07-26

## 决策

继续保留模块化单仓；当前不发布独立 PyPI 或 npm 包。

## 依据

- Backend Contract 已有 simulation 与 ZMotion 两个实现，Robot Tool、AgentEngine、WebUI transport 和 Electron ProductManifest 已形成逻辑边界。
- 但 WebUI、Electron、Agent Core 和 Robot Tool 仍只有一个实际产品使用方；公开 API、版本策略和独立安装体验尚未经过第二项目验证。
- PyInstaller 仍需显式收集可选 ZMotion 插件。过早拆包会让安装、资源路径与安全兼容问题转移到发布阶段，而非降低耦合。
- 当前优先级是保持已发布简化 UI、机械手安全和数据恢复行为，而不是为目录拆分引入新的发布面。

## 重新评估条件

同时满足以下条件后才提取物理包：至少两个独立使用方或产品、稳定且版本化的公开 API、独立安装/测试、兼容策略、带可选依赖的 PyInstaller 收集验证，以及完整发布清单通过。

在此之前，新代码只能依赖 `ai_runtime`、`robot_platform` 或 `robot_server` 的公开边界；兼容 adapter 不得删除。

## 2026-07-26 复核

本次在 Product Profile、Tool manifest 和 AI Provider 边界落地后重新审计，结论仍为**暂不物理拆包**。

| 候选包 | 当前边界证据 | 物理提取判定 |
|---|---|---|
| `robot-platform-core` | `robot_platform` 不反向 import `ai_runtime`、`robot_server` 或 `nanobot`；核心 application 路径不直接 import ZMotion。 | 可作为未来第一个候选，但仍与现有 library/flow/position 数据模型共同演进，暂留单仓。 |
| `robot-backend-zmotion` | ZMotion 已通过 plugin manifest 和产品 wiring 惰性加载；simulation 能在独立进程不加载厂商模块。 | 可以提取，但必须先有独立 wheel、可选依赖、PyInstaller collect 与目标机 SDK 验证。 |
| `robot-tool-sdk` | `ai_runtime.robot_tools` 已不依赖 Nanobot Tool SDK，且 Tool contract/manifest 已独立。 | 逻辑边界成立；当前 Tool catalog 仍只有一个产品使用方，暂不发布 SDK。 |
| `agent-provider-nanobot` | `AgentEngine` 与 `AiProvider` 已存在，但当前 provider 仍包装 Nanobot loop、配置和 session 实现。 | 不应拆出；先实现并实际运行第二种 Provider，确认 contract 足以承载不同生命周期与失败模式。 |
| `webui-transport-sdk` | HTTP/WS 和 robot/library/user/engineer transport 已从页面迁出，bootstrap/capability 有 v1。 | 暂不发布 npm 包；需要第二个 WebUI 或桌面产品证明 API、版本协商与打包入口稳定。 |
| Electron 产品壳 | ProductManifest 集中当前 MotionFlow 参数。 | 暂不拆；manifest 仍是单一 `motionFlowManifest()`，尚无第二产品的安装、更新和资源收集验证。 |

### 本次确认的不可拆前提

1. 现场发布清单中的脱敏 runtime 迁移/回滚和受控硬件验证尚未完成；不能在安全证据未齐时改变发布/导入结构。
2. 兼容 adapter 仍承载已有调用与历史数据迁移，删除或跨仓发布都会扩大回归面。
3. 一个产品无法证明 semver、弃用窗口、独立安装、依赖冲突和资源定位策略；“能 import”不是可发布包的验收标准。

### 下次重新评估的可验证门槛

只有同时满足以下每一项，才创建物理包的实施计划：

- 第二个独立产品实际使用相同的 backend、Tool 或 WebUI transport；
- 该包有版本化公开 API、迁移说明、兼容/弃用策略和独立测试环境；
- 可选 ZMotion 依赖在 wheel、PyInstaller 和无 SDK 的 simulation 环境均验证通过；
- 发布清单的 runtime 迁移/回滚与受控硬件签核完成；
- 至少一次跨项目升级演练证明不会丢失 profile、审计、确认闸门或数据目录。
