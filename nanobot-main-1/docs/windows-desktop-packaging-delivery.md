# Windows 桌面安装包：构建、问题处理与使用说明

本文记录 Nanobot Robot AI Windows 桌面版的实际打包方式、已处理的问题、当前验证结果，以及后续构建和交付时的操作步骤。

适用项目目录：`nanobot-main-1`。当前构建目标为 **Windows 10/11 x64**。

## 1. 最终交付物

一次成功构建后，在下列目录取交付文件：

```text
desktop/release-build4/
├─ nanobot-robot-ai-Setup-<版本号>.exe
└─ nanobot-robot-ai-Setup-<版本号>.exe.sha256
```

对外或给其他电脑安装时，只发送这两个文件；不要发送 `win-unpacked` 里的单个 EXE。后者依赖同目录的 Electron、Python Gateway、DLL 和资源文件，仅用于构建机诊断。

当前已验证的安装包为：

```text
desktop/release-build4/nanobot-robot-ai-Setup-0.1.0.exe
SHA-256: d583b02c5436f51479aca215419626fe9df95373fc4fc92e3620dcc56ab5396a
```

## 2. 打包内容和流程

构建入口是：

```text
desktop/package-win.bat
```

也可从 `nanobot-main-1` 根目录执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\desktop\package-win.ps1
```

脚本会以隐藏输入方式要求输入组织 API Key，并按以下顺序执行：

1. 确认 Python 构建环境、WebUI、ZMotion DLL、默认机器人数据、图标和资源编辑器都存在。
2. 删除旧的 PyInstaller 输出和旧的 `release-build4` 输出。
3. 用 PyInstaller 重建 Python Gateway 为 `nanobot_gateway.exe` 及其运行时目录。
4. 编译 Electron 主进程和预加载脚本。
5. 用 electron-builder 生成 x64 NSIS 安装程序。
6. 将默认配置、机器人位置/命令/流程/知识库、Gateway 和 ZMotion SDK 一并放入安装包。
7. 对生成内容做结构、JSON、`app.asar`、程序版本信息检查，并生成 SHA-256 文件。
8. 将完整解包程序复制到含空格的临时目录，以独立运行时数据启动 Gateway 冒烟测试。

任一步失败都会返回非零退出码，不能把不完整的输出当作正式安装包。

## 3. 本次遇到的问题和处理方式

| 问题 | 原因 | 处理方式 | 防回归措施 |
| --- | --- | --- | --- |
| 其他电脑启动 Gateway 报 `No module named '_socket'` | 仅复制 EXE 或旧的 Python 打包输出不完整，扩展模块/DLL 没有得到完整交付。 | 每次打包先重新执行 PyInstaller，并把完整 `py-runtime` 作为 Electron 资源带入。 | 发布校验要求 `_socket.pyd`、`_ssl.pyd`、`_asyncio.pyd`、`python311.dll`、ZMotion DLL 等关键文件存在；再运行 Gateway 冒烟测试。 |
| Git 仓库包含大量 `release-build4` 生成文件 | 生成物被错误纳入版本控制，体积大且容易与源码不同步。 | 停止跟踪已有生成物，并将 `release-build4/` 和本地 `electron.exe` 写入忽略规则。 | 生成包只保留在本机构建目录，Git 测试会阻止其重新被纳入。 |
| Electron Builder 因图标资源失败或应用图标不正确 | Windows 主程序需要可用的 `.ico` 图标资源。 | 提供 `nanobot-app-icon.ico`，并在构建前检查该资源。 | 发布配置测试校验图标和尺寸。 |
| electron-builder 下载 `winCodeSign` 后解压失败 | 其缓存包含 macOS 符号链接；普通 Windows 账户通常没有创建符号链接的权限。 | 关闭 electron-builder 的自动资源编辑，改为在 `afterPack` 使用项目自带的 Windows `rcedit-x64.exe` 写入图标和版本信息。 | 构建前检查本地资源编辑器；不再依赖该有符号链接的缓存。 |
| 安装包已生成，但验证脚本报 `Join-Path` 的 `Path` 为空 | Windows PowerShell 5 用 `-File` 执行时，参数默认值阶段 `$PSScriptRoot` 为空。 | 把 `release-build4` 默认路径的计算移到 `param` 之后执行。 | 测试通过新的 `powershell.exe -File` 进程覆盖该调用方式。 |
| 验证脚本误判默认 JSON 无效 | Windows PowerShell 5 对 UTF-8 无 BOM 文本的默认读取编码不可靠。 | 使用明确的 UTF-8 无 BOM 读取方式后再执行 JSON 解析。 | 测试夹具采用非 ASCII 的 UTF-8 无 BOM JSON 验证。 |
| 只运行 `win-unpacked/Nanobot Robot AI.exe` 或单独复制它无法工作 | Electron 主 EXE 必须和 `resources`、DLL、语言包等同目录文件配套。 | 统一以 NSIS Setup 安装包交付。 | 文档和发布校验明确区分安装包与诊断目录。 |

## 4. 当前已完成的验证

对现有 `0.1.0` 安装包已完成：

- 前端构建成功；
- Electron 相关测试、发布规则测试、发布配置测试、发布验证脚本测试和 Gateway 冒烟脚本测试通过；
- Python 的 Electron 运行时数据测试通过（6 项）；
- 实际安装包的关键文件、默认 JSON、`app.asar`、版本元数据和 SHA-256 校验通过；
- 解包程序在带空格的临时路径下，通过独立运行时数据完成 Gateway 启动冒烟测试。

当前主程序没有配置 Windows 代码签名证书，因此签名状态是 `NotSigned`。这不影响程序功能，但 Windows SmartScreen 可能显示“未知发布者”。

## 5. 后续如何重新打包

### 5.1 构建机前置条件

构建机需要具备：

- Windows x64；
- 项目完整源码及已安装的 `desktop/node_modules`；
- `desktop/.build-venv` Python 构建环境；
- 已构建的 WebUI：`nanobot/web/dist/index.html`；
- `vendor/zmotion` 下的控制器 SDK 文件；
- 网络可访问 Electron/NSIS 首次构建需要下载的缓存资源；
- 可用的组织 API Key。

### 5.2 操作步骤

1. 在构建机更新并检查源码。
2. 双击 `desktop/package-win.bat`。
3. 在提示处输入组织 API Key；输入过程不会回显。
4. 等待脚本显示 `Package created and verified`，不要在中途关闭窗口。
5. 到 `desktop/release-build4` 取新的 Setup EXE 和 `.sha256` 文件。
6. 使用下面的命令核对哈希值，确认与 `.sha256` 文件第一列完全一致：

```powershell
Get-FileHash .\nanobot-robot-ai-Setup-<版本号>.exe -Algorithm SHA256
```

7. 每次准备正式发放前，都至少在一台未安装 Python、Node.js 和本项目的干净 Windows 10 x64 电脑，以及一台干净 Windows 11 x64 电脑上安装验收。

### 5.3 API Key 安全说明

构建时输入的组织 API Key 会写入安装包默认配置，供离线安装的应用使用。因此 Setup EXE 和它的副本都应按敏感文件管理，只发给获授权人员。

若密钥泄露、人员变更或不再使用，应在服务端撤销或轮换该 Key，然后重新构建并替换已发放的安装包。

## 6. 接收方如何安装和使用

1. 接收 Setup EXE 和对应 `.sha256` 文件。
2. 先核对 SHA-256；不一致时不要安装。
3. 双击 Setup EXE，选择安装目录后完成安装。
4. 从开始菜单或桌面快捷方式启动 **Nanobot Robot AI**。
5. 首次使用时，在登录页按现场配置控制器地址和连接模式，再使用已分配账户登录。
6. 普通操作请在模拟模式或通过安全检查后执行；连接真实控制器前确认网络、电源、急停和现场安全状态。

安装包不要求目标电脑预先安装 Python、Node.js 或项目源码。

## 7. 发布前检查清单

- [ ] `package-win.bat` 完整执行并显示验证成功。
- [ ] Setup EXE 与 `.sha256` 文件一同保存。
- [ ] 已在构建机重新计算 SHA-256 并一致。
- [ ] 已在干净 Windows 10 x64 和 Windows 11 x64 电脑完成安装、登录、命令库/流程库、工程师页面和 Gateway 基本验收。
- [ ] 已验证卸载和覆盖升级不会破坏用户运行时数据。
- [ ] 若对外发放，已完成代码签名或已接受未签名包会被 SmartScreen 提示的风险。
- [ ] 已确认接收方具备使用嵌入 API Key 的授权。

## 8. 常用排查命令

只检查已有安装包，不重新打包：

```powershell
cd .\desktop
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\verify-release.ps1
```

只运行已解包程序的 Gateway 冒烟检查：

```powershell
cd .\desktop
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\smoke-packaged-gateway.ps1
```

以上两个命令均应返回退出码 `0`。如果重新打包在“创建 Windows 安装程序”阶段失败，保留完整错误输出，不要把旧的 `release-build4` 目录当作新的构建结果。
