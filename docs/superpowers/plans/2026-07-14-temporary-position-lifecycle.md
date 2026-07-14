# Temporary Position Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent temporary chat and draft coordinates from persisting, then safely remove existing unreferenced temporary positions.

**Architecture:** Separate temporary coordinate execution from the persistent position registry. A cleanup service classifies positions by prefix, preserves references from published assets, creates a backup, and records every removal.

**Tech Stack:** Python 3.11, existing robot position registry JSON, pytest.

---

### Task 1: Classify and safely clean legacy positions

**Files:**
- Create: `nanobot-main-1/robot_ai/positions/cleanup.py`
- Test: `nanobot-main-1/tests/robot_ai/test_position_cleanup.py`

- [ ] Write a failing test with temporary names and a referenced temporary name; assert only the unreferenced name is selected.
- [ ] Run `python -m pytest tests/robot_ai/test_position_cleanup.py -q` and confirm failure.
- [ ] Implement `classify_temporary(name)` for `flowdraft:`, `agent:`, and `ai_first:`; implement `build_cleanup_plan(positions, referenced_names)` returning `remove` and `preserve` lists.
- [ ] Add `backup_and_apply(path, plan)` that writes a timestamped JSON backup before removing items.
- [ ] Re-run the focused test and commit `feat: add safe temporary position cleanup`.

### Task 2: Prevent new temporary persistence

**Files:**
- Modify: `nanobot-main-1/robot_ai/positions/registry.py`
- Test: `nanobot-main-1/tests/robot_ai/test_position_registry.py`

- [ ] Write a failing test asserting `register(..., persistence="temporary")` does not write the registry file or list entry.
- [ ] Implement an explicit `persistence` argument with `"persistent"` as the only write-enabled value; return a transient coordinate handle for `"temporary"`.
- [ ] Update chat/planning callers to pass `persistence="temporary"`; save-position, save-command, and save-flow callers pass `"persistent"`.
- [ ] Run focused registry tests and commit `feat: keep temporary coordinates out of registry`.

### Task 3: Expose audited cleanup

**Files:**
- Modify: `nanobot-main-1/nanobot/api/robot_routes.py`
- Test: `nanobot-main-1/tests/robot_ai/test_engineer_routes.py`

- [ ] Write a failing engineer-only route test for preview and apply cleanup responses.
- [ ] Add preview endpoint returning counts, names, preserved references, and backup location only after apply.
- [ ] Add apply endpoint requiring explicit action and recording audit details.
- [ ] Run route tests, full relevant pytest suite, and commit `feat: expose audited temporary position cleanup`.

### Task 4: Verify live data

- [ ] Run cleanup preview against the active registry; inspect preserved references and candidate count.
- [ ] Apply cleanup only after preview is recorded; verify common positions remain and temporary count is zero.
- [ ] Open WebUI and verify temporary chat planning no longer changes registered-position count.
