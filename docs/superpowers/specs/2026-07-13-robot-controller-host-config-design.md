# 下位机控制器 IP 设置（登录页）— 设计

日期：2026-07-13
状态：已确认（含运行时修正），待实施计划
关联：切片② 登录页（Plan B F2 `LoginPage`，已实现·待复核）；`robot_ai/backends/factory.py`（`RobotBackendConfig`）、`zmotion_shared_client.py`（共享 ZAux 单例）、`robot_ai/bridge.py`（`RobotBridge` 诊断）；memory `zmotion-gateway-shared-client`（连接管理坑）、`gateway-port-secret-architecture`（localhost-only）、`appliance-mode-packaging`（default-config）。

## 1. 目标与边界

把"下位机（ZMotion 控制器）IP"从硬编码（`RobotBackendConfig.controller_host` 默认 `10.168.3.21` / env `ROBOT_CONTROLLER_HOST`）改为**可在登录页配置**：预填当前值、可测试连通性、变更时保存并切换连接目标。控制器 IP 是**网关级单例**（一台 gateway 一个控制器，共享 ZAux 连接），登录页只是"设置入口"。

**In scope：**
- 登录页加 IP 输入框（IPv4，预填当前 config 值，从未配过则空）+「测试连接」按钮 + 状态指示。
- 三个独立 GET 端点（gateway-token 门控，pre-auth，走 `X-Nanobot-Robot-Body`）：
  - `GET /api/robot/controller-host` — 取当前 host（+ backend mode）。
  - `GET /api/robot/controller-host/test` — 临时 ZAux 连通性测试，**不动共享单例**。
  - `GET /api/robot/controller-host/apply` — 持久化 + 切换连接目标（**不要求控制器在线**）。
- 配置持久化：`config.json` 新字段 `robot_ai.controller_host`；优先级 `config.json → ROBOT_CONTROLLER_HOST → 空`；**移除工厂默认 `10.168.3.21`**。
- 运行时修正：新增**受锁保护**的 `shared.reconfigure(host, sdk_config)`（断开旧 ZAux → 清 client → 写新 host/config → 下次轮询连接）；`RobotBackendConfig`/`RobotBridge` 的有效 host 同步更新。
- simulation 模式：不要求 IP，登录不被缺 IP 阻断。

**Out of scope：**
- engineer-only / 网络白名单门禁（localhost-only 下 pre-auth 可接受；网关暴露到非 localhost 时再加）。
- 多控制器 / 每用户控制器（单例决定不支持）。
- 连接成功后回显控制器详细信息（只通/不通）。
- 把 host 塞进 `/webui/bootstrap`（边界分离：bootstrap = 传输凭证；controller-host = 机器人域）。

**硬约束：** 全程 no-git、零进程管理（[[no-git-commit-unified-later]]、[[no-process-management-without-approval]]）；apply/test 端点不启动/不杀 gateway；测试用 mock ZAux（pytest）+ vi.mock（vitest）。

---

## 2. 登录页 UX（扩 `LoginPage`）

```
┌──────────────────────────────┐
│     nanobot 机械手控制台      │
│  ┌─────────┐ ┌─────────┐      │
│  │■操作员■ │ │  工程师 │      │
│  └─────────┘ └─────────┘      │
│  用户名 [_______________]     │
│  密  码 [_______________]     │
│  下位机IP [10.168.3.21__] [测试] ●  ← 仅 real 模式显示；sim 模式整行隐藏
│                              │
│  [         登 录          ]   │
└──────────────────────────────┘
```

- **加载**：登录页 mount 后（bootstrap 完）调 `GET /api/robot/controller-host` 预填 IP 框 + 取 `backend_mode`。`backend_mode==="simulation"` → 隐藏整行 IP + 测试按钮，登录不要求 IP。
- **预填**：当前 config 的 `controller_host`；从未配过 → 空（无 placeholder、无工厂默认）。
- **测试连接**：点「测试」→ 调 `test` 端点 → 状态点：检测中(灰)/通(绿)/不通(红)。**不通不阻止登录**（用户可离线配置后登录）。
- **登录提交**：`onSubmit {username, password, role, controller_host}`。App 在 login 前：若 `controller_host` 与当前 config 不同 → 调 `apply`（保存+切换目标，**不要求在线**）→ 再走 `fetchLogin`。IP 未变 → 跳过 apply。real 模式下 IP 空 → 客户端置灰登录（必填）；sim 模式 → 不要求。
- **错误态**：test 失败仅提示；apply 失败（持久化/重连异常）→ 登录页报"控制器配置失败，请重试"，**不阻止**用户重试或改 IP。

---

