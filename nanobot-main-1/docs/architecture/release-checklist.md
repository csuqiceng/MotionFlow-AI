# 模块化迁移发布清单

本清单的基线是当前已发布的简化 WebUI。它不要求、也不允许恢复历史 Settings、工作区、草稿、附件或 LLM 流程创作页面。

## 自动化证据

- Python：使用 `desktop/.build-venv/Scripts/python.exe`，并将 `TEMP`/`TMP` 指向 worktree 外目录，执行 `python -m pytest -q`。
- WebUI：在 `webui/` 执行 `npm test -- --run` 与 `npm run build`。
- Electron：在 `desktop/` 执行 `npm run build`、`node electron/tests/product-manifest.test.js`、`npm run dist`、`npm run verifyRelease`、`npm run smokePackagedRobotServer`。
- 数据兼容：执行 `tests/robot_ai/test_platform_data_migration.py` 与 `tests/robot_server/test_app.py::test_identity_recovers_enabled_legacy_users_from_seeded_placeholders`。它们证明旧 `robot_ai` 数据复制到 `robot_platform` 后保留源目录、写入迁移报告，并可恢复旧账户。

任何失败都阻止发布。Vite 分块、React `act(...)` 及 Windows Proactor 的已知 warning 必须记录；不得将 warning 伪装成通过或失败。

## 脱敏数据副本演练

在隔离机器上操作，不连接真实机械手。

1. 从待升级机器复制并脱敏运行时根目录：`config.json`、`robot_ai/`、会话、审计、命令、流程、位置、知识、待执行计划和媒体索引。
2. 使用只读演练工具生成复制、SHA-256 与 JSON 顶层记录清单；原始副本保持只读：

   ```powershell
   desktop\.build-venv\Scripts\python.exe tools\rehearse_runtime_migration.py `
     --source-runtime D:\sanitized\runtime `
     --scratch-root D:\migration-rehearsal\run-001
   ```

   它要求 scratch 为空且不在源目录内；完整副本保留在 `scratch\runtime`，并在独立的 `scratch\legacy-replay` 中重放首次 `robot_ai` → `robot_platform` 迁移。两处均不启动 server/backend，报告写入 `runtime-migration-rehearsal.json`；不会改写或删除 `scratch\runtime` 中已存在的 canonical 数据。
3. 使用新版本、`simulation` backend 和 `scratch\runtime` 启动一次。确认 `scratch\legacy-replay\robot_platform_migration.json` 存在、旧 `robot_ai/` 仍存在，且 `scratch\runtime` 的现有 canonical 数据保持原样。
4. 比较用户、角色、命令、流程、位置、知识、审计、会话与待执行计划的数量、ID 和摘要；任何差异必须有经批准的迁移说明。
5. 登录当前简化 UI，完成登录、会话、Settings、自动任务、资产库、工程师工作台和 robot dry-run 的人工旅程。不得检查已删除页面。

## 回滚演练

1. 停止新版本；保留 `robot_platform/`、`robot_ai/` 与 `robot_platform_migration.json`。
2. 将运行时根目录恢复为演练前只读副本，或将旧 `robot_ai/` 作为旧版本的数据根重新启动。
3. 以 simulation 复核登录、资产读取、会话和 dry-run；比较第 2 步的 SHA-256/记录清单。
4. 记录操作者、时间、版本、差异和结论。未通过时不得删除兼容 adapter 或发布。

## 受控硬件验证

只在批准工位、急停可达、操作者在场时进行：先 ZMotion 只读，再 dry-run，最后执行经批准的最小真实动作。真实动作前后都验证确认码会话绑定、双现场确认和独立急停。自动化和模拟环境不能替代此项。
