# MotionFlow AI Windows 安装包发布操作手册

本文对应当前的 `desktop/package-win.ps1` 发布脚本。它生成包含 Electron、WebUI、Python 机器人服务、ZMotion SDK 与项目默认机器人库的 Windows x64 NSIS 安装包。

> 适用范围：内部受控测试与交付。当前安装包**没有代码签名**；首次在其他电脑安装时，Windows 可能显示“未知发布者”提示。不要把含部署 AI 凭据的包公开上传。

## 1. 打包前必须理解的两类配置

不要混淆“随安装包首次带出的默认数据”和“用户电脑运行后生成的数据”。

| 类型 | 位置 | 用途 | 是否会覆盖已有用户数据 |
| --- | --- | --- | --- |
| AI 部署模板 | `desktop/electron/config.default.template.json` | 服务商、模型、底层工具执行策略、语音服务配置 | 只在首次安装创建运行时 `config.json` |
| 默认机器人库 | `desktop/electron/defaults/robot_ai/` | 首次安装时复制的位置、命令、流程、知识库 | 不覆盖已有运行时库 |
| 位置种子 | `robot_platform/positions/seed_positions.json` | 从项目配置导入命名位置 | 只补缺失位置 |
| 命令种子 | `robot_platform/library/seed_query_table.json` | 项目 Func 命令定义，包括运动、急停、复位等 | 首次建立命令库时导入 |
| PyInstaller 定义 | `desktop/pyinstaller/robot_server.spec` | 指定哪些 Python 模块与数据文件进入 `robot_server.exe` | 每次构建重新生效 |
| 用户运行时目录 | `%APPDATA%\motionflow-ai\runtime\` | 实际使用的 AI 配置、机器人库、日志、审计记录 | 安装或升级时必须保留 |

默认机器人库目录中各文件的职责：

- `positions.json`：命名位置；例如 home、位置 A/B/C。它是数据文件，不应在 Python/TypeScript 中写死名称或坐标。
- `commands.json`：命令库；保存完整命令参数，例如运动速度、加速度、减速度、Func 编号。
- `flows.json`：流程库；旧项目 `1.1` 格式会在首次读取时自动迁移为当前可发布格式。
- `knowledge.json`：机器人知识库。

新建位置时，系统会把该位置加入运行时的 `positions.json`，并创建对应的移动命令。已有项目命令的完整运动参数是源数据，不会被位置导入覆盖。

## 2. 发布前检查清单

在仓库根目录执行。建议先确认工作区干净，避免把临时文件打进未审核版本。

```powershell
git status
node --version
npm --version
.\desktop\.build-venv\Scripts\python.exe --version
```

必须存在的本地依赖和资源：

- Windows x64；Node.js 与 npm 已可用。
- `desktop/.build-venv/Scripts/python.exe`：Python 构建环境；项目当前使用 Python 3.11 及以上。
- `desktop/node_modules/` 与 `webui/node_modules/`：Electron、electron-builder、TypeScript、前端依赖。
- `vendor/zmotion/zauxdll.dll`、`vendor/zmotion/zmotion.dll`、`vendor/zmotion/zauxdllPython.py`：下位机 SDK。
- `desktop/tools/rcedit-x64.exe` 与 `desktop/electron/assets/robot-arm-app-icon.ico`：Windows 可执行文件元数据和图标。
- `robot_server/webui/index.html`：WebUI 构建输入。发布脚本会先自动重新构建它。

可先运行静态检查：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\desktop\tests\package-win-script.test.ps1

powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\desktop\tests\pyinstaller-spec.test.ps1
```

## 3. AI 部署凭据（最重要）

桌面 UI 不提供用户修改 AI 服务商、模型和密钥的入口；这些都由发布时配置决定。

推荐做法是让 `desktop/electron/config.default.template.json` 中待注入的密钥字段保持为：

```text
__ORGANIZATION_API_KEY__
```

再在打包电脑上通过安全输入传给发布脚本。密钥只在本次 PowerShell 和 `electron/default-config.json` 的临时生成过程中存在；脚本结束时会删除临时文件。

