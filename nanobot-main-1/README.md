# Robotic Arm AI Platform

面向通用机械手的本地 AI 控制平台。产品由一个本地 `robot_server`、React 单页控制
界面和 Electron 桌面壳组成，支持机械臂状态、位置库、命令库、流程、AI 对话、
本地身份与安全审计。

项目当前正式支持 Windows 10/11 x64。真实机械臂写入默认受安全门禁保护；首次
调试、换机测试和新控制器接入应先使用 simulation、dry-run 或只读模式。

## 目录

- [普通用户安装](#普通用户安装)
- [开发环境要求](#开发环境要求)
- [从源码安装](#从源码安装)
- [运行后端和网页](#运行后端和网页)
- [运行 Electron 桌面 App](#运行-electron-桌面-app)
- [制作 Windows 安装包](#制作-windows-安装包)
- [测试](#测试)
- [运行数据和故障排查](#运行数据和故障排查)
- [架构与安全边界](#架构与安全边界)

## 普通用户安装

普通测试电脑不需要安装 Python、Node.js 或项目源码，只需要发布者提供的两个文件：

```text
motionflow-ai-Setup-<version>.exe
motionflow-ai-Setup-<version>.exe.sha256
```

安装前先验证 SHA-256：

```powershell
Get-FileHash .\motionflow-ai-Setup-<version>.exe -Algorithm SHA256
Get-Content .\motionflow-ai-Setup-<version>.exe.sha256
```

两者哈希必须一致。随后运行 Setup，选择安装目录并启动 **MotionFlow AI**。

注意：

- 当前内部测试包可能未配置 Windows 代码签名，SmartScreen 可能显示“未知发布者”。
- 安装包已包含 Python 运行时、Robot Server、WebUI、Electron 和 ZMotion SDK 文件。
- 首次在其他电脑测试时先验证登录、AI 对话、位置查询和 dry-run，不要直接执行
  真实机械臂运动。
- 安装包可能内置测试专用 API 密钥，应按敏感文件管理，只发送给授权测试人员。

## 开发环境要求

| 组件 | 要求 |
| --- | --- |
| 操作系统 | Windows 10/11 x64 |
| Python | 3.11 或更高版本 |
| Node.js | 18 或更高版本 |
| npm | 随 Node.js 安装 |
| Git | 推荐最新版 |
| ZMotion SDK | `vendor/zmotion/` 下的 DLL 和 Python wrapper |

检查环境：

```powershell
python --version
node --version
npm --version
git --version
```

## 从源码安装

以下命令均从包含本 README 的项目根目录执行。

### 1. 创建 Python 虚拟环境

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[api,dev]"
```

如果 PowerShell 禁止激活脚本，可以不激活，后续直接使用：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[api,dev]"
```

### 2. 安装并构建 WebUI

```powershell
cd .\webui
npm install
npm run build
cd ..
```

WebUI 构建结果会写入 `robot_server/webui/`，由 Robot Server 在同一个 localhost
端口提供服务。

### 3. 安装 Electron 依赖

```powershell
cd .\desktop
npm install
cd ..
```

### 4. 准备桌面构建环境（需要桌面运行或打包时）

开发桌面 App 和正式打包使用 `desktop/.build-venv`。可以运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\desktop\build-desktop.ps1
```

该脚本会创建构建虚拟环境并继续执行完整桌面构建。如果只想运行后端和浏览器，
普通 `.venv` 即可，不必执行桌面构建。

## 运行后端和网页

### 使用源码虚拟环境

```powershell
.\.venv\Scripts\python.exe -m robot_server.cli --port 8765
```

或在已激活虚拟环境中：

```powershell
robot-server --port 8765
```

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8765/health
```

浏览器打开：

```text
http://127.0.0.1:8765/
```

需要指定已有 Provider 配置时：

```powershell
.\.venv\Scripts\python.exe -m robot_server.cli `
  --port 8765 `
  --config "$env:APPDATA\motionflow-ai\runtime\config.json"
```

服务默认只允许绑定 `127.0.0.1`、`localhost` 或 `::1`。绑定非回环地址必须显式
提供访问令牌，不建议在开发电脑上直接暴露给局域网。

### WebUI 热更新开发

先启动 Robot Server，再打开另一个终端：

```powershell
cd .\webui
$env:NANOBOT_API_URL = "http://127.0.0.1:8765"
npm run dev
```

访问 `http://127.0.0.1:5173/`。Vite 会将 `/api`、`/auth` 和 `/webui` 请求代理到
Robot Server。

## 运行 Electron 桌面 App

确保以下文件存在：

```powershell
Test-Path .\desktop\.build-venv\Scripts\python.exe
Test-Path .\desktop\node_modules
Test-Path .\robot_server\webui\index.html
```

然后运行：

```powershell
cd .\desktop
npm run dev
```

Electron 会自动选择本地端口、启动自己的 Robot Server、等待 `/health` 就绪并打开
桌面窗口。运行 Electron 前不要另外占用它将使用的服务端口；关闭桌面 App 时，
Electron 会一并停止其管理的 Robot Server 进程树。

如果 App 没有打开，优先检查：

```text
%APPDATA%\motionflow-ai\runtime\robot-server.log
```

开发模式也可以通过环境变量指定 Python：

```powershell
$env:NANOBOT_DEV_PYTHON = (Resolve-Path .\.build-venv\Scripts\python.exe)
npm run dev
```

## 制作 Windows 安装包

正式发布入口是 `desktop/package-win.ps1`。它会重新构建 WebUI、PyInstaller Robot
Server、Electron 和 NSIS 安装程序，并执行发布校验、打包后服务冒烟测试与 SHA-256
校验。

### 交互式打包（推荐）

从项目根目录执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\desktop\package-win.ps1
```

看到提示后输入测试专用 API 密钥：

```text
Enter the organization API key to embed
```

输入采用 `SecureString`，不会显示在窗口中。不要把真实密钥写进命令、README、
`.env`、模板、Git 提交或构建日志。

### CI/受控环境打包

CI Secret 必须以当前构建进程的 `NANOBOT_ORGANIZATION_API_KEY` 环境变量注入，
然后执行：

```powershell
cd .\desktop
.\.package-with-runtime-key.ps1
```

该脚本不会从开发电脑的 AppData 配置中读取真实密钥。环境变量缺失、模板存在混合
凭据、多个占位符、非法凭据字段或日志泄漏风险时，构建会直接失败。

### 打包产物

成功产物位于：

```text
desktop/release2/motionflow-ai-Setup-<version>.exe
desktop/release2/motionflow-ai-Setup-<version>.exe.sha256
desktop/release2/win-unpacked/
```

对其他电脑只交付 Setup 和 `.sha256`，不要单独复制
`win-unpacked/MotionFlow AI.exe`。

完整的打包、安全密钥、换机验收和故障处理说明见：

- [Windows 中文打包说明](desktop/PACKAGING-GUIDE.zh-CN.md)
- [Windows Build Guide](desktop/BUILD-GUIDE.md)
- [桌面版交付说明](desktop/README.md)

### 内置密钥风险

初版安装包内置密钥可能被提取。必须使用独立、限额、限流、可监控、可随时吊销的
安装包专用密钥。服务端代理上线后，应删除客户端内置密钥并吊销所有历史客户端
密钥。

## 测试

Python 核心、Robot AI 和 Robot Server：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\robot_ai tests\robot_server -q
```

仓库凭据卫生和打包注入：

```powershell
.\desktop\.build-venv\Scripts\python.exe -m pytest `
  tests\architecture\test_repository_secret_hygiene.py -q
node .\desktop\electron\tests\before-pack.test.js
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\desktop\tests\package-win-script.test.ps1
```

WebUI：

```powershell
cd .\webui
npm test
npm run lint
npm run build
```

发布产物：

```powershell
cd .\desktop
npm run verifyRelease
npm run smokePackagedRobotServer
```

## 管理命令

```powershell
robot-admin engineer set-password
robot-admin users set-bootstrap-password --username operator
```

密码通过安全终端提示输入，不接受命令行明文密码。

## 运行数据和故障排查

安装版默认运行数据：

```text
%APPDATA%\motionflow-ai\runtime
```

平台库、位置、命令、流程和审计数据位于 Nanobot 运行目录下的
`robot_platform/`。不要把开发电脑的运行数据、日志或配置文件打进安装包。

常见现象：

- `idempotency_key_required`：工具调用 ID 没有进入运行时幂等上下文，或运行了未
  更新的旧进程；更新代码并重启服务后再验证。
- `AuditIntegrityError`：审计历史不符合当前 HMAC 链规则。不要删除原文件，应由
  管理员原样隔离旧审计、记录 SHA-256，再生成新审计链。
- `disconnected/degraded`：未连接真实控制器或 ZMotion 配置不可用；在 dry-run
  测试电脑上属于预期，不代表 AI 或桌面服务启动失败。
- 网页能打开但无法操作：静态页面可能仍在浏览器缓存中，应先检查 `/health` 和
  `robot-server.log`。

## 架构与安全边界

```text
Electron / browser
        │ HTTP + WebSocket（单一 localhost 端口）
robot_server            # API、单页 UI、会话与服务进程
        │
ai_runtime              # 与传输层无关的 Agent/Tool 运行契约
        │
robot_platform          # 厂商无关的平台、应用服务和安全边界
        │
robot_platform/backends # simulation、ZMotion 和未来厂商适配器
```

`nanobot/` 目前只保留 Agent 引擎的过渡性实现，不能作为产品入口或新业务模块的
依赖。新代码应依赖 `agent_contracts`、`ai_runtime`、`robot_platform` 或
`robot_server` 的公开接口。

核心安全不变量：

- 真实写入默认关闭，新接入先使用 simulation、dry-run 或只读模式。
- 运动必须经过规划、现场条件验证、明确确认和执行许可。
- 急停通过独立 API/平台用例执行，不能被普通 Agent 对话替代。
- 服务默认只绑定回环地址，身份令牌与服务访问令牌相互独立。
- UI、Agent Runtime 和 HTTP 路由不得直接调用厂商 SDK。

更多架构与发布资料：

- [模块化迁移进度](docs/architecture/modular-migration-progress.md)
- [兼容性矩阵](docs/architecture/modular-migration-compatibility-matrix.md)
- [发布清单](docs/architecture/release-checklist.md)
- [拆包决策记录](docs/architecture/package-extraction-decision-record.md)
- [解耦与组件化实施方案](docs/architecture/motionflow-decoupling-implementation-plan.md)

## License

本项目采用 MIT License，详见 [LICENSE](LICENSE)。第三方依赖与资源声明见
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
