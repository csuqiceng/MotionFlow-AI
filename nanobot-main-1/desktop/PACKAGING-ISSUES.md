# MotionFlow AI 打包记录

> 本文前半部分是 2026-07-24 重构前的历史故障记录，其中提到的 gateway、`nanobot.spec` 和 `robot_ai` 均不再是当前产品结构。当前构建与验收步骤以 [BUILD-GUIDE.md](BUILD-GUIDE.md) 和 `package-win.ps1` 为准；本文仅保留历史排障背景。

## 环境

- 系统：Windows 10
- Python：系统默认 3.10.9（不满足 >=3.11 要求），使用 3.14.6 构建成功
- Node.js：Electron 33 + electron-builder 24

---

## 问题 1：PyInstaller spec 文件缺失

**现象**：`desktop/pyinstaller/` 目录下没有 `nanobot.spec`，`build-desktop.ps1` 引用了它导致构建脚本无法执行。

**修复**：创建了完整的 `nanobot.spec`，包含：
- hiddenimports（`uvloop`、`robot_ai` 子模块等）
- datas（robot_ai defaults、ZMotion vendor）
- excludes（tkinter 等桌面 GUI 库）

---

## 问题 2：before-pack.js 在无 API Key 时直接报错退出

**现象**：`scripts/before-pack.js` 检测到 `NANOBOT_ORGANIZATION_API_KEY` 环境变量未设置时抛出 `Error`，导致 electron-builder 打包流程中断。

**修复**：改为无 key 时使用模板原样生成 default-config.json，打印 warning 但不阻塞打包。首运行时会弹出配置向导。

---

## 问题 3：main.ts 硬编码 Python 路径

**现象**：`resolvePython()` 函数内写死了 `C:/Users/KY/Desktop/...` 的绝对路径，在其他机器上无法找到 Python。

**修复**：改为基于 `app.getAppPath()` 的相对路径解析，兼容开发模式和打包模式。

---

## 问题 4：electron-builder.yml 输出目录残留

**现象**：`output: release-build4` 是之前测试时遗留的目录名。

**修复**：改为 `output: release2`（后续可改为 `release`）。

---

## 问题 5：Python 版本不匹配

**现象**：系统 PATH 默认 Python 是 3.10.9，项目 `pyproject.toml` 要求 `>=3.11`。用 3.10 创建的 venv 中 `import tomllib` 会失败（3.11+ 才有）。

**修复**：使用 `C:\Users\a\AppData\Local\Programs\Python\Python314\python.exe`（3.14.6）创建专用构建 venv `.build-venv`，安装所有依赖后构建成功。

---

## 问题 6：PyInstaller 打包缺少 WebUI 前端静态资源

**现象**：Electron 启动后页面空白，gateway 的 `GET /` 返回 404，但 `GET /webui/bootstrap` 正常返回 200。

**根因**：`nanobot/web/dist/`（前端编译产物，200+ 文件）未被 `nanobot.spec` 的 datas 收录。`_default_webui_dist()` 通过 `nanobot.web.__file__` 定位 dist 目录，PyInstaller 打包后该目录不存在。

**修复**：在 `nanobot.spec` 的 datas 中添加：
```
(REPO_ROOT / "nanobot" / "web" / "dist") -> nanobot/web/dist
```

---

## 问题 7：PyInstaller 打包缺少 Jinja2 提示词模板

**现象**：登录后发送对话消息，AI 回复 "Sorry, I encountered an error."。

**根因**：`nanobot/templates/` 目录（含 agent 系统提示词模板，如 `platform_policy.md`、`identity.md` 等）未被 PyInstaller 打包。gateway 运行时报错：
```
jinja2.exceptions.TemplateNotFound: 'agent/platform_policy.md' not found in search path
```

**排查过程**：
1. API Key 验证通过（DeepSeek API 正常）
2. 添加 gateway 日志输出（`main.ts` 中 `onOutput` 回调写 `gateway.log`）
3. 日志明确显示 `TemplateNotFound` 异常

**修复**：在 `nanobot.spec` 的 datas 中添加：
```
(REPO_ROOT / "nanobot" / "templates") -> nanobot/templates
```

---

## 问题 8：Gateway 日志不可见

