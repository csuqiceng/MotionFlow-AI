# MotionFlow AI 打包文档

本文档详细说明如何在 Windows 上从源码打包 MotionFlow AI 桌面应用，生成 NSIS 安装包。

---

## 1. 打包产物概览

| 产物 | 路径 | 说明 |
|------|------|------|
| NSIS 安装包 | `desktop\release2\motionflow-ai-Setup-<version>.exe` | 正式交付给用户的安装程序 |
| 免安装版目录 | `desktop\release2\win-unpacked\` | 解压即可运行的完整应用，仅用于本机诊断 |
| SHA-256 校验 | `desktop\release2\motionflow-ai-Setup-<version>.exe.sha256` | 安装包完整性校验文件（`package-win.ps1` 流程才生成） |

**版本号** 取自 [desktop/package.json](file:///d:/learn/yjcao/nanobot-robotic-arms/nanobot-main-1/desktop/package.json) 的 `version` 字段（当前 `0.1.0`）。

---

## 2. 构建环境要求

### 2.1 操作系统
- **Windows 10/11 x64**（仅在 x64 上正式支持）
- Windows 7/8/8.1、32 位 Windows、ARM64 不在正式支持范围

### 2.2 必装软件

| 软件 | 版本要求 | 说明 |
|------|---------|------|
| Python | >= 3.11（推荐 3.14） | 用于构建 PyInstaller gateway。系统默认 Python 若低于 3.11 会因 `tomllib` 缺失而失败 |
| Node.js | >= 18 | 用于编译 Electron 主进程和运行 electron-builder |
| npm | >= 9 | 随 Node.js 一起安装 |

检查命令：
```powershell
python --version   # 应输出 3.11+
node --version     # 应输出 v18+
npm --version      # 应输出 9+
```

### 2.3 项目内必备资源

以下文件/目录必须存在，否则打包失败：

| 资源 | 路径 | 用途 |
|------|------|------|
| WebUI 构建产物 | `nanobot\web\dist\index.html` 及整个 dist 目录 | gateway 启动后通过 `GET /` 提供前端页面 |
| ZMotion SDK | `vendor\zmotion\zauxdll.dll` `zmotion.dll` `zauxdllPython.py` | 机械手控制器 SDK |
| 应用图标 | `desktop\electron\assets\nanobot-app-icon.ico` | exe 图标 |
| rcedit 工具 | `desktop\tools\rcedit-x64.exe` | 写入 Windows exe 版本信息（公司、商标等） |
| PyInstaller spec | `desktop\pyinstaller\nanobot.spec` | gateway 打包配置 |
| 配置模板 | `desktop\electron\config.default.template.json` | 含 `__ORGANIZATION_API_KEY__` 占位符，打包时注入实际密钥 |
| 默认数据 | `desktop\electron\defaults\robot_ai\*.json` | positions/commands/flows/knowledge 默认数据 |

---

## 3. 打包架构

应用由三层组成，每层独立构建：

```
┌──────────────────────────────────────────────────────────┐
│  NSIS 安装包 (motionflow-ai-Setup-0.1.0.exe)           │
│  ┌────────────────────────────────────────────────────┐  │
│  │  Electron 壳 (app.asar)                            │  │
│  │  - build/main.js (编译后的 TS 主进程)              │  │
│  │  - electron/default-config.json (注入 API Key)     │  │
│  │  - electron/config-wizard/wizard.html (首运行向导) │  │
│  │  - electron/defaults/robot_ai/*.json (默认数据)    │  │
│  └────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────┐  │
│  │  py-runtime (PyInstaller onedir)                   │  │
│  │  - nanobot_gateway.exe (Python gateway)           │  │
│  │  - _internal/python311.dll (Python 运行时)         │  │
│  │  - _internal/nanobot/web/dist/ (前端静态资源)      │  │
│  │  - _internal/nanobot/templates/ (Jinja2 模板)     │  │
│  └────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────┐  │
│  │  vendor/zmotion (ZMotion SDK DLL)                 │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

**运行时数据目录**（用户配置、凭据、日志，不在安装包内）：
```
%APPDATA%\motionflow-ai\runtime\
  ├── config.json                 # 用户配置（首运行向导写入）
  ├── desktop-env.json            # 环境变量（控制器 IP、后端模式等）
  ├── gateway.log                 # gateway 日志
  └── robot_ai\
      ├── users.json              # 用户凭据（首次运行自动创建）
      ├── flows.json              # 用户流程
      ├── commands.json           # 用户命令
      ├── positions.json          # 用户位置
      └── knowledge.json          # 用户知识库
```

---

## 4. 打包方式选择

提供两种打包路径：

| 方式 | 脚本 | 适用场景 | 是否注入 API Key |
|------|------|---------|-----------------|
| **完整流程** | `package-win.ps1` | 正式交付（含密钥注入、冒烟测试、SHA-256 校验） | 是，交互式输入 |
| **快速流程** | 手动分步执行 | 开发调试、仅更新前端、复用已有 py-runtime | 可选 |

---

## 5. 完整打包流程（package-win.ps1）

### 5.1 前置准备

1. 确认 Python 3.11+、Node.js 18+ 已安装；
2. 创建构建 venv（首次或依赖更新后需要）：
   ```powershell
   cd d:\learn\yjcao\nanobot-robotic-arms\nanobot-main-1\desktop
   python -m venv .build-venv
   .\.build-venv\Scripts\python.exe -m pip install -U pip
   .\.build-venv\Scripts\python.exe -m pip install -e "..[api,pdf]" "pyinstaller>=6.0"
   ```
3. 构建 WebUI 前端（首次或前端代码变更后需要）：
   ```powershell
   cd d:\learn\yjcao\nanobot-robotic-arms\nanobot-main-1\webui
   npm install
   npm run build
   ```
   产物输出到 `nanobot\web\dist\`；
4. 安装 desktop npm 依赖（首次或依赖更新后需要）：
   ```powershell
   cd d:\learn\yjcao\nanobot-robotic-arms\nanobot-main-1\desktop
   npm install
   ```

### 5.2 执行一键打包

在项目根目录运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\desktop\package-win.ps1
```

脚本会提示输入组织 API Key（输入时不可见）。完整流程如下：

| 步骤 | 脚本动作 | 输出位置 |
|------|---------|---------|
| 1 | 检查必备资源是否齐全 | — |
| 2 | 清理旧的 PyInstaller build/dist、release-build4 目录 | — |
| 3 | 设置 `NANOBOT_ORGANIZATION_API_KEY` 环境变量 | 进程内 |
| 4 | 调用 PyInstaller 构建 gateway | `desktop\pyinstaller\dist\py-runtime\` |
| 5 | 调用 `npm run build` 编译 Electron 主进程 TS | `desktop\build\` |
| 6 | 调用 `npm run dist` 触发 electron-builder | `desktop\release-build4\` |
| 7 | `before-pack.js` 将 API Key 注入 `default-config.json` | 临时文件，打包后删除 |
| 8 | `after-pack.js` 用 rcedit 写入 exe 版本信息（公司、商标） | exe 元数据 |
| 9 | `verify-release.ps1` 检查产物完整性 | — |
| 10 | `smoke-packaged-gateway.ps1` 启动 gateway 冒烟测试 | — |
| 11 | 生成并核对 SHA-256 校验文件 | `*.exe.sha256` |

任何一步失败都会以非零退出码终止，不会把不完整的安装包标记为成功。

### 5.3 产物位置

```
desktop\release-build4\
  ├── motionflow-ai-Setup-0.1.0.exe           # 正式交付的安装包
  ├── motionflow-ai-Setup-0.1.0.exe.sha256   # 完整性校验
  └── win-unpacked\                           # 免安装版（仅诊断用）
      ├── MotionFlow AI.exe
      └── resources\
          ├── app.asar                        # Electron 应用包
          ├── py-runtime\                     # Python gateway
          └── vendor\zmotion\                 # ZMotion SDK
```

---

## 6. 快速打包流程（手动分步）

适用于：仅更新前端代码、复用已有 py-runtime、开发调试。

### 6.1 仅更新 WebUI

当只改了前端代码（React 组件、样式等），无需重新构建 Python gateway：

```powershell
# 1. 构建 WebUI
cd d:\learn\yjcao\nanobot-robotic-arms\nanobot-main-1\webui
npm run build
# 产物输出到 nanobot\web\dist\

# 2. 复制现有 py-runtime（如已构建过）
$src = "d:\learn\yjcao\nanobot-robotic-arms\nanobot-main-1\desktop\release2\win-unpacked\resources\py-runtime"
$dst = "d:\learn\yjcao\nanobot-robotic-arms\nanobot-main-1\desktop\pyinstaller\dist\py-runtime"
if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
Copy-Item $src $dst -Recurse -Force

# 3. 用新 WebUI 覆盖 py-runtime 中的旧 WebUI
$webSrc = "d:\learn\yjcao\nanobot-robotic-arms\nanobot-main-1\nanobot\web\dist"
$webDst = "$dst\_internal\nanobot\web\dist"
if (Test-Path $webDst) { Remove-Item $webDst -Recurse -Force }
Copy-Item $webSrc $webDst -Recurse -Force

# 4. 编译 Electron 主进程
cd d:\learn\yjcao\nanobot-robotic-arms\nanobot-main-1\desktop
npm run build

# 5. 清理旧产物并打包
Remove-Item -Recurse -Force release2\win-unpacked -ErrorAction SilentlyContinue
Remove-Item -Force release2\motionflow-ai-Setup-*.exe -ErrorAction SilentlyContinue
npx electron-builder --config electron-builder.yml --win nsis --x64
```

### 6.2 完整重新构建（含 Python gateway）

```powershell
cd d:\learn\yjcao\nanobot-robotic-arms\nanobot-main-1\desktop

# 1. 构建 WebUI（如未构建）
Push-Location ..\webui
npm run build
Pop-Location

# 2. PyInstaller 构建 gateway
$buildPython = ".\.build-venv\Scripts\python.exe"
Push-Location pyinstaller
& $buildPython -m PyInstaller nanobot.spec --noconfirm --clean --distpath dist --workpath build
Pop-Location

# 3. 编译 Electron 主进程
npm run build

# 4. 打包
Remove-Item -Recurse -Force release2\win-unpacked -ErrorAction SilentlyContinue
Remove-Item -Force release2\motionflow-ai-Setup-*.exe -ErrorAction SilentlyContinue
npx electron-builder --config electron-builder.yml --win nsis --x64
```

> **注意**：快速流程不注入 API Key，`before-pack.js` 会写入占位符 `__ORGANIZATION_API_KEY__`，首运行时会弹出配置向导让用户输入自己的 API Key。

---

## 7. 关键配置文件详解

### 7.1 [electron-builder.yml](file:///d:/learn/yjcao/nanobot-robotic-arms/nanobot-main-1/desktop/electron-builder.yml)

```yaml
appId: com.motionflow.ai           # Windows 应用唯一标识
productName: MotionFlow AI          # 显示名称
copyright: Copyright © 2026 MotionFlow AI
publish: null                       # 本地构建不发布到更新渠道

directories:
  output: release2                  # 输出目录（package-win.ps1 用 release-build4）

files:                              # 打包进 app.asar 的文件
  - build/**/*                       #   编译后的 Electron 主进程
  - electron/config-wizard/**/*     #   首运行向导 HTML
  - electron/default-config.json     #   注入 API Key 后的默认配置
  - electron/defaults/**/*           #   默认 robot_ai 数据
  - package.json

