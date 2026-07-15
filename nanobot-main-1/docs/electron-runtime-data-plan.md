# Electron 运行数据与零配置启动方案

## 目标

将 Robot AI 封装为 Electron 应用时，应用首次启动无需用户填写控制器、位置、流程或基础系统配置；开发、安装和便携运行均使用统一的数据根目录机制。

现有 `C:\\Users\\KY\\.nanobot` 中的 API 配置、账户密码、位置、命令、流程、审计和历史数据必须保留，不写入安装包，也不提交到 Git。

## 第一版范围与安全边界

第一版采用内置固定 AI API Key 的方式，以保证全新安装无需填写 AI 配置即可使用。该 Key 会随默认种子配置进入安装包，并在首次启动时复制到本机运行目录。

这是临时交付策略：桌面安装包和本机 `config.json` 中的 Key 可被拥有本机访问权限的人员提取。第一版暂不处理服务端代理、密钥托管、设备授权或密钥轮换；界面、日志、审计和导出仍不得明文展示该 Key。

已有用户的旧数据迁移优先于默认种子，迁移时必须保留其现有 API 配置和账户密码，禁止用内置 Key 或默认账户覆盖。

## 数据目录策略

| 运行场景 | 数据根目录 |
| --- | --- |
| 开发环境 | `nanobot-main-1\\.runtime\\nanobot` |
| Electron 安装版 | Electron `app.getPath("userData")` 下的 `NanobotRobotAI` 数据目录 |
| Electron 便携版 | 可执行文件同级的 `data\\nanobot` |

Electron 主进程在启动 Python Gateway 前确定唯一 `dataDir`。它必须保证：

```text
NANOBOT_HOME == dirname(--config)
```

`desktop-env.json` 不得覆盖 `NANOBOT_HOME`；Electron 在展开该文件后必须强制写回该变量，或在加载时过滤该字段。若 `NANOBOT_HOME` 与 `--config` 所在目录不一致，Gateway 必须拒绝启动，避免配置、位置和流程库分裂。

Python 端所有运行数据路径必须从统一路径服务解析，禁止机械手模块继续直接拼接 `Path.home() / ".nanobot"`。

## 目录内容

```text
<NANOBOT_HOME>/
├─ config.json
├─ robot_ai/
│  ├─ positions.json
│  ├─ commands.json
│  ├─ flows.json
│  ├─ users.json
│  ├─ audit.jsonl
│  ├─ knowledge.json
│  ├─ library_executions.json
│  ├─ flow_aliases.json
│  └─ nlp_standard_words.json
├─ cron/
├─ webui/
├─ media/
└─ workspace/
```

`config.json`、`users.json`、审计记录、媒体和聊天记录属于私有运行数据；不得放入 `resources`、`app.asar`、安装目录或版本控制。

## 内置默认值与首次启动

安装包携带只读种子数据：

```text
resources/defaults/
├─ config.default.json
└─ robot_ai/
   ├─ positions.json
   ├─ commands.json
   ├─ flows.json
   └─ knowledge.json
```

当目标数据目录不存在时：

1. Electron 创建目录结构。
2. 复制种子配置、正式位置、命令、流程和知识库。
3. 生成运行期 `users.json`、`audit.jsonl`、cron、WebUI、媒体和工作区目录。
4. 默认控制器地址使用 `10.168.3.21`，时区使用 `Asia/Shanghai`。
5. 控制器初始状态为未验证；真实执行仍必须遵循既有安全检查。

第一版的 `config.default.json` 包含固定 AI API Key，但不得包含任何现有用户的真实账号密码、位置数据、流程、审计、聊天记录或媒体。种子文件必须包含版本字段和完整性清单，并在 Electron 打包配置中明确纳入 `resources/defaults/`。

后续版本应将 API Key 改为服务端代理或设备授权；该升级不改变数据目录和迁移架构。

## 现有数据迁移

首次启动优先执行以下判断：

