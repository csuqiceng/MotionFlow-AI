# MotionFlow AI Windows 安装包制作说明

本文档用于在 Windows 10/11 x64 上制作可复制到其他电脑测试的
MotionFlow AI 安装程序。正式入口是 `desktop/package-win.ps1`。

## 1. 安全原则

1. Git 仓库和配置模板中只能保留唯一占位符
   `__ORGANIZATION_API_KEY__`，不得保存真实密钥。
2. 本地打包时使用 PowerShell 的安全输入提示；CI 打包时只能通过构建任务的
   `NANOBOT_ORGANIZATION_API_KEY` 进程环境变量注入。
3. 不要把密钥写进命令行、脚本参数、`.env`、日志、测试输出或提交记录。
4. `before-pack.js` 只允许替换模板中指定 provider 的完整 `apiKey` 字段；模板中
   出现混合凭据、多个占位符、非占位凭据或非法凭据字段时，打包会立即失败。
5. 初版安装包内置密钥存在被提取的风险。必须使用独立、限额、限流、可监控、
   可随时吊销的测试专用密钥，不得使用个人主密钥或生产主密钥。
6. 服务端代理上线后，应删除客户端内置密钥，并立即吊销所有旧安装包密钥。

## 2. 打包前准备

从仓库根目录检查以下资源：

```powershell
Test-Path .\desktop\.build-venv\Scripts\python.exe
Test-Path .\desktop\node_modules
Test-Path .\vendor\zmotion\zauxdll.dll
Test-Path .\vendor\zmotion\zmotion.dll
Test-Path .\vendor\zmotion\zauxdllPython.py
```

以上结果都应为 `True`。另外建议先确认工作区内容和当前分支：

```powershell
git branch --show-current
git status --short
```

安装包会包含当前工作区源码，而不只包含最后一次 Git 提交。用于对外分发前，建议
先提交、打标签并记录版本号；临时测试包至少要记录提交哈希和未提交变更。

## 3. 本机交互式打包（推荐）

在仓库根目录执行：

```powershell
cd .\desktop
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\package-win.ps1
```

看到下面的提示时输入测试专用密钥并按回车：

```text
Enter the organization API key to embed
```

PowerShell 使用 `SecureString` 接收输入，输入内容不会显示，也不会进入命令历史。
不要把密钥直接拼接到上述命令中。

脚本会依次完成：

1. 校验 Python、ZMotion SDK、WebUI、配置模板和发布脚本。
2. 清理本脚本管理的旧 PyInstaller 和 `release2` 产物。
3. 重新构建 WebUI，防止安装包包含过期前端。
4. 通过 PyInstaller 构建独立的 `robot_server.exe` 运行目录。
5. 编译 Electron 主进程和 preload。
6. 通过 electron-builder 生成 x64 NSIS 安装程序。
7. 执行发布结构、模板和密钥注入校验。
8. 启动打包后的 Robot Server，执行健康检查和 WebUI 冒烟测试。
9. 生成并复核安装程序 SHA-256 文件。
10. 在 `finally` 中删除临时生成的含密钥配置，并清理构建进程环境。

## 4. CI/受控构建环境打包

CI 密钥应配置在平台的 Secret 管理中，并仅注入当前构建进程。构建步骤调用：

```powershell
cd .\desktop
.\.package-with-runtime-key.ps1
```

该脚本只读取当前构建进程中的 `NANOBOT_ORGANIZATION_API_KEY`，不会从本机
`AppData`、仓库配置或模板中读取真实密钥。环境变量缺失时会直接失败。

不要在普通终端中执行下面这种命令：

```powershell
# 错误示例：真实密钥会进入命令历史
$env:NANOBOT_ORGANIZATION_API_KEY = "真实密钥"
```

如果构建平台不支持安全 Secret 注入，应使用第 3 节的交互式安全提示，不要自行
创建临时密钥文件。

## 5. 安装包产物

成功后产物位于：

```text
desktop/release2/motionflow-ai-Setup-0.1.0.exe
desktop/release2/motionflow-ai-Setup-0.1.0.exe.sha256
desktop/release2/win-unpacked/
```

