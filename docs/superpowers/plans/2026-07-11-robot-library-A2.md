# Robot Library A2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the A2 operator read-only command/flow library — remove Apps/Skills from the shared Sidebar, add a 命令库 entry → `#/library` page (命令/流程 tabs, list+filter+detail), a read-only flow list/detail API, and the `rightPanel`-gating regression test.

**Architecture:** Backend adds two read-only `/api/robot/library/flows*` endpoints (read from existing `FlowRegistry`, no writes) mounted through the existing `ws_http._dispatch_robot_library_routes` token gate. Frontend adds `robot-library-api.ts` (4 functions), `useRobotLibrary` hook, `robot/library/` page components, extends `ShellView` with `"library"`, renders the page in the center area, and gates `rightPanel` (`view !== "library" && rightPanel`) so `RobotSidePanel` hides on the library page. `RobotOperatorApp`/`RobotSidePanel`/chat/confirm/execute/`robot_ai/flow/` untouched.

**Tech Stack:** Python 3.11 aiohttp (backend, `.venv-robot-desktop`); React 18 + TypeScript + vitest(happy-dom) + tailwind (frontend, `bun`).

**Spec:** `docs/superpowers/specs/2026-07-11-robot-library-A2-design.md`

**No-git rule (user-standing):** No `git add`/`commit` steps. Each task ends with a **Verify & checkpoint** step (run tests + lint). User commits unified later. TDD discipline (failing test → implement → passing test) preserved.

**Working directory note:** Backend commands assume cwd = `nanobot-main-1/`; frontend commands assume cwd = `nanobot-main-1/webui/`. Backend tests MUST run under `.venv-robot-desktop/Scripts/python.exe` (base Python lacks aiohttp).

---

## File Structure

**Create (new):**
- `webui/src/lib/robot-library-api.ts` — 4 API functions + `LibraryCommand`/`LibraryFlow`/`LibraryFlowStep` types
- `webui/src/robot/hooks/useRobotLibrary.ts` — `useRobotLibrary(token, tab)` hook (list + detail)
- `webui/src/robot/library/CommandLibraryPage.tsx` — page shell (tabs + list + detail)
- `webui/src/robot/library/LibraryList.tsx` — search + filter + list
- `webui/src/robot/library/CommandDetail.tsx` — read-only command detail
- `webui/src/robot/library/FlowDetail.tsx` — read-only flow detail
- `webui/src/tests/test_robot_library_api.ts`
- `webui/src/tests/test_use_robot_library.ts`
- `webui/src/tests/test_command_library_page.tsx`

**Modify (existing):**
- `nanobot/api/robot_routes.py` — add `process_robot_library_flows` / `process_robot_library_flow` + `handle_*` + register + `__all__`
- `nanobot/webui/ws_http.py` — extend `_dispatch_robot_library_routes` with flow paths
- `webui/src/components/Sidebar.tsx` — remove Apps/Skills buttons, add 命令库 button
- `webui/src/App.tsx` — `ShellView += "library"`, route `#/library`, `onOpenLibrary`, render page, gate `rightPanel`, sidebarProps
- `webui/src/i18n/locales/en/common.json` + `zh-CN/common.json` — `sidebar.commandLibrary` + `library.*` keys
- `webui/src/tests/app-layout.test.tsx` — append regression test + sidebar nav assertions

**Do NOT touch:** `RobotOperatorApp.tsx`, `RobotSidePanel.tsx`, `robot_ai/flow/` (FlowRegistry read-only), chat/confirm/execute链路, real execution.

---

## Task 1: Backend — read-only flow API

**Files:**
- Modify: `nanobot/api/robot_routes.py` (after `process_robot_library_component` ~line 456; after `handle_robot_library_component` ~line 764; in `register_robot_routes` ~line 780; in `__all__`)
- Modify: `nanobot/webui/ws_http.py` (`_dispatch_robot_library_routes` ~line 386-434)
- Test: `tests/robot_ai/test_robot_library_routes.py` (extend) + `tests/robot_ai/test_ws_http_library_routes.py` (extend)

- [ ] **Step 1: Write the failing tests (extend `test_robot_library_routes.py`)**

Append to `tests/robot_ai/test_robot_library_routes.py`:

```python
from robot_ai.flow.models import FlowEntry, FlowStep
from robot_ai.flow.registry import FlowRegistry


def _seed_flow(path, name="PickPlace", confirmed=False):
    reg = FlowRegistry(path)
    reg.add(FlowEntry(
        name=name,
        description="pick and place",
        steps=[FlowStep(step_id=1, action="move", func_id=108, params={"target_z": 50.0})],
        step_delay_ms=500,
        confirmed=confirmed,
    ))


def test_flow_list_envelope(tmp_path):
    flows = tmp_path / "flows.json"
    _seed_flow(flows, "PickPlace")
    status, result = process_robot_library_flows(flow_registry_path=str(flows))
    assert status == 200
    assert result["ok"] is True
    assert result["data"]["total"] == 1
    assert result["data"]["items"][0]["name"] == "PickPlace"


def test_flow_list_empty(tmp_path):
    flows = tmp_path / "flows.json"
    FlowRegistry(flows)  # creates empty registry file
    status, result = process_robot_library_flows(flow_registry_path=str(flows))
    assert status == 200
    assert result["data"]["total"] == 0
    assert result["data"]["items"] == []


def test_flow_detail_found_and_404(tmp_path):
    flows = tmp_path / "flows.json"
    _seed_flow(flows, "PickPlace")
    s_ok, r_ok = process_robot_library_flow("pickplace", flow_registry_path=str(flows))
    assert s_ok == 200
    assert r_ok["data"]["name"] == "PickPlace"
    assert r_ok["data"]["steps"][0]["func_id"] == 108
    s_miss, r_miss = process_robot_library_flow("nope", flow_registry_path=str(flows))
    assert s_miss == 404 and r_miss["error"]["code"] == 404
```

Add `process_robot_library_flows, process_robot_library_flow` to the import line at the top of the test file (extend the existing `from nanobot.api.robot_routes import (...)`).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_robot_library_routes.py -q`
Expected: FAIL with `ImportError: cannot import name 'process_robot_library_flows'`

- [ ] **Step 3: Implement the process + handle functions**

In `nanobot/api/robot_routes.py`, insert after `process_robot_library_component` (after line 456, before the `# Flow process functions` comment block):

