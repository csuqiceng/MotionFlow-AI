# Robot WebUI Chinese Localization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Display Chinese labels in the robot login preflight and engineer command/flow workbench when `zh-CN` is active, while preserving the existing language switcher.

**Architecture:** Move every affected visible literal into the existing i18next locale dictionaries. Components call `t()` with a Chinese fallback only for new keys, so no API, role, draft, publish, or execution behavior changes. Tests switch to `zh-CN` and assert Chinese labels rather than relying on English literals.

**Tech Stack:** React 18, TypeScript, react-i18next, Vitest, Testing Library.

---

### Task 1: Add localized workbench and preflight labels

**Files:**
- Modify: `nanobot-main-1/webui/src/i18n/locales/en/common.json`
- Modify: `nanobot-main-1/webui/src/i18n/locales/zh-CN/common.json`
- Modify: `nanobot-main-1/webui/src/components/LoginPage.tsx`
- Modify: `nanobot-main-1/webui/src/robot/workbench/EngineerWorkbench.tsx`
- Modify: `nanobot-main-1/webui/src/robot/workbench/CommandDraftEditor.tsx`
- Modify: `nanobot-main-1/webui/src/robot/workbench/FlowDraftEditor.tsx`
- Modify: `nanobot-main-1/webui/src/robot/library/FlowDetail.tsx`

- [ ] **Step 1: Write failing Chinese-rendering assertions**

Add tests that render the login page and engineer workbench after `await i18n.changeLanguage("zh-CN")`, then assert Chinese labels including `"检测连接"`, `"新建命令"`, `"新建流程"`, `"保存草稿"`, and `"发布流程"`.

- [ ] **Step 2: Run the localization tests to verify failure**

Run: `npm.cmd --prefix webui test -- --run src/tests/login-page.test.tsx src/tests/engineer-workbench.test.tsx`

Expected: FAIL because the preflight and workbench labels are currently hard-coded English strings.

- [ ] **Step 3: Add locale keys and replace hard-coded labels**

Add `login.preflight` keys for the controller host, connection check, check in-progress, controller/voice/AI status and operator gate notice. Add `library.workbench` keys for command and flow draft labels, step controls, validation, publish/archive dialogs, and flow-detail metadata. Replace every affected visible literal with `t("<key>")` in the listed components.

Use this pattern in each component:

```tsx
const { t } = useTranslation();
<Button>{t("library.workbench.saveDraft")}</Button>
```

- [ ] **Step 4: Run the localization tests to verify success**

Run: `npm.cmd --prefix webui test -- --run src/tests/login-page.test.tsx src/tests/engineer-workbench.test.tsx`

Expected: PASS with Chinese assertions satisfied and existing English tests retained.

- [ ] **Step 5: Commit the localized UI**

Run:

```bash
git add webui/src/i18n/locales/en/common.json webui/src/i18n/locales/zh-CN/common.json webui/src/components/LoginPage.tsx webui/src/robot/workbench webui/src/robot/library/FlowDetail.tsx webui/src/tests/login-page.test.tsx webui/src/tests/engineer-workbench.test.tsx
git commit -m "feat: localize robot workbench labels"
```

### Task 2: Verify the Chinese UI in the integrated app

**Files:**
- Modify: `nanobot-main-1/webui/src/tests/app-layout.test.tsx`

- [ ] **Step 1: Add a Chinese engineer-login assertion**

Add a test that switches `i18n` to `zh-CN`, reaches the login view, and asserts the localized engineer role tab and Chinese login/preflight labels.

- [ ] **Step 2: Run the assertion to verify failure**

Run: `npm.cmd --prefix webui test -- --run src/tests/app-layout.test.tsx`

Expected: FAIL before Task 1 because the affected labels are not yet localized.

- [ ] **Step 3: Verify integrated rendering after Task 1**

Run: `npm.cmd --prefix webui test -- --run src/tests/app-layout.test.tsx src/tests/login-page.test.tsx src/tests/engineer-workbench.test.tsx`

Expected: PASS with the login and workbench rendered in Chinese under `zh-CN`.

- [ ] **Step 4: Build the production frontend**

Run: `npm.cmd --prefix webui run build`

Expected: TypeScript compilation and Vite build complete successfully.

- [ ] **Step 5: Browser verification**

Open `http://127.0.0.1:5173/`, select Chinese in the existing language switcher, then confirm that the engineer library displays Chinese action labels. Do not create, publish, archive, or execute any robot definition.

- [ ] **Step 6: Commit the integration coverage**

Run:

```bash
git add webui/src/tests/app-layout.test.tsx
git commit -m "test: verify Chinese robot workbench labels"
```
