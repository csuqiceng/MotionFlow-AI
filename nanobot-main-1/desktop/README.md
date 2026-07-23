# MotionFlow AI Windows 桌面版

## 支持范围

- 正式支持 Windows 10/11 x64。
- 目标电脑不需要安装 Python、Node.js 或项目源码。
- Windows 7/8/8.1、32 位 Windows 和 ARM64 暂不在正式支持范围。

## 一键打包

构建电脑需要准备项目的 `.build-venv`、Node.js 依赖和已编译的 WebUI。双击 `package-win.bat`，或在项目根目录运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\desktop\package-win.ps1
```

脚本会安全读取组织 API Key，并按以下顺序执行：

1. 清理旧的 PyInstaller 和 Electron 生成目录；
2. 重新构建 Python Gateway；
3. 编译 Electron 主进程；
4. 生成 Windows x64 NSIS 安装包；
5. 检查 `_socket.pyd`、`_ssl.pyd`、`_asyncio.pyd`、Python DLL、ZMotion DLL、默认数据和 `app.asar`；
6. 将完整应用复制到含空格的临时目录，使用独立运行数据启动 Gateway 冒烟测试；
7. 生成并复核安装包的 SHA-256 文件。

任何一步失败，脚本都会以失败状态退出，不会把不完整的安装包报告为成功。

## API Key 注意事项

打包时输入的组织 API Key 会写入安装包的默认配置。安装包及其副本应按敏感文件管理，只提供给授权人员。密钥泄露或不再使用时，应在服务端立即撤销或轮换。

## 正式交付文件

只向其他电脑提供：

```text
desktop/release-build4/motionflow-ai-Setup-<version>.exe
desktop/release-build4/motionflow-ai-Setup-<version>.exe.sha256
```

不要单独复制 `win-unpacked/MotionFlow AI.exe`。`win-unpacked` 依赖同目录下的 `resources`、DLL 和运行时文件，仅用于本机构建诊断。

接收方可以运行下面的命令核对安装包：

```powershell
Get-FileHash .\motionflow-ai-Setup-<version>.exe -Algorithm SHA256
```

结果应与 `.sha256` 文件中的值一致。

## 未签名内部包

没有配置 Windows 代码签名证书时，安装包属于未签名内部测试包。SmartScreen 可能显示“未知发布者”，企业安全策略也可能直接阻止运行。

正式对外分发前，应配置 OV、EV 或 Azure Trusted Signing，并在签名后的最终安装包上重新执行完整性验证和干净电脑验收。

## 干净电脑验收

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

## 运行数据

默认运行数据位于：

```text
%APPDATA%\motionflow-ai\runtime
```

使用 `--portable` 启动时，运行数据位于应用程序同级的 `data\nanobot`。构建输出和安装包不应包含开发电脑现有的用户运行数据。