```powershell
Set-Location D:\path\to\nanobot-main-1
$apiKey = Read-Host '输入部署 AI Key（不会回显）' -AsSecureString
.\desktop\package-win.ps1 -ApiKey $apiKey
Remove-Variable apiKey -ErrorAction SilentlyContinue
```

也可以直接双击 `desktop/package-win.bat`，脚本会安全询问密钥。但发布与日志排障时建议使用 PowerShell 命令，以便保留完整错误输出。

### 密钥安全规则

1. 不要把真实 Key 写入 Git、文档、截图、聊天记录或 `.env` 后再提交。
2. 不要将带真实 Key 的安装包发给不受控人员或公开上传。
3. 如需交付给外部测试人员，使用限额、可撤销的专用部署 Key；测试结束后轮换该 Key。
4. 模板必须且只能在 `providers.dashscope.apiKey` 保留唯一 `__ORGANIZATION_API_KEY__` 占位符；模板含真实 Key、第二占位符、混合凭据或其他非空 provider credential 时，`before-pack.js` 必须终止打包。
5. 当前初版包要求开箱可用，因此模板缺失或未提供受控环境 Key 都必须终止打包；不支持生成“无 Key 测试包”或依赖首次启动手工填写。
6. 安装包内置 Key 可被提取。正式包只能使用独立专用、限额、限流、可监控、可随时吊销的部署 Key；不得复用开发者或其他产品凭据。
7. 服务端代理上线后，删除客户端打包注入和内置 Key，切换为服务端代管，并立即吊销初版客户端专用旧 Key。

## 4. 正式打包步骤

1. 确认代码版本和版本号。

   安装包文件名来自 `desktop/package.json` 的 `version`。发布新版本前，先更新该版本号并提交代码；例如 `0.1.1` 会输出 `motionflow-ai-Setup-0.1.1.exe`。

2. 确认项目配置数据。

   检查位置、命令和流程文件，尤其是实际下位机动作的坐标和速度。不要为了让流程“能跑”而修改安全限位、急停或报警复位命令的定义。

   ```powershell
   Get-Content .\desktop\electron\defaults\robot_ai\positions.json
   Get-Content .\desktop\electron\defaults\robot_ai\commands.json
   Get-Content .\desktop\electron\defaults\robot_ai\flows.json
   ```

3. 运行一条完整发布命令。

   ```powershell
   Set-Location D:\path\to\nanobot-main-1
   $apiKey = Read-Host '输入部署 AI Key（不会回显）' -AsSecureString
   .\desktop\package-win.ps1 -ApiKey $apiKey
   ```

4. 等待脚本完成。它会按固定顺序执行：

   ```text
   清理旧 desktop/release2、PyInstaller 中间目录
        ↓
   webui/npm run build → robot_server/webui
        ↓
   PyInstaller → py-runtime/robot_server.exe
        ↓
   desktop/npm run build
        ↓
   electron-builder → NSIS 安装包与 win-unpacked
        ↓
   verify-release.ps1
        ↓
   smoke-packaged-robot-server.ps1
   ```

5. 只在控制台显示 `Package created and verified` 后，才视为打包成功。

> 打包过程通常需要数分钟。PyInstaller 必须重新分析并收集 Python 依赖，不能按普通前端打包的速度预期。

## 5. 产物与自动校验

成功后，产物位于 `desktop/release2/`：

| 文件/目录 | 用途 |
| --- | --- |
| `motionflow-ai-Setup-<version>.exe` | 交给测试电脑安装的 NSIS 安装包 |
| `motionflow-ai-Setup-<version>.exe.sha256` | 安装包 SHA-256 校验文件 |
| `win-unpacked/` | 免安装解包产物；用于发布前检查和定位问题，不建议作为正式交付物 |

`verify-release.ps1` 会检查：Electron 主程序、`app.asar`、Python 运行时、ZMotion SDK、默认位置/命令/流程/知识库、可执行文件元数据和安装包哈希。

`smoke-packaged-robot-server.ps1` 会复制 `win-unpacked` 到临时且带空格的路径，启动打包后的 `robot_server.exe`，再验证：