```python
def process_robot_library_flows(
    *,
    flow_registry_path: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Core logic for ``GET /api/robot/library/flows`` (read-only list).

    Reads the existing ``FlowRegistry`` without writing. Step shape stays as-is
    (``func_id``/``params``); the ``{command_id, version}`` upgrade is phase C.
    """
    from robot_ai.flow import FlowRegistry

    registry = FlowRegistry(_resolve_flow_registry_path(flow_registry_path))
    items = registry.list_all()
    return 200, {"ok": True, "data": {"items": [f.to_dict() for f in items], "total": len(items)}}


def process_robot_library_flow(
    flow_name: str,
    *,
    flow_registry_path: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Core logic for ``GET /api/robot/library/flows/{name}`` (read-only)."""
    from robot_ai.flow import FlowRegistry

    registry = FlowRegistry(_resolve_flow_registry_path(flow_registry_path))
    flow = registry.get(flow_name)
    if flow is None:
        return 404, {"error": {"message": f"Flow '{flow_name}' not found.",
                               "type": "invalid_request_error", "code": 404}}
    return 200, {"ok": True, "data": flow.to_dict()}
```

Insert after `handle_robot_library_component` (after line 764, before `register_robot_routes`):

```python
async def handle_robot_library_flows(request: web.Request) -> web.Response:
    """GET /api/robot/library/flows — read-only flow list."""
    status, result = process_robot_library_flows(
        flow_registry_path=request.app.get("robot_flow_registry_path"),
    )
    return web.json_response(result, status=status)


async def handle_robot_library_flow(request: web.Request) -> web.Response:
    """GET /api/robot/library/flows/{flow_name} — single flow (read-only)."""
    flow_name = request.match_info["flow_name"]
    status, result = process_robot_library_flow(
        flow_name, flow_registry_path=request.app.get("robot_flow_registry_path")
    )
    return web.json_response(result, status=status)
```

In `register_robot_routes`, after the `components/{component_id}` line (line 780), add:

```python
    app.router.add_get("/api/robot/library/flows", handle_robot_library_flows)
    app.router.add_get("/api/robot/library/flows/{flow_name}", handle_robot_library_flow)
```

In `__all__`, add these four names alongside the other library exports:

```python
    "handle_robot_library_flows",
    "handle_robot_library_flow",
    "process_robot_library_flows",
    "process_robot_library_flow",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_robot_library_routes.py -q`
Expected: all pass (existing + 3 new).

- [ ] **Step 5: Mount flow paths in the gateway dispatcher**

Replace the entire `_dispatch_robot_library_routes` method body in `nanobot/webui/ws_http.py` (lines 386-434) with:

```python
    def _dispatch_robot_library_routes(self, request: WsRequest, got: str) -> Response | None:
        """Dispatch the read-only ``/api/robot/library/*`` endpoints.

        Token-gated GET (no body), mounted through the robot dispatcher so the
        library inherits the same ``check_api_token`` gate as the other robot
        routes. Detail paths use regex (the rest of the robot dispatcher is
        exact-match only). ``?version=`` is explicitly unsupported in A1.
        """
        command_detail = re.match(r"^/api/robot/library/commands/([^/]+)$", got)
        component_detail = re.match(r"^/api/robot/library/components/([^/]+)$", got)
        flow_detail = re.match(r"^/api/robot/library/flows/([^/]+)$", got)
        is_command_list = got == "/api/robot/library/commands"
        is_component_list = got == "/api/robot/library/components"
        is_flow_list = got == "/api/robot/library/flows"
        if not (command_detail or component_detail or flow_detail
                or is_command_list or is_component_list or is_flow_list):
            return None

        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")

        query = _parse_query(request.path)
        if _query_first(query, "version") is not None:
            return _http_error(400, "unsupported parameter: version")

        from nanobot.api.robot_routes import (
            DEFAULT_COMMANDS_PATH,
            DEFAULT_FLOW_REGISTRY_PATH,
            process_robot_library_command,
            process_robot_library_commands,
            process_robot_library_component,
            process_robot_library_components,
            process_robot_library_flow,
            process_robot_library_flows,
        )

        commands_path = getattr(self, "_robot_commands_path", None) or DEFAULT_COMMANDS_PATH
        flow_registry_path = getattr(self, "_robot_flow_registry_path", None) or DEFAULT_FLOW_REGISTRY_PATH

        if is_command_list:
            status, result = process_robot_library_commands(
                commands_path=commands_path,
                component_id=_query_first(query, "component_id") or None,
                risk_level=_query_first(query, "risk_level") or None,
                status=_query_first(query, "status") or None,
                q=_query_first(query, "q") or None,
            )
        elif command_detail is not None:
            status, result = process_robot_library_command(
                unquote(command_detail.group(1)), commands_path=commands_path
            )
        elif is_component_list:
            status, result = process_robot_library_components()
        elif component_detail is not None:
            status, result = process_robot_library_component(unquote(component_detail.group(1)))
        elif is_flow_list:
            status, result = process_robot_library_flows(flow_registry_path=flow_registry_path)
        else:  # flow_detail
            status, result = process_robot_library_flow(
                unquote(flow_detail.group(1)), flow_registry_path=flow_registry_path
            )
        return _http_json_response(result, status=status)
```

- [ ] **Step 6: Extend the ws_http library test with flow paths**

Append to `tests/robot_ai/test_ws_http_library_routes.py`:

```python
def test_library_flow_list_returns_200(tmp_path: Path) -> None:
    from robot_ai.flow.models import FlowEntry
    from robot_ai.flow.registry import FlowRegistry
    flows = tmp_path / "flows.json"
    FlowRegistry(flows).add(FlowEntry(name="PickPlace", description="x"))
    fake = SimpleNamespace(
        check_api_token=lambda _req: True,
        _robot_commands_path=str(tmp_path / "commands.json"),
        _robot_flow_registry_path=str(flows),
    )
    resp = GatewayHTTPHandler._dispatch_robot_library_routes(
        fake, _fake_request("/api/robot/library/flows"), "/api/robot/library/flows"
    )
    assert resp.status_code == 200


def test_library_flow_detail_404(tmp_path: Path) -> None:
    fake = SimpleNamespace(
        check_api_token=lambda _req: True,
        _robot_commands_path=str(tmp_path / "commands.json"),
        _robot_flow_registry_path=str(tmp_path / "flows.json"),
    )
    resp = GatewayHTTPHandler._dispatch_robot_library_routes(
        fake, _fake_request("/api/robot/library/flows/nope"),
        "/api/robot/library/flows/nope",
    )
    assert resp.status_code == 404
```

- [ ] **Step 7: Run + checkpoint**