extraResources:                      # 不进 asar，放在 resources/ 下
  - from: electron/defaults         #   默认数据（与 asar 内重复但 gateway 直接读取）
    to: defaults
  - from: pyinstaller/dist/py-runtime  # Python gateway 整个 onedir
    to: py-runtime
  - from: ../vendor/zmotion          #   ZMotion SDK
    to: vendor/zmotion

win:
  executableName: MotionFlow AI
  icon: electron/assets/nanobot-app-icon.ico
  legalTrademarks: MotionFlow AI
  target:
    - target: nsis
      arch: [x64]
  artifactName: motionflow-ai-Setup-${version}.${ext}
  signAndEditExecutable: false      # 用 after-pack.js 中的 rcedit 代替

nsis:
  oneClick: false                   # 非一键安装，允许选择安装目录
  perMachine: false                 # 当前用户安装，无需管理员
  allowToChangeInstallationDirectory: true
```

### 7.2 [nanobot.spec](file:///d:/learn/yjcao/nanobot-robotic-arms/nanobot-main-1/desktop/pyinstaller/nanobot.spec)

PyInstaller 打包配置，生成 `nanobot_gateway.exe`。关键部分：

```python
datas = [
    # WebUI 前端编译产物 — gateway 通过 GET / 提供
    (REPO_ROOT / "nanobot" / "web" / "dist", "nanobot/web/dist"),
    # Jinja2 提示词模板 — agent 系统提示词
    (REPO_ROOT / "nanobot" / "templates", "nanobot/templates"),
    # Robot AI 默认数据
    (REPO_ROOT / "desktop" / "electron" / "defaults" / "robot_ai", "defaults/robot_ai"),
    # ZMotion SDK
    (REPO_ROOT / "vendor" / "zmotion", "vendor/zmotion"),
]

