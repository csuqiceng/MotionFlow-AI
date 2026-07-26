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