Run: `cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/test_robot_library_routes.py tests/robot_ai/test_ws_http_library_routes.py -q && .venv-robot-desktop/Scripts/python.exe -m ruff check nanobot/api/robot_routes.py nanobot/webui/ws_http.py tests/robot_ai/test_robot_library_routes.py tests/robot_ai/test_ws_http_library_routes.py`
Expected: all tests pass; ruff clean. No git commit.

---

## Task 2: Frontend — `robot-library-api.ts`

**Files:**
- Create: `webui/src/lib/robot-library-api.ts`
- Test: `webui/src/tests/test_robot_library_api.ts`

- [ ] **Step 1: Write the failing test**

```typescript
// webui/src/tests/test_robot_library_api.ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchWithTimeout } from "@/lib/http";
import {
  robotLibraryCommand,
  robotLibraryCommands,
  robotLibraryFlow,
  robotLibraryFlows,
  type LibraryCommand,
  type LibraryFlow,
} from "@/lib/robot-library-api";

vi.mock("@/lib/http", () => ({
  fetchWithTimeout: vi.fn(),
}));

const okResponse = (body: unknown) => ({
  ok: true,
  status: 200,
  headers: { get: () => "application/json" },
  json: async () => body,
}) as unknown as Response;

afterEach(() => {
  vi.mocked(fetchWithTimeout).mockReset();
});

describe("robot-library-api", () => {
  it("lists commands with filters encoded as query params", async () => {
    vi.mocked(fetchWithTimeout).mockResolvedValue(
      okResponse({ ok: true, data: { items: [], total: 0 } }),
    );
    await robotLibraryCommands("tok", { q: "home", risk_level: "high" });
    const [url, init] = vi.mocked(fetchWithTimeout).mock.calls[0];
    expect(String(url)).toBe("/api/robot/library/commands?q=home&risk_level=high");
    expect((init as RequestInit).method).toBe("GET");
    expect(((init as RequestInit).headers as Record<string, string>)["Authorization"]).toBe(
      "Bearer tok",
    );
  });

  it("fetches a single command by id", async () => {
    const cmd: LibraryCommand = {
      id: "home", name: "home", component_id: "linear_move", parameters: {},
      aliases: [], description: "", risk_level: "high", status: "published",
      version: 1, source: "legacy-import", created_by: "", created_at: "",
      updated_at: "", published_at: "",
    };
    vi.mocked(fetchWithTimeout).mockResolvedValue(okResponse({ ok: true, data: cmd }));
    const result = await robotLibraryCommand("tok", "home");
    expect(result.data.id).toBe("home");
    expect(String(vi.mocked(fetchWithTimeout).mock.calls[0][0])).toBe(
      "/api/robot/library/commands/home",
    );
  });

  it("lists flows", async () => {
    vi.mocked(fetchWithTimeout).mockResolvedValue(
      okResponse({ ok: true, data: { items: [], total: 0 } }),
    );
    await robotLibraryFlows("tok");
    expect(String(vi.mocked(fetchWithTimeout).mock.calls[0][0])).toBe(
      "/api/robot/library/flows",
    );
  });

  it("fetches a single flow by name (url-encoded)", async () => {
    const flow: LibraryFlow = {
      name: "休息姿态", description: "", steps: [], step_delay_ms: 1000,
      rehearsal_spd: 20, confirmed: false, version: 1, state: "idle",
      current_step: 0, created_by: "", created_at: "", updated_at: "",
    };
    vi.mocked(fetchWithTimeout).mockResolvedValue(okResponse({ ok: true, data: flow }));
    const result = await robotLibraryFlow("tok", "休息姿态");
    expect(result.data.name).toBe("休息姿态");
    expect(String(vi.mocked(fetchWithTimeout).mock.calls[0][0])).toBe(
      "/api/robot/library/flows/" + encodeURIComponent("休息姿态"),
    );
  });

  it("throws on non-ok response", async () => {
    vi.mocked(fetchWithTimeout).mockResolvedValue({
      ok: false, status: 404, text: async () => "not found",
    } as unknown as Response);
    await expect(robotLibraryCommand("tok", "nope")).rejects.toThrow();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webui && bun run test -- src/tests/test_robot_library_api.ts`
Expected: FAIL with `Failed to resolve import "@/lib/robot-library-api"`

- [ ] **Step 3: Implement `robot-library-api.ts`**

```typescript
// webui/src/lib/robot-library-api.ts
import { fetchWithTimeout } from "./http";

const LIBRARY_TIMEOUT_MS = 15_000;

export interface LibraryCommand {
  id: string;
  name: string;
  aliases: string[];
  description: string;
  component_id: string;
  parameters: Record<string, unknown>;
  risk_level: string;
  status: string;
  version: number;
  source: string;
  created_by: string;
  created_at: string;
  updated_at: string;
  published_at: string;
}

export interface LibraryFlowStep {
  step_id: number;
  action: string;
  func_id: number;
  params: Record<string, unknown>;
  position_name: string | null;
  spd_pct: number;
  description: string;
}

export interface LibraryFlow {
  name: string;
  description: string;
  steps: LibraryFlowStep[];
  step_delay_ms: number;
  rehearsal_spd: number;
  confirmed: boolean;
  version: number;
  state: string;
  current_step: number;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface LibraryListResponse<T> {
  ok: boolean;
  data: { items: T[]; total: number };
}

export interface LibraryDetailResponse<T> {
  ok: boolean;
  data: T;
}

export interface LibraryCommandFilters {
  component_id?: string;
  risk_level?: string;
  status?: string;
  q?: string;
}

async function libraryGet<T>(url: string, token: string): Promise<T> {
  const res = await fetchWithTimeout(
    url,
    {
      method: "GET",
      headers: { Authorization: `Bearer ${token}` },
      credentials: "same-origin",
    },
    LIBRARY_TIMEOUT_MS,
  );
  if (!res.ok) {
    const text = typeof res.text === "function" ? (await res.text()).trim() : "";
    throw new Error(`Library API ${url} failed: ${res.status} ${text}`);
  }
  return (await res.json()) as T;
}

function buildQuery(params: Record<string, string | undefined>): string {
  const entries = Object.entries(params).filter(([, v]) => v && v.trim() !== "");
  if (entries.length === 0) return "";
  return "?" + entries.map(([k, v]) => `${k}=${encodeURIComponent(v as string)}`).join("&");
}

export function robotLibraryCommands(
  token: string,
  filters: LibraryCommandFilters = {},
): Promise<LibraryListResponse<LibraryCommand>> {
  const query = buildQuery(filters);
  return libraryGet<LibraryListResponse<LibraryCommand>>(
    `/api/robot/library/commands${query}`,
    token,
  );
}

export function robotLibraryCommand(
  token: string,
  id: string,
): Promise<LibraryDetailResponse<LibraryCommand>> {
  return libraryGet<LibraryDetailResponse<LibraryCommand>>(
    `/api/robot/library/commands/${encodeURIComponent(id)}`,
    token,
  );
}

export function robotLibraryFlows(
  token: string,
): Promise<LibraryListResponse<LibraryFlow>> {
  return libraryGet<LibraryListResponse<LibraryFlow>>("/api/robot/library/flows", token);
}

export function robotLibraryFlow(
  token: string,
  name: string,
): Promise<LibraryDetailResponse<LibraryFlow>> {
  return libraryGet<LibraryDetailResponse<LibraryFlow>>(
    `/api/robot/library/flows/${encodeURIComponent(name)}`,
    token,
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webui && bun run test -- src/tests/test_robot_library_api.ts`
Expected: 5 PASS