1. 新数据目录已有 `config.json`：直接使用，不迁移。
2. 新数据目录为空且旧 `C:\\Users\\KY\\.nanobot` 存在：执行可恢复的完整迁移。
3. 迁移创建独占 `migration.lock`，复制到临时目录，逐文件校验清单和关键 JSON；只有写入 `migration.complete` 后才原子切换为正式目录。
4. 迁移失败、中断、磁盘不足或源数据损坏时，保留旧目录和临时证据，允许安全重试；不得启动真实控制器。
5. 校验成功后启动 Gateway；旧目录保留为备份，不自动删除。
6. 只有旧目录不存在时，才使用内置种子数据创建全新运行目录。

因此，现有 API 配置和账户密码会原样迁移并继续生效。

## 必须改造的路径引用

以下组件需要统一通过公开的 `get_nanobot_home()`、`get_robot_ai_dir()` 或等价的配置路径服务生成路径：

- `robot_arm`、`robot_position`：位置库。
- `robot_flow`：流程和别名。
- 工程师 `robot_routes`：位置、流程、命令与审计。
- 命令库、流程库、执行历史和自然语言标准词。
- 会话兼容路径。

改造前必须通过代码搜索建立完整清单，逐项替换所有 `~/.nanobot`、`Path.home() / ".nanobot"` 与自行拼接的旧路径；不能只修改机械手模块。

所有默认路径应变为：

```python
get_nanobot_home() / "robot_ai" / "positions.json"
```

而不是：

```python
Path.home() / ".nanobot" / "robot_ai" / "positions.json"
```

## 安全与版本控制

- 在开发仓库的 `.gitignore` 中忽略 `/.runtime/` 与 `/local-runtime/`。
- 不将用户密码哈希、审计、聊天记录、媒体或机械手运行数据提交到 Git。第一版固定 API Key 属于安装包种子配置的例外，后续版本必须移出安装包。
- 应用升级只能更新程序与默认种子，不能覆盖用户数据目录。
- 迁移失败时不启动真实控制器执行，保留源目录并显示可恢复错误。
- 便携模式只能通过明确的 `--portable` 参数或 portable 标记文件启用；安装版始终使用 Electron `userData`，不得通过 EXE 路径猜测。

## 验收标准

1. 全新 Windows 用户首次打开 Electron App，无需配置即可登录、浏览默认位置和流程。
2. 有旧 `.nanobot` 的用户升级后，位置、流程、用户账户和 API 配置保持不变。
3. 安装包和 Git 仓库不包含真实 API Key、密码或运行历史。
4. 开发、安装和便携模式都通过 `NANOBOT_HOME` 使用各自独立的数据目录。
5. 真实机械手执行仍需原有安全校验，不能因首次初始化而绕过。
6. 迁移中断后可恢复且重复启动幂等；两个实例并发启动不会同时迁移。
7. 旧数据损坏或缺少关键文件时不覆盖源目录；升级后用户数据哈希不变。
8. 自动化测试覆盖 `NANOBOT_HOME`、`--config`、便携模式、默认种子、迁移中断和并发迁移。

## 实施前定稿规则（优先于前文冲突表述）

### 组织 API Key 的交付规则

第一版允许安装包携带**组织固定 API Key**，但 Git 仓库只能提交不含明文 Key 的 `config.default.template.json`。受控 CI 在打包时注入该 Key 并生成安装包内的 `config.default.json`；本地开发、测试输出和日志不得保存或打印该值。

验收标准中的“安装包和 Git 仓库不包含真实 API Key”修订为：Git 仓库和安装包不得包含任何**用户个人 API Key**；安装包可包含可撤销的组织固定 Key。该 Key 可能被提取，必须由发布方维护额度、责任人、撤销和轮换流程。后续版本应使用服务端代理或设备授权。

### 运行状态与迁移判定

不得以数据根目录是否存在或是否为空作为首启条件。唯一状态依据为：