## 3. 端点契约（均 GET，gateway-token 门控，pre-auth）

所有三个端点：`Authorization: Bearer <ws_token>`（无 user-token，登录前调用）。test/apply 带 body：`X-Nanobot-Robot-Body: <json>`。响应 `Cache-Control: no-store`。挂载在 `nanobot/api/robot_routes.py` + `nanobot/webui/ws_http.py`（沿用既有 robot 路由分发）。

### `GET /api/robot/controller-host`
返回当前 host + 模式，供登录页预填/决定是否显示 IP 行。
```json
{ "ok": true, "data": { "host": "10.168.3.21", "backend_mode": "zmotion_readonly" | "simulation" | "unknown" } }
```
- `host`：当前有效 host（config → env → 空 `""`）。
- `backend_mode`：`robot_ai.execution.mode.EXECUTION_MODE` 或后端类型；`"simulation"` → 登录页隐藏 IP 行。

### `GET /api/robot/controller-host/test`  (+ `X-Nanobot-Robot-Body: {"host":"..."}`)
连通性测试。**临时客户端，finally disconnect，绝不触碰共享单例。**
- **localhost 强制**：服务端 `_is_localhost(connection)` 为假 → **403**（不靠"部署通常 localhost"假设；remote 请求拒）。
- 校验 `host`：`ipaddress.IPv4Address(host)`（非 IPv4 → 400 `{error:{code:"invalid_host"}}`）。
- 开临时 `ZMotionSdkClient(host=test_host)` → `ZAux_OpenEth` → **`finally: client.disconnect()`**（确保断开，防漏连接堵会话表）。
- 返回 `{ok:true, data:{host:<canonical>, connected:true|false}}`。sim 模式被调 → `{connected:false, reason:"simulation_mode"}`（前端正常不在 sim 模式显示测试按钮）。
- **绝不调** `shared.configure`/`shared.reconfigure`，不开共享连接。

### `GET /api/robot/controller-host/apply`  (+ `X-Nanobot-Robot-Body: {"host":"..."}`)
保存 + 切换连接目标。**不要求控制器在线**（不在此时开新连接；下次状态轮询连）。
```json
{ "ok": true, "data": { "host": "10.168.3.21", "applied": true } }
```
- **localhost 强制**：`_is_localhost(connection)` 为假 → **403**。
- 校验 `host`：`ipaddress.IPv4Address(host)`（非 IPv4 → 400 `{error:{code:"invalid_host"}}`）。
- **持久化**：`config.json` `robot_ai.controller_host = host`（`atomic_write_json`；写规范形式）。
- **reconfigure 共享客户端**：`shared.reconfigure(host, current_sdk_config)`（见 §4）。
- **同步有效 config**：更新 `RobotBackendConfig.controller_host` + `RobotBridge` 有效配置（诊断/UI 不显示旧 IP）。
- 与当前 host 相同 → 幂等 no-op（仍返 200 `{applied:false}`）。
- sim 模式：仅持久化 host 到 config（供切回 real 模式用），不 reconfigure（无共享 ZAux）；返 `{applied:true, host}`。

---

## 4. 后端改动

### 4.1 配置（`RobotBackendConfig` / config schema）
- `nanobot/config/schema.py`：`robot_ai` 段加 `controller_host: str = ""`（默认空，**不**保留 `10.168.3.21`）。
- `robot_ai/backends/factory.py:36`：`RobotBackendConfig.controller_host` 默认改 `""`（去硬编码）。
- `from_env()` 优先级（factory.py:41-45）：`config.robot_ai.controller_host`（非空）→ `ROBOT_CONTROLLER_HOST` env（非空）→ `""`。即 **config.json → env → 空**。
- 持久化写：`nanobot/config/loader.py` 的既有 config 写入路径 + `atomic_write_json`（沿用切片① outbox 模式无关；直接写 config.json）。