- [ ] **Step 5: Verify & checkpoint**

Run: `cd webui && bun run test -- src/tests/test_robot_library_api.ts && bunx tsc -p tsconfig.build.json --noEmit`
Expected: tests pass; tsc clean. No git commit.

---

## Task 3: Frontend — `useRobotLibrary` hook

**Files:**
- Create: `webui/src/robot/hooks/useRobotLibrary.ts`
- Test: `webui/src/tests/test_use_robot_library.ts`

- [ ] **Step 1: Write the failing test**

```typescript
// webui/src/tests/test_use_robot_library.ts
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/robot-library-api", () => ({
  robotLibraryCommands: vi.fn(),
  robotLibraryCommand: vi.fn(),
  robotLibraryFlows: vi.fn(),
  robotLibraryFlow: vi.fn(),
}));

import { robotLibraryCommand, robotLibraryCommands, robotLibraryFlow, robotLibraryFlows } from "@/lib/robot-library-api";
import { useRobotLibrary } from "@/robot/hooks/useRobotLibrary";
import type { LibraryCommand, LibraryFlow } from "@/lib/robot-library-api";

afterEach(() => {
  vi.mocked(robotLibraryCommands).mockReset();
  vi.mocked(robotLibraryCommand).mockReset();
  vi.mocked(robotLibraryFlows).mockReset();
  vi.mocked(robotLibraryFlow).mockReset();
});

describe("useRobotLibrary", () => {
  it("loads the command list for the commands tab", async () => {
    vi.mocked(robotLibraryCommands).mockResolvedValue({
      ok: true, data: { items: [{ id: "home", name: "home" } as LibraryCommand], total: 1 },
    });
    const { result } = renderHook(() => useRobotLibrary("tok", "commands"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.items).toHaveLength(1);
    expect(result.current.error).toBeNull();
  });

  it("loads the flow list for the flows tab", async () => {
    vi.mocked(robotLibraryFlows).mockResolvedValue({
      ok: true, data: { items: [{ name: "PickPlace" } as LibraryFlow], total: 1 },
    });
    const { result } = renderHook(() => useRobotLibrary("tok", "flows"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(robotLibraryFlows).toHaveBeenCalledWith("tok");
    expect(result.current.items[0]).toMatchObject({ name: "PickPlace" });
  });

  it("loads detail when an item is selected", async () => {
    vi.mocked(robotLibraryCommands).mockResolvedValue({
      ok: true, data: { items: [{ id: "home", name: "home" } as LibraryCommand], total: 1 },
    });
    vi.mocked(robotLibraryCommand).mockResolvedValue({
      ok: true, data: { id: "home", name: "home", component_id: "linear_move" } as LibraryCommand,
    });
    const { result } = renderHook(() => useRobotLibrary("tok", "commands"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => result.current.select("home"));
    await waitFor(() => expect(result.current.detail).not.toBeNull());
    expect(robotLibraryCommand).toHaveBeenCalledWith("tok", "home");
    expect(result.current.detail).toMatchObject({ id: "home" });
  });

  it("exposes a list error", async () => {
    vi.mocked(robotLibraryCommands).mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useRobotLibrary("tok", "commands"));
    await waitFor(() => expect(result.current.error).toBe("boom"));
    expect(result.current.items).toEqual([]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webui && bun run test -- src/tests/test_use_robot_library.ts`
Expected: FAIL with `Failed to resolve import "@/robot/hooks/useRobotLibrary"`

- [ ] **Step 3: Implement the hook**

```typescript
// webui/src/robot/hooks/useRobotLibrary.ts
import { useEffect, useState } from "react";

import {
  robotLibraryCommand,
  robotLibraryCommands,
  robotLibraryFlow,
  robotLibraryFlows,
  type LibraryCommand,
  type LibraryCommandFilters,
  type LibraryFlow,
} from "@/lib/robot-library-api";

export type LibraryTab = "commands" | "flows";

export interface LibraryFilters {
  q: string;
  component_id: string;
  risk_level: string;
  status: string;
}

export interface UseRobotLibraryResult {
  items: LibraryCommand[] | LibraryFlow[];
  loading: boolean;
  error: string | null;
  filters: LibraryFilters;
  setFilters: (patch: Partial<LibraryFilters>) => void;
  selectedId: string | null;
  select: (id: string | null) => void;
  detail: LibraryCommand | LibraryFlow | null;
  detailLoading: boolean;
  detailError: string | null;
}

const EMPTY_FILTERS: LibraryFilters = { q: "", component_id: "", risk_level: "", status: "" };

export function useRobotLibrary(token: string, tab: LibraryTab): UseRobotLibraryResult {
  const [filters, setFiltersState] = useState<LibraryFilters>(EMPTY_FILTERS);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [items, setItems] = useState<LibraryCommand[] | LibraryFlow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<LibraryCommand | LibraryFlow | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const setFilters = (patch: Partial<LibraryFilters>) => {
    setFiltersState((current) => ({ ...current, ...patch }));
    setSelectedId(null);
    setDetail(null);
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const apiFilters: LibraryCommandFilters = {
      q: filters.q || undefined,
      component_id: filters.component_id || undefined,
      risk_level: filters.risk_level || undefined,
      status: filters.status || undefined,
    };
    const promise =
      tab === "commands"
        ? robotLibraryCommands(token, apiFilters).then((r) => r.data.items as LibraryCommand[])
        : robotLibraryFlows(token).then((r) => r.data.items as LibraryFlow[]);
    promise
      .then((result) => {
        if (!cancelled) {
          setItems(result);
          setLoading(false);
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
          setItems([]);
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [token, tab, filters.q, filters.component_id, filters.risk_level, filters.status]);

  useEffect(() => {
    if (selectedId === null) {
      setDetail(null);
      setDetailError(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    setDetailError(null);
    const promise =
      tab === "commands"
        ? robotLibraryCommand(token, selectedId).then((r) => r.data as LibraryCommand)
        : robotLibraryFlow(token, selectedId).then((r) => r.data as LibraryFlow);
    promise
      .then((result) => {
        if (!cancelled) {
          setDetail(result);
          setDetailLoading(false);
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setDetailError(e instanceof Error ? e.message : String(e));
          setDetail(null);
          setDetailLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [token, tab, selectedId]);

  return {
    items,
    loading,
    error,
    filters,
    setFilters,
    selectedId,
    select: setSelectedId,
    detail,
    detailLoading,
    detailError,
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webui && bun run test -- src/tests/test_use_robot_library.ts`
Expected: 4 PASS