**现象**：gateway 运行时错误输出到 stdout/stderr，被 Electron `GatewaySupervisor` 捕获后仅保留在内存中（`recentOutput`），不写入文件，难以排查运行时问题。

**修复**：在 `main.ts` 中为 `GatewaySupervisor` 添加 `onOutput` 回调，将每行日志追加写入 `{dataDir}/gateway.log`。

---

## 最终 nanobot.spec datas 列表

```python
datas=[
    # WebUI 前端编译产物
    (str(REPO_ROOT / "nanobot" / "web" / "dist"),
     os.path.join("nanobot", "web", "dist")),
    # Jinja2 提示词模板
    (str(REPO_ROOT / "nanobot" / "templates"),
     os.path.join("nanobot", "templates")),
    # Robot AI 默认数据（flows, knowledge, positions, commands）
    (str(REPO_ROOT / "desktop" / "electron" / "defaults" / "robot_ai"),
     os.path.join("defaults", "robot_ai")),
    # ZMotion 运动控制 SDK
    (str(REPO_ROOT / "vendor" / "zmotion"),
     os.path.join("vendor", "zmotion")),
],
```

---

## 默认登录凭据

| 角色   | 用户名   | 密码 |
|--------|----------|------|
| 工程师 | admin    | 0000 |
| 操作员 | operator | 0000 |

凭据存储在 `{AppData}/motionflow-ai/runtime/robot_ai/users.json`，首次运行时由 `runtime_data.py` 自动创建。密码可通过工程师设置 UI 或 `nanobot users set-bootstrap-password` 命令修改。

---

## 产出文件

- NSIS 安装程序：`desktop/release2/motionflow-ai-Setup-0.1.0.exe`
- 免安装版：`desktop/release2/win-unpacked/MotionFlow AI.exe`

---

## 2026-07-24：机器人服务器重构的打包迁移状态

本节记录重构分支的当前状态；它不代表旧 gateway 包仍是发布目标。

### 已完成的架构迁移

- Electron 只负责启动和监控 `robot_server.exe`，不再启动 `nanobot gateway`。
- 桌面端与本地服务只使用一个端口；窗口直接加载该端口的机器人单页 UI。
- PyInstaller 新入口为 `pyinstaller/robot_server_launcher.py`，规格文件为
  `pyinstaller/robot_server.spec`，静态资源改为 `robot_server/webui/`。
- 退出流程会终止 `robot_server.exe` 进程树；日志文件名迁移为
  `robot-server.log`。
- 发布脚本、验证脚本和冒烟脚本已迁移到 `robot-server` 命名，并不再假定
  固定的 `python311.dll` 文件名。

### 已通过的自动检查

- Electron TypeScript 编译检查（使用临时输出目录，未改写被占用的 `build/`）。
- `packaged-robot-server-launch.test.js`。
- `package-win-script.test.ps1`、`release-config.test.ps1`、
  `smoke-packaged-robot-server-script.test.ps1`、`verify-release.test.ps1`。
- `robot_server.spec` 的干净 PyInstaller 构建（Python 3.14.6，182 秒）。
- 新建 `robot_server.exe` 的独立冒烟：`/health`、`/api/robot/status` 与
  打包的单页 HTML 均返回成功。

### 已关闭的 AI 依赖收敛风险

`AgentLoop` 现支持注入工具装载器。桌面 `AgentRuntime` 使用
`RobotToolLoader`，只注册 `robot_arm`、`robot_flow`、`robot_knowledge` 和
`robot_position`，不再扫描通用工具包。PyInstaller 规格也排除了当前产品没有
UI 入口的文档解析、图像和 Bedrock 依赖，最终收集文件从约 2,600 项降为 692 项。

该桌面发行版的 AI 输入是文本提示，并使用 OpenAI-compatible 提供商路径；若未来
需要附件解析或 Bedrock，必须先恢复相应 UI/API 能力、依赖和打包测试，不能只从
配置中切换提供商。

### 尚未执行的发布步骤

完整 NSIS 构建仍需由发布负责人提供组织 API Key，并且需要关闭当前占用
`desktop/build/` 的 Electron 进程后运行 `package-win.ps1`。这不是源码或
PyInstaller 风险；在安装包真实生成后，还应执行
`smoke-packaged-robot-server.ps1` 对 `win-unpacked` 产物进行最终验证。
