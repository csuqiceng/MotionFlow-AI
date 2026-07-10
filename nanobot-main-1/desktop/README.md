# Nanobot Robot AI — Desktop (Electron + PyInstaller)

打包 nanobot Robot AI(React WebUI + Python gateway + robot_ai 机械臂链路)成
Windows 双击即用的桌面应用。Electron 作壳,内嵌 PyInstaller 打包的 gateway。

## 架构

```
nanobot-robot-ai.exe (Electron)
 ├─ 首启:无 provider 配置 → 弹向导窗口(写 %APPDATA%\…\config.json + desktop-env.json)
 ├─ pickFreePort() → channelPort(前端/WS)+ healthPort(/health)
 ├─ patchRuntimeConfig():写 channels.websocket.port / gateway.port / 清空 secret
 ├─ spawn resources/py-runtime/nanobot_gateway.exe --config <APPDATA>/config.json
 ├─ 轮询 http://127.0.0.1:<channelPort>/webui/bootstrap → 200
 └─ BrowserWindow.loadURL("http://127.0.0.1:<channelPort>/")   # 同源,无 secret
退出 → taskkill /PID /T /F 杀整棵 gateway 子进程树
```

关键:gateway 监听**两个端口** —— `channels.websocket.port`(前端 fetch/WS/REST)与
`gateway.port`(仅 `/health`)。前端连前者。详见记忆 `gateway-port-secret-architecture`。

## 构建(一条命令)

需要 Windows + Python 3.11+ + Node 18+(可选 bun)。

```powershell
pwsh ./desktop/build-desktop.ps1
```

产出:`desktop/release/nanobot-robot-ai-Setup-<version>.exe`(NSIS 安装包)。

脚本步骤:建/刷新 `desktop/.build-venv` → `pip install -e ".[api,pdf]" pyinstaller` →
`pyinstaller nanobot.spec` → `npm install` → `tsc` → `electron-builder --win nsis`。

安装后布局:`%LOCALAPPDATA%\Programs\nanobot-robot-ai\nanobot-robot-ai.exe` +
`resources\{app.asar, py-runtime\…}`。

## 用户数据

`%APPDATA%\nanobot-robot-ai\`(由 `NANOBOT_HOME` 重定向 + `app.setPath`):
`config.json`、`desktop-env.json`、`workspace\`、`robot_ai\`、`run\gateway.json`、`logs\`。

设置 → 打开配置目录(IPC `desktop:open-config-dir`)直接打开此目录。

## ZMotion DLL

**不内嵌**(许可未知,且用户用自己的版本)。只读模式(`zmotion_readonly`)下,首启
向导里填 ZMotion Wrapper 路径 + DLL 目录,写入 `desktop-env.json`,gateway 运行时经
`ROBOT_ZMOTION_WRAPPER_PATH` / `ROBOT_ZMOTION_DLL_DIR` 加载。默认 `simulation` 模式
无需任何 DLL。

## 开发模式

```bash
cd desktop
npm install
npm run dev        # ELECTRON_DEV=1:spawn venv python -m nanobot gateway(非 PyInstaller)
```

dev 模式 Electron spawn 的是 `desktop/.build-venv` 的 python(跑 live nanobot 源码),
便于改 Python 即时生效。前端仍由 gateway 同源服务(不走 vite dev server,以保持
bootstrap/静态/SPA 同源)。

## 验证(端到端)

**Phase A — 无硬件**:
1. 干净 Windows(无 Python/Node)装 Setup.exe。
2. 首启向导:选 provider + 填 key + model,模式 simulation。
3. 窗口开,聊天能发消息收到回复。
4. 任务管理器结束 app → `nanobot_gateway.exe` 及子进程全消失(taskkill /T 验证)。
5. 重启无端口冲突,`run/gateway.json` 自愈。
6. 设置 → 打开配置目录 → 确认 `config.json`/`workspace`/`logs` 齐全。

**Phase B — 硬件(ZMotion 只读)**:向导填 DLL 路径 + controller host,模式
`zmotion_readonly`,聊天触发运动,确认 DLL 从用户路径加载。

**Phase C — 韧性**:双实例第二者聚焦已有窗口;删 `config.json` 再保存不崩。

## 排障

- **gateway 起不来**:看 `%APPDATA%\nanobot-robot-ai\logs\gateway.log` 或错误弹窗里的
  recent output。常见:provider 未配(build_provider_snapshot 报错)→ 重开向导。
- **端口冲突**:本机若已有 dev gateway 占 8765,Electron 会自动 pick 空闲端口,不冲突。
- **bootstrap 401**:config 里 `channels.websocket.token_issue_secret` 非空;桌面 app 每次
  启动会 `patchRuntimeConfig` 清空它走 localhost-only。

## 已知限制 / TODO

### NSIS `Setup.exe` 在普通 Windows 账号下可能失败

electron-builder 解压 winCodeSign 缓存时要创建符号链接,普通 Windows 账号无此权限,
报 `Cannot create symbolic link ... 客户端没有所需的特权`。解决(任一):
- 开启开发者模式:`ms-settings:developers`(设置 → 隐私和安全性 → 开发者选项),再重跑 `npm run dist`。
- 或以管理员身份运行构建终端。

注意:**此错误下 `release/win-unpacked/` 仍会完整产出**(含 gateway + app.asar),可直接
运行 `release/win-unpacked/nanobot-robot-ai.exe`,或把整个 `win-unpacked/` 目录 zip 分发。

### 其他

- Win32 Job Object(`KILL_ON_JOB_CLOSE`)+ 崩溃自动重启上限未实现(`main.ts` 标注 TODO);
  当前 `taskkill /T` 覆盖正常退出,Electron 异常崩溃时 gateway 可能残留。
- 安装包未签名(Windows SmartScreen 会提示)。
- tiktoken 离线缓存:`--collect-all tiktoken` 已含 BPE 文件,但极端情况下首跑可能尝试
  联网;断网环境若 hang,设 `TIKTOKEN_CACHE_DIR` 指向内置副本。