hiddenimports = [
    "nanobot.agent.tools.robot_arm",      # 机械手控制工具
    "nanobot.agent.tools.robot_flow",     # 流程执行工具
    "robot_ai.backends.zmotion_backend",  # ZMotion 后端
    "robot_ai.backends.simulation_backend",# 模拟后端
    "uvicorn.protocols.http.auto",        # ASGI 服务器
    "tiktoken_ext.openai_public",         # token 计数
    # ... 其他隐式导入
]

excludes = ["matplotlib", "numpy", "pandas", "scipy", "tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6", "IPython", "notebook"]
```

### 7.3 [before-pack.js](file:///d:/learn/yjcao/nanobot-robotic-arms/nanobot-main-1/desktop/electron/before-pack.js)

electron-builder 钩子，在文件收集前运行：

- 读取 `electron/config.default.template.json`（含 `__ORGANIZATION_API_KEY__` 占位符）；
- 如果设置了 `NANOBOT_ORGANIZATION_API_KEY` 环境变量，替换占位符写入 `default-config.json`；
- 如果未设置，原样写入模板（占位符保留），首运行时弹出配置向导。

### 7.4 [after-pack.js](file:///d:/learn/yjcao/nanobot-robotic-arms/nanobot-main-1/desktop/electron/after-pack.js)

electron-builder 钩子，在文件收集后运行：

- 调用 `tools/rcedit-x64.exe` 写入 exe 的 Windows 版本信息：
  - `FileDescription`、`ProductName` = `MotionFlow AI`
  - `ProductVersion`、`FileVersion` = 版本号
  - `LegalCopyright` = 版权信息
  - `CompanyName` = `MotionFlow AI`
  - `LegalTrademarks` = `MotionFlow AI`
  - 设置 exe 图标

---

## 8. 运行时启动流程

打包后用户首次启动应用的完整流程：

```
用户双击 MotionFlow AI.exe
        │
        ▼
