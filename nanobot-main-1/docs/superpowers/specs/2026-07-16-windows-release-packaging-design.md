# Windows 正式发布打包设计

## 目标

将 Nanobot Robot AI 构建为可交付给其他电脑使用的标准 Windows 安装包。正式支持范围为 Windows 10/11 x64，目标电脑无需预装 Python、Node.js 或项目源码。

唯一正式交付物为 NSIS 安装包：

```text
nanobot-robot-ai-Setup-<version>.exe
nanobot-robot-ai-Setup-<version>.exe.sha256
```

`win-unpacked` 仅用于本机诊断和自动化测试，不作为正式交付物，也不提交 Git。

## 当前问题

1. `release-build4` 当前只有 `win-unpacked`，没有成功生成 Setup 安装包。
2. 发布目录被 Git 跟踪，而仓库同时忽略 `*.pyd`，导致通过 Git 获取的发布目录缺少 `_socket.pyd`、`_ssl.pyd` 等 Python 原生模块。
3. 当前 EXE 未签名，Windows SmartScreen 或企业安全策略可能阻止启动。
4. `signAndEditExecutable: false` 导致主程序仍显示 Electron 的产品名称、版本和公司信息。
5. 现有测试只验证部分脚本文本和 TypeScript 编译，没有验证最终发布目录的关键文件和实际 Gateway 启动。
6. 组织 API Key 位于安装资源中，可以被拥有安装包的人提取，只能作为当前内部交付阶段的临时方案。

## 构建架构

打包流程保持现有两层结构：

```text
React WebUI
  -> 由 Python Gateway 同源提供

Python Gateway + robot_ai + Python Runtime
  -> PyInstaller onedir

Electron 主程序 + PyInstaller Runtime + ZMotion SDK + 默认数据
  -> electron-builder
  -> NSIS Setup.exe
```

PyInstaller 必须生成完整的 onedir 运行时。electron-builder 只从该新生成目录收集文件，禁止从 Git 中恢复或复用发布目录。

## 发布目录管理

- `desktop/release-build4/` 从 Git 索引中移除并加入 `desktop/.gitignore`。
- `desktop/pyinstaller/build/`、`desktop/pyinstaller/dist/` 和 `desktop/release-build4/` 均为可重新生成的构建产物。
- 打包脚本开始时清理并重新创建 PyInstaller 和 electron-builder 输出，避免旧文件掩盖缺失依赖。
- 不允许将 `win-unpacked` 复制到 Git、网盘同步目录后再作为安装包使用。

## 产品元数据

Windows 主程序和安装包使用项目自身信息：

- 产品名：`Nanobot Robot AI`
- 应用 ID：`com.nanobot.robotai`
- 版本：来自 `desktop/package.json`
- 可执行文件名：`Nanobot Robot AI.exe`
- 安装包名：`nanobot-robot-ai-Setup-<version>.exe`
- 架构：x64

恢复 electron-builder 对 EXE 资源的编辑，使文件属性不再显示为 Electron/GitHub。代码签名作为正式对外发布要求；没有证书时允许生成明确标记为未签名的内部测试包，但验收报告必须显示 `NotSigned`。

## 打包前检查

打包脚本必须检查：

- 构建 Python 和 PyInstaller 可用；
- Node.js、`npm.cmd` 和 electron-builder 可用；
- WebUI 已构建并包含入口文件；
- ZMotion 的 `zauxdll.dll`、`zmotion.dll` 和 Python wrapper 存在；
- 默认位置、命令、流程和知识文件存在；
- API Key 通过安全输入或 CI 环境变量提供，模板文件中仍只保存占位符。

任何一项缺失都立即停止，不生成可交付产物。

## 打包后验收

新增独立的发布验收脚本，至少验证：

- Setup 安装包存在且大小非零；
- `win-unpacked/Nanobot Robot AI.exe` 存在；
- `app.asar` 包含编译后的 `build/main.js` 和默认配置；
- `nanobot_gateway.exe` 存在；
- `python311.dll`、`_socket.pyd`、`_ssl.pyd`、`_asyncio.pyd` 存在；
- ZMotion 两个 DLL 和 wrapper 存在；
- 默认位置、命令、流程和知识文件存在；
- EXE 的产品名和产品版本与项目配置一致；
- 安装包 SHA256 文件生成成功；
- 最终安装包不依赖项目绝对路径。

验收失败时打包命令返回非零退出码，不显示“打包成功”。

## 运行验证

自动运行验证分为两层：

1. Gateway 烟雾测试：将 `win-unpacked` 完整复制到包含空格的隔离目录，使用隔离的 `NANOBOT_HOME` 和模拟控制器模式启动打包后的 Gateway，轮询 `/webui/bootstrap`，成功后关闭进程树。
2. Electron 烟雾测试：从隔离目录启动 `Nanobot Robot AI.exe`，确认 Gateway 子进程启动、WebUI bootstrap 可访问、退出 Electron 后子进程被回收。

本机测试不能替代干净系统测试。发布前还需在没有 Python/Node 的 Windows 10 x64 和 Windows 11 x64 虚拟机中分别完成安装、首次启动、登录、卸载测试。

## 安全与兼容边界

- 当前正式支持 Windows 10/11 x64。
- Windows 7/8/8.1、32 位 Windows 和 ARM64 不在本次范围。
- 未签名内部测试包可能触发 SmartScreen；正式对外分发必须配置 Windows 代码签名。
- 固定组织 API Key 能从安装包提取，发布方必须能够撤销和轮换。后续正式生产版本应改为服务端代理或设备授权。
- 安装程序只更新程序文件和默认种子，不覆盖 `%APPDATA%\nanobot-robot-ai\runtime` 中的用户账户、命令、流程、位置和日志。

## 验收标准

1. 一键打包命令生成 Setup 和 SHA256 两个文件。
2. 发布验收脚本检查关键 PYD、DLL、默认资源、产品元数据和 Setup，结果全部通过。
3. 将完整 `win-unpacked` 移动到不同路径后，打包 Gateway 能在隔离数据目录启动。
4. Setup 可在干净 Windows 10/11 x64 环境安装，目标机无需 Python 和 Node.js。
5. 安装后可打开登录页并使用默认账户登录。
6. 升级安装不覆盖已有运行数据。
7. Git 工作区不再因生成 `release-build4` 出现数千项发布产物变更。