版本号来自 `desktop/package.json`。每次分发必须同时提供 `.exe` 和相邻的
`.sha256` 文件，不要使用旧目录中仅凭时间判断的历史安装包。

手动复核哈希：

```powershell
$installer = ".\desktop\release2\motionflow-ai-Setup-0.1.0.exe"
$actual = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
$expected = ((Get-Content -LiteralPath "$installer.sha256" -Raw).Trim() -split "\s+")[0].ToLowerInvariant()
if ($actual -ne $expected) { throw "Installer SHA-256 mismatch" }
Write-Host "Installer SHA-256 verified: $actual"
```

也可以重新执行发布校验：

```powershell
cd .\desktop
npm run verifyRelease
npm run smokePackagedRobotServer
```

## 6. 在其他电脑上测试

1. 将安装程序和 `.sha256` 文件一起复制到目标电脑。
2. 在目标电脑使用 `Get-FileHash` 复核 SHA-256，确认传输过程中未被修改。
3. 安装到普通用户可写目录；当前为测试包，如未配置代码签名，Windows 可能显示
   未知发布者提示。
4. 首次启动后确认桌面窗口能打开，`/health` 正常，WebUI 能加载。
5. 先验证登录、AI 对话、位置查询、流程列表和 dry-run。
6. 在没有连接真实控制器时，机械臂状态显示 `disconnected/degraded` 属于预期，
   不代表桌面应用或 AI 服务启动失败。
7. 未完成控制器地址、SDK、权限、安全门禁和急停验证前，不要执行真实运动。
8. 测试结束后，如安装包曾发送给非受控人员，立即吊销或轮换该安装包专用密钥。

## 7. 发布前最小检查清单

```powershell
# 仓库不得包含真实凭据
.\desktop\.build-venv\Scripts\python.exe -m pytest `
  tests\architecture\test_repository_secret_hygiene.py -q

# 密钥注入的正常和失败场景、日志不泄漏
node .\desktop\electron\tests\before-pack.test.js

# 打包脚本结构
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\desktop\tests\package-win-script.test.ps1

# Electron 产品清单
node .\desktop\electron\tests\product-manifest.test.js
```

所有检查通过后再执行正式打包。

## 8. 常见问题

### 安装包生成了，但时间是旧的

正式脚本会清理并重建 `desktop/release2`。不要直接使用目录中打包前已存在的
`.exe`；以本次脚本最终输出路径、时间和 SHA-256 为准。

### 提示缺少 API 密钥

- 本地打包：直接运行 `package-win.ps1`，在安全提示中输入。
- CI 打包：确认 Secret 已注入当前进程的
  `NANOBOT_ORGANIZATION_API_KEY`。
- 不要从 `%APPDATA%\motionflow-ai\runtime\config.json` 复制密钥进行打包。

### 提示模板存在混合或多个凭据

停止打包，检查 `desktop/electron/config.default.template.json`。模板只能在指定
provider 的 `apiKey` 字段保留一个完整占位符，其他 provider 凭据必须为空。

### PyInstaller 或 Electron 构建失败

确认 `desktop/.build-venv`、`desktop/node_modules`、ZMotion SDK 和 WebUI 资源
完整。不要通过跳过 `verifyRelease` 或 `smokePackagedRobotServer` 来强行获得安装包。

### App 启动时报审计完整性错误

不要删除审计历史。先停止服务，将异常 `audit.jsonl` 和锁文件原样移动到带时间戳
的隔离目录，再由新版本生成 HMAC 审计链，并保存旧文件 SHA-256。该操作应由明确
授权的管理员完成。

## 9. 回滚与密钥吊销

- 保留上一个已验证安装程序及 SHA-256，可用于应用版本回滚。
- 不要通过重新启用旧密钥完成回滚；旧密钥一旦吊销就保持吊销。
- 发现安装包泄漏、异常调用、额度激增或无法确认分发范围时，先吊销密钥，再调查。
- 服务端代理上线后，删除客户端打包注入路径，发布无内置密钥的新版本，并吊销
  所有历史客户端密钥。