### 4.2 `shared.reconfigure(host, sdk_config)`（**运行时修正，核心**）
`robot_ai/backends/zmotion_shared_client.py`：现有 `configure(host, sdk_config)` **只改 `_host`/`_sdk_config`，不断开既有 `_client`**（连接还在用旧 host）。新增**受锁保护**的 reconfigure，且**整段（含旧连接 `disconnect()`）在锁内完成**，杜绝"旧连接尚未断开、并发 `get()` 已建新连接"的窗口（否则控制器残留双连接 / 3402）：
```python
def reconfigure(host: str, sdk_config: ZMotionSdkConfig) -> None:
    """Atomically switch the shared client to a new host.

    Holds _LOCK for the WHOLE operation including the old connection's
    disconnect(), so no concurrent _get_client() can create a new connection
    while the old one is still being torn down. Config change is low-frequency
    → safety over throughput (brief lock hold acceptable).
    """
    with _LOCK:
        old = _client
        if old is not None:
            old.disconnect()    # ZMotionSdkClient.disconnect() — NOT close()
        _client = None
        _host = host
        _sdk_config = sdk_config
```
- **`disconnect()` 在锁内**：旧连接断开后才清 `_client`、设新 host；`_get_client()` 取同一把锁，reconfigure 释放前不会跑 → 不存在"旧未断 + 新已建"窗口。
- `ZMotionSdkClient` 的方法是 **`disconnect()`**（**不是** `close()`）。
- 若不想整段持锁，等价方案：`_reconfiguring` 标志 + `threading.Condition`（`_get_client()` 在 `_reconfiguring` 时 `wait()`，reconfigure 完成后 `notify_all()`）。本切片采用更简单的"持锁完成 disconnect"。
- `_LOCK`：复用共享客户端既有 per-operation 锁（或专用 `threading.Lock`），与 `_get_client()`/运动写入互斥。
- 区别于 `_reset_state_for_tests`（测试专用）；reconfigure 是生产路径。

### 4.3 `RobotBridge` / `RobotBackendConfig` 同步（frozen）
- `RobotBackendConfig` 是 **frozen dataclass**，**不能原地改** `controller_host`。
- apply 后用 `dataclasses.replace(self._backend_config, controller_host=host)` 生成新配置对象替换 `RobotBridge` 持有的引用；或封装为 `RobotBridge.reconfigure_controller_host(host)`。使 `bridge.py:370` 诊断/UI 显示新 IP（不留旧 IP）。
- `_status_backend`（`robot_routes.py:336`）是模块全局，`use_shared=True` 走共享单例——reconfigure 后自动跟随新 host，无需重建。

### 4.4 IPv4 校验 + 规范化
- 用 `ipaddress.IPv4Address(host)`：构造抛 `ValueError` → 400 `invalid_host`；通过则 `str(...)` 得规范形式（如 `010.168.003.021` → `10.168.3.21`）。
- 拒绝主机名 / IPv6 / 空 / 带端口。
- 持久化与 reconfigure 用规范形式。

---

## 5. 前端改动（Plan B `LoginPage` 扩展 + `bootstrap.ts`/新 `robot-api` 调用）

- `webui/src/components/LoginPage.tsx`：
  - props 加 `controllerHost: string`、`backendMode: "simulation" | "zmotion_readonly" | ...`、`onTestHost: (host) => Promise<{connected:boolean}>`、`onSubmit` 带 `controller_host`。
  - `backendMode==="simulation"` → 不渲染 IP 行；否则渲染 IP `Input`（预填 `controllerHost`，空起始）+「测试」`Button` + 状态点。
  - real 模式 IP 空 → 登录钮置灰。
- `webui/src/lib/bootstrap.ts` 或新 `webui/src/lib/controller-host.ts`：`fetchControllerHost(wsToken)`、`testControllerHost(wsToken, host)`、`applyControllerHost(wsToken, host)`（GET + `X-Nanobot-Robot-Body`）。
- `webui/src/App.tsx`：登录页 mount 后（bootstrap 完）`fetchControllerHost` 喂预填 + 模式；登录提交时若 IP 变更先 `applyControllerHost`（不阻塞于控制器在线）再 `fetchLogin`。

---

## 6. 安全

- **pre-auth**：三个端点登录前调用（仅 gateway-token）。
- **localhost 服务端强制**（test/apply）：`_is_localhost(connection)` 为假 → **403**。**不**依赖"部署通常 localhost"假设——服务端显式拒绝远程请求（有 remote→403 测试）。`GET controller-host`（只读）不强制 localhost。
- **test 无副作用**：临时 `ZMotionSdkClient` `finally disconnect`，不持久化 host、**绝不**调 shared configure/reconfigure。
- **apply 受控**：仅持久化 + `shared.reconfigure`，不开新连接、不驱动运动；误设最坏后果是状态轮询连不上（UI 显 disconnected），不是误动机械臂。
- **reconfigure 并发安全**：持锁完成 disconnect → 无"旧未断 + 新已建"双连/3402 窗口（§4.2）。

---

## 7. 测试（pytest + vitest，零进程）