- [ ] **Step 5: Verify & checkpoint**

Run: `cd webui && bun run test -- src/tests/test_use_robot_library.ts && bunx tsc -p tsconfig.build.json --noEmit`
Expected: tests pass; tsc clean. No git commit.

---

## Task 4: Frontend — library page components

**Files:**
- Create: `webui/src/robot/library/CommandLibraryPage.tsx`
- Create: `webui/src/robot/library/LibraryList.tsx`
- Create: `webui/src/robot/library/CommandDetail.tsx`
- Create: `webui/src/robot/library/FlowDetail.tsx`
- Test: `webui/src/tests/test_command_library_page.tsx`

- [ ] **Step 1: Write the failing test**

```typescript
// webui/src/tests/test_command_library_page.tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nextProvider } from "react-i18next";
import i18n from "@/i18n";

vi.mock("@/robot/hooks/useRobotLibrary", () => ({
  useRobotLibrary: vi.fn(),
}));

import { useRobotLibrary } from "@/robot/hooks/useRobotLibrary";
import { CommandLibraryPage } from "@/robot/library/CommandLibraryPage";
import type { LibraryCommand, LibraryFlow } from "@/lib/robot-library-api";

function renderPage() {
  return render(
    <I18nextProvider i18n={i18n}>
      <CommandLibraryPage token="tok" />
    </I18nextProvider>,
  );
}

afterEach(() => vi.mocked(useRobotLibrary).mockReset());

describe("CommandLibraryPage", () => {
  it("renders the commands tab with list items and switches to flows", async () => {
    vi.mocked(useRobotLibrary).mockImplementation((_token, tab) => ({
      items: tab === "commands"
        ? [{ id: "home", name: "home", component_id: "linear_move" } as LibraryCommand]
        : [{ name: "PickPlace" } as LibraryFlow],
      loading: false,
      error: null,
      filters: { q: "", component_id: "", risk_level: "", status: "" },
      setFilters: vi.fn(),
      selectedId: null,
      select: vi.fn(),
      detail: null,
      detailLoading: false,
      detailError: null,
    }));
    renderPage();
    expect(screen.getByTestId("command-library-page")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "home" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /Flows/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: "PickPlace" })).toBeInTheDocument());
  });

  it("renders the empty state", () => {
    vi.mocked(useRobotLibrary).mockReturnValue({
      items: [], loading: false, error: null,
      filters: { q: "", component_id: "", risk_level: "", status: "" },
      setFilters: vi.fn(), selectedId: null, select: vi.fn(),
      detail: null, detailLoading: false, detailError: null,
    });
    renderPage();
    expect(screen.getByText(/No items/i)).toBeInTheDocument();
  });

  it("renders the error state", () => {
    vi.mocked(useRobotLibrary).mockReturnValue({
      items: [], loading: false, error: "boom",
      filters: { q: "", component_id: "", risk_level: "", status: "" },
      setFilters: vi.fn(), selectedId: null, select: vi.fn(),
      detail: null, detailLoading: false, detailError: null,
    });
    renderPage();
    expect(screen.getByText(/boom/)).toBeInTheDocument();
  });

  it("renders command detail when selected", async () => {
    const cmd = {
      id: "home", name: "home", component_id: "linear_move",
      parameters: { target_z: 1270.0 }, aliases: ["回零"], description: "go home",
      risk_level: "high", status: "published", version: 1, source: "legacy-import",
      created_by: "", created_at: "", updated_at: "", published_at: "",
    } as LibraryCommand;
    vi.mocked(useRobotLibrary).mockReturnValue({
      items: [cmd], loading: false, error: null,
      filters: { q: "", component_id: "", risk_level: "", status: "" },
      setFilters: vi.fn(), selectedId: "home", select: vi.fn(),
      detail: cmd, detailLoading: false, detailError: null,
    });
    renderPage();
    expect(screen.getByText("target_z")).toBeInTheDocument();
    expect(screen.getByText("1270")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webui && bun run test -- src/tests/test_command_library_page.tsx`
Expected: FAIL with `Failed to resolve import "@/robot/library/CommandLibraryPage"`

- [ ] **Step 3: Implement the detail components**

```tsx
// webui/src/robot/library/CommandDetail.tsx
import { useTranslation } from "react-i18next";
import type { LibraryCommand } from "@/lib/robot-library-api";

export function CommandDetail({ command }: { command: LibraryCommand }) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-3 p-4">
      <h2 className="text-lg font-semibold">{command.name}</h2>
      {command.description ? <p className="text-sm text-muted-foreground">{command.description}</p> : null}
      {command.aliases.length > 0 ? (
        <p className="text-xs text-muted-foreground">{t("library.aliases", { defaultValue: "Aliases" })}: {command.aliases.join(", ")}</p>
      ) : null}
      <dl className="grid grid-cols-2 gap-2 text-sm">
        <div><dt className="text-xs text-muted-foreground">component_id</dt><dd className="font-mono">{command.component_id}</dd></div>
        <div><dt className="text-xs text-muted-foreground">risk_level</dt><dd>{command.risk_level}</dd></div>
        <div><dt className="text-xs text-muted-foreground">status</dt><dd>{command.status}</dd></div>
        <div><dt className="text-xs text-muted-foreground">version</dt><dd>{command.version}</dd></div>
      </dl>
      <div>
        <p className="text-xs text-muted-foreground">parameters</p>
        <table className="mt-1 w-full text-xs">
          <tbody>
            {Object.entries(command.parameters).map(([k, v]) => (
              <tr key={k} className="border-b border-border/40">
                <td className="py-1 pr-2 font-mono">{k}</td>
                <td className="py-1 font-mono">{String(v)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

```tsx
// webui/src/robot/library/FlowDetail.tsx
import { useTranslation } from "react-i18next";
import type { LibraryFlow } from "@/lib/robot-library-api";