Electron 主进程启动 (build/main.js)
        │
        ├─ 设置 userData = %APPDATA%\motionflow-ai
        ├─ 解析运行数据目录 = %APPDATA%\motionflow-ai\runtime
        │
        ├─ 启动 PyInstaller gateway
        │   └─ nanobot_gateway.exe --foreground --verbose
        │       --config <runtime>\config.json
        │       --port <随机空闲端口>
        │
        ├─ 等待 gateway 健康检查通过
        │   └─ GET /webui/bootstrap 返回 200
        │
        ├─ 检查 config.json 是否已有有效 provider
        │   ├─ 是 → 直接加载 WebUI
        │   └─ 否 → 显示首运行配置向导 (wizard.html)
        │           └─ 用户填写 API Key、模型、控制器 IP
        │               └─ 写入 config.json + desktop-env.json
        │                   └─ 重启 gateway
        │
        └─ BrowserWindow 加载 http://127.0.0.1:<port>/
            └─ gateway 从 _internal/nanobot/web/dist/ 提供前端
```

---

## 9. 默认登录凭据

| 角色   | 用户名   | 密码 |
|--------|----------|------|
| 工程师 | admin    | 0000 |
| 操作员 | operator | 0000 |

凭据存储在 `%APPDATA%\motionflow-ai\runtime\robot_ai\users.json`，首次运行时由 `runtime_data.py` 自动创建。密码可通过工程师设置 UI 或 `nanobot users set-bootstrap-password` 命令修改。

---

## 10. API Key 注意事项

- 打包时输入的组织 API Key 会写入安装包的默认配置（`electron/default-config.json`）；
- 安装包及其副本应按敏感文件管理，只提供给授权人员；
- 密钥泄露或不再使用时，应在服务端立即撤销或轮换；
- 快速打包流程（不注入 Key）首运行时会弹出配置向导，用户自行输入 API Key。

---

## 11. 验证安装包

### 11.1 校验 SHA-256

```powershell
Get-FileHash .\motionflow-ai-Setup-0.1.0.exe -Algorithm SHA256
```

结果应与 `.sha256` 文件中的值一致。

### 11.2 检查 exe 元数据

```powershell
$info = (Get-Item ".\win-unpacked\MotionFlow AI.exe").VersionInfo
$info.ProductName      # 应为 MotionFlow AI
$info.ProductVersion   # 应为 0.1.0
$info.LegalTrademarks  # 应为 MotionFlow AI
```

### 11.3 自动验证脚本

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\desktop\verify-release.ps1
```