- `/health` 返回 200；
- 单页 WebUI 可以正常服务；
- `/api/library/commands` 返回 200 且包含 `data.items`；
- 配置与运行时路径在打包环境中可用。

可在需要时手动重跑两项检查：

```powershell
Set-Location D:\path\to\nanobot-main-1\desktop
.\verify-release.ps1
.\smoke-packaged-robot-server.ps1
```

在发送安装包前，在发布电脑上复算校验值：

```powershell
Get-FileHash .\release2\motionflow-ai-Setup-<version>.exe -Algorithm SHA256
Get-Content .\release2\motionflow-ai-Setup-<version>.exe.sha256
```

两者必须一致。

## 6. 其他电脑的安装与验收

1. 将 `.exe` 和对应 `.sha256` 一起传到测试电脑。
2. 在测试电脑计算 SHA-256，与发布方提供的校验文件比对；不一致时不要安装。
3. 运行安装包，选择测试安装目录，完成安装后启动 `MotionFlow AI`。
4. 首次运行检查：
   - 能进入登录页；
   - 能以操作员和工程师账号登录；
   - 命令库能打开，默认命令、默认位置和流程能显示；
   - 右侧状态栏能连接并显示实际下位机状态；
   - 真机动作前先检查急停、报警、暂停/继续、取消等状态；
   - 若使用语音，确认系统麦克风权限已允许桌面应用。
5. 在真机测试前确认 `desktop-env.json` 的控制器地址、ZMotion SDK 路径和后端模式与现场一致。不能连接时应报错，不应假装移动成功。

默认运行时位置：

```text
%APPDATA%\motionflow-ai\runtime\
├─ config.json                 # 首次从部署模板创建
├─ desktop-env.json            # 下位机地址、后端、SDK 路径等
├─ robot-server.log            # 打包服务日志
└─ robot_platform\
   ├─ positions.json
   ├─ commands.json
   ├─ flows.json
   ├─ knowledge.json
   └─ audit.jsonl
```

升级安装前请备份整个 `runtime` 目录；卸载、重装和升级都不应把用户保存的位置、命令、流程和审计记录当成默认文件覆盖。

## 7. 常见失败与处理

| 现象 | 优先检查 | 处理方式 |
| --- | --- | --- |
| 提示缺少 API Key | `package-win.ps1` 的安全输入参数 | 用 `Read-Host -AsSecureString` 传入部署 Key；不要把 Key 写进命令行历史 |
| WebUI 与开发环境不一致 | `robot_server/webui/index.html` | 必须通过 `package-win.ps1` 打包；它会先运行 `webui/npm run build` |
| PyInstaller 找不到位置种子或命令种子 | `desktop/pyinstaller/robot_server.spec` | 检查 `seed_positions.json` 和 `seed_query_table.json` 的 datas 规则 |
| 安装后命令库 500 或为空 | `%APPDATA%\motionflow-ai\runtime\robot_platform` 与 `robot-server.log` | 先检查运行时目录可写、默认库 JSON 存在且合法；再运行打包服务冒烟脚本 |
| 机械手未连接或状态栏无数据 | `desktop-env.json`、ZMotion DLL、控制器网络 | 核对 `ROBOT_AI_BACKEND`、`ROBOT_CONTROLLER_HOST`、SDK 路径和现场网络；不要用模拟结果替代真实错误 |
| 图标/版本信息不对 | `after-pack.js`、`rcedit-x64.exe`、`package.json` | 检查版本号、图标和 Windows 资源编辑工具，然后重新完整打包 |
| Windows 报未知发布者 | 安装包未签名 | 当前为内部测试包；对外发布前接入代码签名证书和签名校验流程 |

## 8. 哪些文件可以交付，哪些不能交付

可以交付：安装包 `.exe`、对应 `.sha256`、本手册、测试记录。

不能交付到公开渠道：`config.default.template.json`（若含真实凭据）、运行时 `config.json`、`desktop-env.json`、`robot-server.log`、`audit.jsonl`、任何含 API Key 或真实控制器内网地址的文件。