export function FlowDetail({ flow }: { flow: LibraryFlow }) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-3 p-4">
      <h2 className="text-lg font-semibold">{flow.name}</h2>
      {flow.description ? <p className="text-sm text-muted-foreground">{flow.description}</p> : null}
      <dl className="grid grid-cols-2 gap-2 text-sm">
        <div><dt className="text-xs text-muted-foreground">state</dt><dd>{flow.state}</dd></div>
        <div><dt className="text-xs text-muted-foreground">version</dt><dd>{flow.version}</dd></div>
        <div><dt className="text-xs text-muted-foreground">confirmed</dt><dd>{flow.confirmed ? t("library.yes", { defaultValue: "yes" }) : t("library.no", { defaultValue: "no" })}</dd></div>
        <div><dt className="text-xs text-muted-foreground">step_delay_ms</dt><dd>{flow.step_delay_ms}</dd></div>
      </dl>
      <div>
        <p className="text-xs text-muted-foreground">steps</p>
        <ol className="mt-1 flex flex-col gap-1 text-xs">
          {flow.steps.map((step) => (
            <li key={step.step_id} className="rounded border border-border/40 p-2">
              <span className="font-mono">#{step.step_id}</span> {step.action}
              <span className="ml-2 text-muted-foreground">func={step.func_id}</span>
              {step.description ? <p className="text-muted-foreground">{step.description}</p> : null}
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
```

```tsx
// webui/src/robot/library/LibraryList.tsx
import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/input";
import type { LibraryCommand, LibraryFlow } from "@/lib/robot-library-api";
import type { LibraryFilters, LibraryTab } from "@/robot/hooks/useRobotLibrary";

interface LibraryListProps {
  tab: LibraryTab;
  items: LibraryCommand[] | LibraryFlow[];
  loading: boolean;
  error: string | null;
  filters: LibraryFilters;
  onFiltersChange: (patch: Partial<LibraryFilters>) => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function LibraryList({
  tab, items, loading, error, filters, onFiltersChange, selectedId, onSelect,
}: LibraryListProps) {
  const { t } = useTranslation();
  return (
    <div className="flex w-72 shrink-0 flex-col gap-2 overflow-y-auto border-r border-border/70 bg-muted/20 p-3 lg:flex">
      <Input
        aria-label={t("library.search", { defaultValue: "Search" })}
        placeholder={t("library.search", { defaultValue: "Search" })}
        value={filters.q}
        onChange={(e) => onFiltersChange({ q: e.target.value })}
      />
      {tab === "commands" ? (
        <select
          aria-label={t("library.filters.risk", { defaultValue: "Risk level" })}
          className="h-8 rounded border border-border/60 bg-background px-2 text-xs"
          value={filters.risk_level}
          onChange={(e) => onFiltersChange({ risk_level: e.target.value })}
        >
          <option value="">{t("library.filters.risk", { defaultValue: "Risk level" })}</option>
          <option value="low">low</option>
          <option value="medium">medium</option>
          <option value="high">high</option>
          <option value="critical">critical</option>
        </select>
      ) : null}
      {loading ? <p className="text-xs text-muted-foreground">…</p> : null}
      {error ? <p className="text-xs text-destructive">{error}</p> : null}
      {!loading && !error && items.length === 0 ? (
        <p className="text-xs text-muted-foreground">{t("library.empty", { defaultValue: "No items." })}</p>
      ) : null}
      <div className="flex flex-col gap-1">
        {items.map((item) => {
          const id = (item as LibraryCommand).id ?? (item as LibraryFlow).name;
          const label = (item as LibraryCommand).name ?? (item as LibraryFlow).name;
          const sub = tab === "commands"
            ? (item as LibraryCommand).component_id
            : `${(item as LibraryFlow).steps.length} steps`;
          return (
            <button
              key={id}
              type="button"
              onClick={() => onSelect(id)}
              aria-current={selectedId === id ? "page" : undefined}
              className="flex flex-col items-start rounded px-2 py-1.5 text-left text-xs hover:bg-accent/50"
            >
              <span className="font-medium">{label}</span>
              <span className="text-muted-foreground">{sub}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
```

```tsx
// webui/src/robot/library/CommandLibraryPage.tsx
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { LibraryList } from "@/robot/library/LibraryList";
import { CommandDetail } from "@/robot/library/CommandDetail";
import { FlowDetail } from "@/robot/library/FlowDetail";
import { useRobotLibrary, type LibraryTab } from "@/robot/hooks/useRobotLibrary";

export function CommandLibraryPage({ token }: { token: string }) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<LibraryTab>("commands");
  const lib = useRobotLibrary(token, tab);
  const isCommand = tab === "commands";

  return (
    <div data-testid="command-library-page" className="flex h-full w-full overflow-hidden">
      <div className="flex min-w-0 flex-1 flex-col">
        <div role="tablist" className="flex gap-1 border-b border-border/70 px-3 py-2">
          <button
            type="button"
            role="tab"
            aria-selected={isCommand}
            onClick={() => setTab("commands")}
            className="rounded px-3 py-1 text-sm font-medium hover:bg-accent/50"
          >
            {t("library.tabs.commands", { defaultValue: "Commands" })}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={!isCommand}
            onClick={() => setTab("flows")}
            className="rounded px-3 py-1 text-sm font-medium hover:bg-accent/50"
          >
            {t("library.tabs.flows", { defaultValue: "Flows" })}
          </button>
        </div>
        <div className="flex min-h-0 flex-1 overflow-hidden">
          <LibraryList
            tab={tab}
            items={lib.items}
            loading={lib.loading}
            error={lib.error}
            filters={lib.filters}
            onFiltersChange={lib.setFilters}
            selectedId={lib.selectedId}
            onSelect={lib.select}
          />
          <div className="flex min-w-0 flex-1 flex-col overflow-y-auto">
            {lib.detailError ? <p className="p-4 text-sm text-destructive">{lib.detailError}</p> : null}
            {lib.detailLoading ? <p className="p-4 text-sm text-muted-foreground">…</p> : null}
            {!lib.detail && !lib.detailLoading && !lib.detailError ? (
              <p className="p-4 text-sm text-muted-foreground">
                {t("library.detail.selectPrompt", { defaultValue: "Select an item to view details." })}
              </p>
            ) : null}
            {lib.detail && isCommand ? (
              <CommandDetail command={lib.detail as import("@/lib/robot-library-api").LibraryCommand} />
            ) : null}
            {lib.detail && !isCommand ? (
              <FlowDetail flow={lib.detail as import("@/lib/robot-library-api").LibraryFlow} />
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webui && bun run test -- src/tests/test_command_library_page.tsx`
Expected: 4 PASS

- [ ] **Step 5: Verify & checkpoint**

Run: `cd webui && bun run test -- src/tests/test_command_library_page.tsx && bunx tsc -p tsconfig.build.json --noEmit`
Expected: tests pass; tsc clean. No git commit.

---

## Task 5: Sidebar + App routing + i18n

**Files:**
- Modify: `webui/src/components/Sidebar.tsx`
- Modify: `webui/src/App.tsx`
- Modify: `webui/src/i18n/locales/en/common.json`
- Modify: `webui/src/i18n/locales/zh-CN/common.json`
- Test: `webui/src/tests/app-layout.test.tsx` (append)

- [ ] **Step 1: Write the failing tests (append to `app-layout.test.tsx`)**

Append two tests inside the existing `describe("App layout", ...)` block:

```typescript
  it("removes Apps/Skills from the sidebar and adds the command library entry", async () => {
    mockFetchRoutes({ "/api/settings": baseSettingsPayload() });
    render(<App />);
    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    expect(within(sidebar).queryByRole("button", { name: "Apps" })).not.toBeInTheDocument();
    expect(within(sidebar).queryByRole("button", { name: "Skills" })).not.toBeInTheDocument();
    expect(within(sidebar).getByRole("button", { name: "Commands" })).toBeInTheDocument();
  });

  it("hides RobotSidePanel on #/library whether mounted directly or navigated from #/operator", async () => {
    const libraryRoutes = {
      "/api/settings": baseSettingsPayload(),
      "/api/robot/status": { ok: true, data: { robot_state: { mode: "idle" }, execution_mode: "dry_run_only" } },
      "/api/robot/library/commands": { ok: true, data: { items: [], total: 0 } },
      "/api/robot/library/flows": { ok: true, data: { items: [], total: 0 } },
    };

    // (b) Direct #/library mount on native surface.
    vi.mocked(fetchBootstrap).mockResolvedValue({
      token: "tok", ws_path: "/", expires_in: 300, runtime_surface: "native",
    });
    window.history.replaceState(null, "", "/#/library");
    mockFetchRoutes(libraryRoutes);
    const { unmount } = render(<App />);
    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.getByTestId("command-library-page")).toBeInTheDocument(),
    );
    expect(screen.queryByText("机械手状态")).not.toBeInTheDocument();
    unmount();

    // (a) Mount at #/operator (RobotSidePanel present), then navigate to #/library.
    window.history.replaceState(null, "", "/#/operator");
    mockFetchRoutes(libraryRoutes);
    render(<App />);
    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByText("机械手状态")).toBeInTheDocument());
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    fireEvent.click(within(sidebar).getByRole("button", { name: "Commands" }));
    await waitFor(() =>
      expect(screen.getByTestId("command-library-page")).toBeInTheDocument(),
    );
    expect(screen.queryByText("机械手状态")).not.toBeInTheDocument();
    expect(window.location.hash).toBe("#/library");
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd webui && bun run test -- src/tests/app-layout.test.tsx`
Expected: FAIL — Apps/Skills still present, no Commands button; RobotSidePanel not hidden on #/library.

- [ ] **Step 3: Add i18n keys**

In `webui/src/i18n/locales/en/common.json`, change the `sidebar` block's `skills` entry to add `commandLibrary`:

```json
    "skills": {
      "title": "Skills"
    },
    "commandLibrary": "Commands"
```

And add a new top-level `library` namespace right after the `sidebar` block (before `"settings":`):

```json
  "library": {
    "tabs": { "commands": "Commands", "flows": "Flows" },
    "search": "Search",
    "aliases": "Aliases",
    "filters": { "component": "Component", "risk": "Risk level", "state": "State", "confirmed": "Confirmed" },
    "empty": "No items.",
    "error": "Failed to load.",
    "yes": "yes",
    "no": "no",
    "detail": { "selectPrompt": "Select an item to view details." }
  },
```

In `webui/src/i18n/locales/zh-CN/common.json`, mirror the same structure (the `sidebar` block already has `skills.title`; add `commandLibrary` and the `library` namespace):

```json
    "commandLibrary": "命令库"
```

(after `skills`) and:

```json
  "library": {
    "tabs": { "commands": "命令", "flows": "流程" },
    "search": "搜索",
    "aliases": "别名",
    "filters": { "component": "组件", "risk": "风险级别", "state": "状态", "confirmed": "已确认" },
    "empty": "暂无内容。",
    "error": "加载失败。",
    "yes": "是",
    "no": "否",
    "detail": { "selectPrompt": "选择一项以查看详情。" }
  },
```

- [ ] **Step 4: Modify `Sidebar.tsx`**

In the lucide-react import (lines 2-11), replace `Archive, Brain, CalendarClock, Menu, Search, Settings, SquarePen, Blocks` with `Archive, BookOpen, CalendarClock, Menu, Search, Settings, SquarePen` (remove `Brain` + `Blocks`, add `BookOpen`).

In `SidebarProps`, remove `onOpenApps: () => void;` and `onOpenSkills: () => void;`, and add `onOpenLibrary: () => void;`. Extend `activeUtility` to `"apps" | "skills" | "automations" | "library" | null`.

Replace the Apps + Skills buttons (the two `SidebarActionButton` blocks using `Blocks`/`Brain`) with a single 命令库 button:

```tsx
        <SidebarActionButton
          collapsed={collapsed}
          label={t("sidebar.commandLibrary")}
          onClick={props.onOpenLibrary}
          active={props.activeUtility === "library"}
          icon={<BookOpen className="h-4 w-4" />}
        />
```

(Place it after the Search `SidebarActionButton` and before the Automations one.)

- [ ] **Step 5: Modify `App.tsx`**

1. Add the import near the other `@/robot` import (after line 18):
```typescript
import { CommandLibraryPage } from "@/robot/library/CommandLibraryPage";
```

2. Extend `ShellView` (line 77):
```typescript
type ShellView = "chat" | "settings" | "apps" | "automations" | "skills" | "library";
```

3. In `readShellRoute`, add a `/library` case before the `/operator` case (before line 142):
```typescript
  if (path === "/library") {
    return { view: "library", activeKey, settingsSection: "overview" };
  }
```

4. Remove `onOpenApps` and `onOpenSkills` handlers (the two `useCallback` blocks ~1222-1238) and add `onOpenLibrary`:
```typescript
  const onOpenLibrary = useCallback(() => {
    setSessionSearchOpen(false);
    navigate({ view: "library", activeKey, settingsSection: "overview" });
    setMobileSidebarOpen(false);
  }, [activeKey, navigate]);
```

5. In `sidebarProps`, remove `onOpenApps,` and `onOpenSkills,`, add `onOpenLibrary,`. Extend the `activeUtility` expression (line ~1444) to include library:
```typescript
    activeUtility: view === "apps" || view === "automations" || view === "skills" || view === "library" ? view : null,
```

6. In the center render block (the `{view !== "chat" && (` SettingsView block ~1631), change the condition to exclude `library` and add a library branch:
```tsx
            {view !== "chat" && view !== "library" && (
              <div className="absolute inset-0 flex flex-col">
                <SettingsView
                  ...
                />
              </div>
            )}
            {view === "library" && (
              <div className="absolute inset-0 flex flex-col">
                <CommandLibraryPage token={token} />
              </div>
            )}
```

7. Gate `rightPanel` (line ~1654):
```tsx
          {view !== "library" && rightPanel}
```

8. In the `document.title` effect (after the `view === "skills"` block ~1415), add:
```typescript
    if (view === "library") {
      document.title = t("app.documentTitle.chat", {
        title: t("sidebar.commandLibrary"),
      });
      return;
    }
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd webui && bun run test -- src/tests/app-layout.test.tsx`
Expected: all pass (existing + 2 new). Note: the existing test `places Automations after Skills` and `opens Apps from the main sidebar` / `opens Skills from the main sidebar` reference removed buttons — **update or remove those existing tests** that assert Apps/Skills buttons exist (they will now fail). Specifically: remove the `places Automations after Skills` test's Apps/Skills assertions (or the whole test), and remove `opens Apps from the main sidebar` + `opens Skills from the main sidebar` tests (the buttons no longer exist; Apps/Skills are still reachable via Settings but those tests clicked the sidebar button). Replace them with the new `removes Apps/Skills...` test above.

- [ ] **Step 7: Verify & checkpoint**

Run: `cd webui && bun run test -- src/tests/app-layout.test.tsx && bunx tsc -p tsconfig.build.json --noEmit && bun run lint`
Expected: tests pass; tsc clean; eslint clean. No git commit.

---

## Task 6: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Full backend suite**

Run: `cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m pytest tests/robot_ai/ -q`
Expected: all pass (A1 + A2 backend; FlowRegistry/flow execute tests unchanged).

- [ ] **Step 2: Full frontend suite**

Run: `cd webui && bun run test`
Expected: all pass.

- [ ] **Step 3: Typecheck + lint + ruff**

Run: `cd webui && bunx tsc -p tsconfig.build.json --noEmit && bun run lint`
Run: `cd nanobot-main-1 && .venv-robot-desktop/Scripts/python.exe -m ruff check nanobot/ robot_ai/ tools/ tests/`
Expected: all clean.

- [ ] **Step 4: Boundary check**

Run: `cd nanobot-main-1 && git status --short -- webui/src/robot/components/RobotSidePanel.tsx webui/src/robot/pages/RobotOperatorApp.tsx robot_ai/flow/`
Expected: no output (none of these files modified by A2).

- [ ] **Step 5: Final checkpoint — no commit**

All tests pass, tsc/eslint/ruff clean, boundaries respected. Do NOT `git add`/`commit` — user commits unified later. Report completion.

---

## Self-Review

**1. Spec coverage:**
- §3 read-only flow API (list/detail, FlowRegistry read-only, token gate) → Task 1 (process + handle + register + ws_http + tests).
- §4 Sidebar (remove Apps/Skills, add 命令库, props cleanup) → Task 5 Step 4.
- §5 routing & Shell (ShellView "library", `#/library`, onOpenLibrary, render page, rightPanel gate, shouldUseRobotOperatorApp unchanged) → Task 5 Step 5.
- §6 library page (CommandLibraryPage tabs, LibraryList, CommandDetail, FlowDetail, useRobotLibrary, robot-library-api) → Tasks 2, 3, 4.
- §7 i18n → Task 5 Step 3.
- §8 security (token gate via ws_http) → Task 1 (flow paths inherit gate).
- §9 tests (backend flow, frontend api/hook/page, regression test) → Tasks 1-5.
- §10 acceptance (Sidebar no Apps/Skills; #/library page; RobotSidePanel hidden both paths; flow API read-only; chat/confirm/execute unchanged; FlowRegistry read-only) → Task 6 + each task's verify.
- Hard constraints (no RobotOperatorApp/RobotSidePanel/flow/chat/confirm/execute changes) → Task 6 Step 4 boundary check.

**2. Placeholder scan:** No TBD/TODO/"add validation". Every code step shows full code; every test shows runnable test code; every command shows expected output. The one judgment call is Task 5 Step 6's note to remove now-stale Apps/Skills sidebar tests — called out explicitly with which tests to remove.

**3. Type/signature consistency:**
- `useRobotLibrary(token, tab)` returns `{items, loading, error, filters, setFilters, selectedId, select, detail, detailLoading, detailError}` — defined Task 3, consumed in CommandLibraryPage (Task 4) with matching destructured fields.
- `LibraryList` props `{tab, items, loading, error, filters, onFiltersChange, selectedId, onSelect}` — defined Task 4, passed by CommandLibraryPage with matching props (`onFiltersChange={lib.setFilters}`, `onSelect={lib.select}`).
- `robotLibraryCommands(token, filters)` / `robotLibraryCommand(token, id)` / `robotLibraryFlows(token)` / `robotLibraryFlow(token, name)` — defined Task 2, called in useRobotLibrary (Task 3) with matching signatures.
- `CommandLibraryPage({token})` — defined Task 4, rendered in App.tsx (Task 5) as `<CommandLibraryPage token={token} />`.
- Backend: `process_robot_library_flows(*, flow_registry_path)` / `process_robot_library_flow(name, *, flow_registry_path)` — defined + registered + ws_http-dispatched with matching kwargs.
- `data-testid="command-library-page"` — set in CommandLibraryPage (Task 4), asserted in app-layout regression test (Task 5).
- RobotSidePanel marker `机械手状态` — read from RobotSidePanel.tsx line 74 (hardcoded, not i18n), asserted in regression test without modifying the component.

No gaps found. Plan complete.