检查项：
- 必备文件是否齐全（exe、app.asar、py-runtime、ZMotion DLL、默认数据）；
- 默认 JSON 文件是否可解析；
- app.asar 是否包含 `build/main.js`、`package.json`、`electron/default-config.json`；
- exe 元数据（ProductName、ProductVersion）是否正确；
- 生成 SHA-256 校验文件。

---

## 12. 干净电脑验收

每次正式发布至少在 Windows 10 x64 和 Windows 11 x64 的干净虚拟机中验证：

1. 系统未安装 Python 和 Node.js；
2. `.sha256` 与安装包实际 SHA-256 一致；
3. Setup 安装成功；
4. 首次启动可以打开登录页；
5. 默认账户可以登录；
6. 命令库、流程库、工程师页面和控制器状态页面可以打开；
7. 模拟模式下可以执行一条安全命令或流程；
8. 关闭应用后没有残留 `nanobot_gateway.exe`；
9. 覆盖升级不会删除用户运行数据；
10. 卸载成功。

---

## 13. 常见问题排查

### 13.1 Electron 启动后页面空白

**原因**：WebUI 静态资源未打包进 py-runtime。

**修复**：确认 `nanobot\web\dist\` 已构建，且 `nanobot.spec` 的 datas 包含 `(REPO_ROOT / "nanobot" / "web" / "dist", "nanobot/web/dist")`。

### 13.2 登录后 AI 回复 "Sorry, I encountered an error."

**原因**：Jinja2 提示词模板未打包。

**修复**：确认 `nanobot.spec` 的 datas 包含 `(REPO_ROOT / "nanobot" / "templates", "nanobot/templates")`。

### 13.3 Gateway 启动失败（401 Unauthorized）

**原因**：API Key 为占位符 `__ORGANIZATION_API_KEY__` 或 NANOBOT_HOME 指向了错误目录。

**修复**：
- 正式打包用 `package-win.ps1` 注入真实 Key；
- 或首运行时通过配置向导输入用户自己的 Key；
- 确认 NANOBOT_HOME 指向 `%APPDATA%\motionflow-ai\runtime`。

### 13.4 Python 版本不匹配

**原因**：系统默认 Python 低于 3.11，`import tomllib` 失败。

**修复**：用 Python 3.11+ 创建专用构建 venv：
```powershell
python -m venv .build-venv
.\.build-venv\Scripts\python.exe -m pip install -e "..[api,pdf]" "pyinstaller>=6.0"
```

### 13.5 electron-builder 尝试发布并失败

**原因**：CI 环境检测导致 electron-builder 尝试发布到 GitHub。

**修复**：在 `electron-builder.yml` 中添加 `publish: null`（已配置）。

### 13.6 WebUI 连接 WebSocket 失败

**原因**：开发模式下 Vite 代理端口与 gateway 实际端口不匹配。

**修复**：通过 `NANOBOT_API_URL` 环境变量指定 gateway 的实际端口；打包模式不受影响（gateway 动态分配端口并通过 bootstrap 响应告知前端）。

### 13.7 查看 gateway 日志

gateway 日志写入 `%APPDATA%\motionflow-ai\runtime\gateway.log`，包含启动诊断和运行时错误。

---

## 14. 未签名安装包说明

没有配置 Windows 代码签名证书时，安装包属于未签名内部测试包：
- SmartScreen 可能显示"未知发布者"；
- 企业安全策略可能直接阻止运行。

正式对外分发前，应配置 OV、EV 或 Azure Trusted Signing，并在签名后的最终安装包上重新执行完整性验证和干净电脑验收。

---

## 15. 便携模式

使用 `--portable` 参数启动时，运行数据存放在应用程序同级目录：

```
<MotionFlow AI.exe 所在目录>\
  └── data\nanobot\
      ├── config.json
      └── robot_ai\
```

便携模式适用于 U 盘携带、不污染系统注册表的场景。构建输出和安装包不应包含开发电脑现有的用户运行数据。