### pytest（`.venv-robot-desktop`，新测试放 `tests/robot_ai/`）
- **配置优先级**：`config.robot_ai.controller_host` 非空 → 用之；空 → env；都空 → `""`（断言默认不再是 `10.168.3.21`）。
- **IPv4 校验+规范化**：`ipaddress.IPv4Address` 合法通过 + 规范化（`010.168.003.021`→`10.168.3.21`）；主机名/IPv6/空/带端口 → 400 `invalid_host`。
- **localhost 强制**：test/apply 用 mock 非 localhost connection → **403**；localhost → 正常。`GET`（只读）不强制。
- **`GET controller-host`**：返回当前 host + backend_mode。
- **`test` 端点**：mock `ZMotionSdkClient`（通/不通）；断言**临时客户端 finally `disconnect()`**（不是 close）；断言**共享单例未被 configure/reconfigure**、`_client` 不变。
- **`apply` 端点**：mock `shared.reconfigure` + config 写；断言 config.json 写入规范 host、`reconfigure` 被调一次（host 变更时）、未变更时幂等 no-op、`RobotBridge` 用 `dataclasses.replace` 换 frozen 配置（诊断显新 IP）。sim 模式：仅持久化、不 reconfigure。
- **`shared.reconfigure`**：mock 旧 `_client`；断言**整段持锁**、**旧 client `disconnect()` 被调**（不是 close）、disconnect 在 `_client=None`+设新 host 之前完成（无并发窗口）。
- **端点传输**：GET + `X-Nanobot-Robot-Body` + Bearer ws-token；no-store。

### vitest（`webui`）
- `LoginPage`：real 模式显示 IP 行 + 预填 + 测试按钮；sim 模式隐藏 IP 行；real 模式 IP 空置灰登录；测试按钮调端点显绿/红；不通不 block 登录；提交带 `controller_host`。
- App：bootstrap 后 `fetchControllerHost` 预填；IP 变更 → apply 再 login；IP 未变 → 不调 apply；apply 失败 → 提示但不崩。

---

## 8. 验收标准

- 登录页（real 模式）显示下位机 IP 框，预填当前 config 值（从未配过为空），可测试连通性（绿/红），不通不阻止登录。
- sim 模式登录页不显示 IP 框，缺 IP 不阻断登录。
- `GET /api/robot/controller-host` 返当前 host + backend_mode。
- `test`/`apply` 远程请求 → 403（localhost 服务端强制）；`test` 用临时 ZAux、finally `disconnect`、不动共享单例。
- `apply` 持久化（config.json `robot_ai.controller_host` 规范形式）+ `shared.reconfigure`（持锁完成 disconnect → 清 client → 设新 host）+ `dataclasses.replace` 同步 `RobotBridge` frozen 配置；不要求控制器在线。
- IP 仅接受 IPv4（`ipaddress.IPv4Address` 校验+规范化）；优先级 `config → env → 空`；工厂默认 `10.168.3.21` 移除。
- 全程 no-git、零进程；pytest + vitest + ruff + build 全绿（不回归切片② 的 525 vitest / 后端基线）。

---

## 9. 决策记录

1. **独立端点，不合并 login**：apply 是"保存+切换连接目标"，login 是身份认证，职责分离；登录页流程 `bootstrap → GET host → (test) → apply-if-changed → login`。
2. **apply 不要求控制器在线**：只保存+切换目标；不可达仅让 test 失败，不阻断登录。
3. **预填用独立 `GET controller-host`**：不塞 bootstrap（bootstrap=传输凭证，controller-host=机器人域，边界清晰）。
4. **从未配置 → 空**：去工厂默认硬编码；real 模式必填，sim 模式不要求。
5. **`shared.reconfigure`（运行时修正）**：现有 `configure` 不断既有连接 → 新增 reconfigure，**整段持锁完成 `disconnect()`（不是 close）→ 清 `_client` → 设新 host**，杜绝"旧未断+新已建"双连/3402 窗口；同步 `RobotBridge` 防诊断显旧 IP。
6. **接口全 GET + `X-Nanobot-Robot-Body`**：匹配 gateway WS-HTTP 传输（websockets 库只接 GET）。
7. **IPv4 用 `ipaddress.IPv4Address`**：校验 + 规范化；拒绝主机名/IPv6/空/带端口。
8. **test 临时客户端 `finally disconnect`、绝不碰共享单例**；apply 持锁 reconfigure、不驱动运动。
9. **`RobotBackendConfig` frozen** → 用 `dataclasses.replace`（或 `RobotBridge.reconfigure_controller_host`）替换，不原地改。
10. **localhost 服务端强制**（test/apply）：`_is_localhost` 为假 → 403，**不**靠"部署通常 localhost"假设（有 remote→403 测试）；`GET`（只读）不强制。
11. **pre-auth 可接受**：三个端点登录前调用（仅 gateway-token）；localhost 强制兜底，暴露到非 localhost 时再加 engineer-only/白名单（本切片不做）。