```text
migration.lock / staging 存在
  → 优先执行恢复或安全重试；禁止启动 Gateway。

runtime.manifest.json 且 status=ready
  → 使用现有数据目录。

不存在 manifest
  → 若旧 .nanobot 存在，迁移；否则播种默认数据。
```

`runtime.manifest.json` 记录数据格式版本、种子版本、迁移来源、完成时间和关键文件哈希。Electron 缓存、日志或其他 `userData` 文件不得影响上述判定。

迁移在目标目录的同一父目录创建临时目录；校验完成后通过 Windows rename 切换到正式运行目录，再写入完成标记。不得尝试替换非空的整个 Electron `userData` 目录。

### 首启账户

全新安装自动创建：

```text
admin / 0000
operator / 1234
```

任一初始账户第一次登录后，系统必须强制修改其密码。在改密完成前，不允许进入工程师管理、配置定时任务或真实控制器执行。旧数据迁移得到的账户不触发该强制流程。

### 迁移范围

迁移策略为完整迁移旧 `.nanobot`，而非白名单迁移，以保留聊天、会话、媒体、cron、工作区、CLI 历史、配对数据及未来未知目录。

- 关键数据：`config.json`、`robot_ai/`、用户、位置、命令和流程；必须存在并可解析。
- 非关键数据：`webui/`、`media/`、`workspace/`、`history/`、`cron/`、`cli-apps/`、配对信息及未知目录；逐文件复制并记录异常，但不因单个非关键文件损坏覆盖旧目录。
- 迁移报告必须记录复制、校验、忽略和失败项；源目录始终保留，便于回滚。

### 路径服务

公开路径服务至少提供：

```python
get_nanobot_home()
get_robot_ai_dir()
get_runtime_path(*parts)
```

其根目录以最终 `--config` 的父目录为准，并校验 `NANOBOT_HOME` 与其完全一致；任何不一致都视为配置错误并拒绝启动。

## 上线前迁移与账户规则（优先于前文）

### 安装版运行根目录

Electron 安装版不得直接将整个 `app.getPath("userData")` 作为数据根目录。唯一运行根目录为：

```text
app.getPath("userData") / "runtime"
```

该 `runtime` 目录才是 `NANOBOT_HOME`，并且 `--config` 必须指向其下的 `config.json`。Electron 的缓存、GPU 数据、日志及其他 `userData` 内容不参与迁移、切换或删除。

### 无崩溃窗口的迁移提交

迁移在 `<runtime-parent>/runtime.staging.<id>` 中完成。staging 内必须先完成全部文件复制、清单/哈希校验，并写入状态为 `ready` 的完整 `runtime.manifest.json`。

父目录同时维护 `migration-state.json`，状态至少包括 `copying`、`ready_to_switch`、`switched_pending_cleanup`、`complete`。目录 rename 与状态更新后，即使进程崩溃，下一次启动也可识别已切换的运行目录并完成收尾；绝不能把它当作首次播种或再次迁移。

当新 `runtime` 目录已经包含旧版 `config.json` 而没有 `runtime.manifest.json` 时，系统必须先校验关键数据并接管该目录、补写 manifest；不得重新播种或重复迁移。

### 服务端强制首次改密

初始账户的 `must_change_password` 必须写入用户记录，并包含在登录 token/session 的服务端状态中。后端在该状态未解除前必须拒绝：

- 工程师管理接口；
- cron 创建、修改和删除；
- 所有真实控制器执行接口；
- 任何可改变机械手配置或库数据的写接口。

只允许登录、读取必要状态和修改当前账户密码。前端限制仅作为提示，不能替代后端鉴权。

### 完整迁移的文件系统边界

完整迁移保留未知普通文件和目录，但不得跟随 Windows junction、symbolic link、reparse point 或设备文件。迁移器必须：

- 检测并跳过上述特殊项；
- 配置单文件大小与迁移总容量上限；
- 将跳过项、超限项和复制失败项写入迁移报告；
- 不因非关键项被跳过而覆盖或删除旧目录；
- 因关键文件无法安全复制或校验而停止初始化并禁止真实控制器启动。
