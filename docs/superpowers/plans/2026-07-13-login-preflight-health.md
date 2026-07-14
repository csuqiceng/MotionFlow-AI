# Login Preflight Health Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add real controller, voice, and AI preflight checks to the legacy-style WebUI login page, blocking only operator login when the edited controller address is not confirmed healthy.

**Architecture:** A new synchronous WebUI preflight service performs bounded controller, TTS, and active-provider probes and returns one normalized payload. `WsHttpGateway` exposes it through the bootstrap bearer-token gate. The React app loads the check after bootstrap and passes stateful results into a redesigned `LoginPage`.

**Tech Stack:** Python 3.11, asyncio, Pydantic configuration, React, TypeScript, Vitest, pytest

---

### Task 1: Preflight service contract and safe controller target validation

**Files:**
- Create: `nanobot-main-1/nanobot/webui/login_preflight.py`
- Create: `nanobot-main-1/tests/webui/test_login_preflight.py`

- [ ] **Step 1: Write failing target-validation tests**

```python
@pytest.mark.parametrize("host", ["10.168.3.21", "192.168.1.20", "127.0.0.1"])
def test_validate_controller_host_accepts_private_and_loopback(host: str) -> None:
    assert validate_controller_host(host) == host

@pytest.mark.parametrize("host", ["", "example.com", "8.8.8.8", "http://10.168.3.21"])
def test_validate_controller_host_rejects_non_private_targets(host: str) -> None:
    with pytest.raises(PreflightInputError):
        validate_controller_host(host)
```

- [ ] **Step 2: Run the validation tests and verify RED**

Run: `.venv-robot-desktop\\Scripts\\python.exe -m pytest -q tests/webui/test_login_preflight.py -k controller_host`

Expected: collection fails because `nanobot.webui.login_preflight` does not exist.

- [ ] **Step 3: Create the normalized result types and validator**

```python
class PreflightInputError(ValueError):
    pass

def validate_controller_host(value: object) -> str:
    raw = str(value or "").strip()
    try:
        address = ipaddress.ip_address(raw)
    except ValueError as exc:
        raise PreflightInputError("controller_host must be an IP address") from exc
    if not (address.is_private or address.is_loopback):
        raise PreflightInputError("controller_host must be private or loopback")
    return raw
```

- [ ] **Step 4: Run validation tests and verify GREEN**

Run: `.venv-robot-desktop\\Scripts\\python.exe -m pytest -q tests/webui/test_login_preflight.py -k controller_host`

Expected: all selected tests pass.

### Task 2: Real, bounded probes with independent failures

**Files:**
- Modify: `nanobot-main-1/nanobot/webui/login_preflight.py`
- Modify: `nanobot-main-1/tests/webui/test_login_preflight.py`

- [ ] **Step 1: Write failing aggregate-probe tests**

```python
def test_preflight_returns_all_services_when_voice_probe_fails(monkeypatch) -> None:
    monkeypatch.setattr(preflight, "probe_controller", lambda host: {"state": "healthy", "latency_ms": 4})
    monkeypatch.setattr(preflight, "probe_voice", lambda config: {"state": "unhealthy", "reason": "voice timeout", "latency_ms": 20})
    monkeypatch.setattr(preflight, "probe_ai", lambda config: {"state": "healthy", "latency_ms": 18})

    result = preflight.run_login_preflight("10.168.3.21", config=Config())

    assert result["controller"]["state"] == "healthy"
    assert result["voice"] == {"state": "unhealthy", "reason": "voice timeout", "latency_ms": 20}
    assert result["ai"]["state"] == "healthy"
```

- [ ] **Step 2: Run aggregate tests and verify RED**

Run: `.venv-robot-desktop\\Scripts\\python.exe -m pytest -q tests/webui/test_login_preflight.py -k preflight_returns`

Expected: FAIL because `run_login_preflight` is not defined.

- [ ] **Step 3: Implement probes with a shared safe result shape**

```python
def _result(name: str, action: Callable[[], None]) -> dict[str, object]:
    started = time.perf_counter()
    try:
        action()
    except Exception as exc:
        return {"state": "unhealthy", "reason": _safe_reason(name, exc), "latency_ms": _elapsed_ms(started)}
    return {"state": "healthy", "latency_ms": _elapsed_ms(started)}

def run_login_preflight(controller_host: object, *, config: Config | None = None) -> dict[str, dict[str, object]]:
    host = validate_controller_host(controller_host)
    current = config or load_config()
    return {
        "controller": probe_controller(host),
        "voice": probe_voice(current),
        "ai": probe_ai(current),
    }
```

`probe_controller` creates an ephemeral backend using `dataclasses.replace(RobotBackendConfig.from_env(), controller_host=host)` and calls only `get_state()`. `probe_voice` resolves the active TTS configuration and runs `synthesize_text(".", effective_config)` under `asyncio.wait_for(..., timeout=5)`, discarding the returned bytes. `probe_ai` creates the configured provider and performs one `chat` request with `[{"role": "user", "content": "health"}]`, `max_tokens=1`, and a five-second timeout; an error finish reason is unhealthy. Each probe returns an independent result and never returns configuration secrets or raw provider output.

- [ ] **Step 4: Add bounded-probe tests**

```python
def test_controller_probe_only_reads_state(monkeypatch) -> None:
    backend = MagicMock()
    backend.get_state.return_value = {"mode": "idle"}
    monkeypatch.setattr(preflight, "create_robot_backend", lambda _: backend)

    result = preflight.probe_controller("10.168.3.21")

    assert result["state"] == "healthy"
    backend.get_state.assert_called_once_with()
    assert backend.method_calls == [call.get_state()]
```

- [ ] **Step 5: Run the full service test file and verify GREEN**

Run: `.venv-robot-desktop\\Scripts\\python.exe -m pytest -q tests/webui/test_login_preflight.py`

Expected: all preflight validation, independent-failure, and read-only tests pass.

### Task 3: Bootstrap-token-protected preflight HTTP route

**Files:**
- Modify: `nanobot-main-1/nanobot/webui/ws_http.py:279-351`
- Modify: `nanobot-main-1/tests/channels/test_websocket_http_routes.py`

- [ ] **Step 1: Write failing dispatcher tests**

```python
async def test_login_preflight_requires_bootstrap_api_token(http_server) -> None:
    response = await _http_get(f"{http_server}/api/login/preflight")
    assert response.status_code == 401

async def test_login_preflight_returns_service_payload(http_server, api_token, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.login_preflight.run_login_preflight", lambda host: {
        "controller": {"state": "healthy", "latency_ms": 3},
        "voice": {"state": "healthy", "latency_ms": 4},
        "ai": {"state": "unhealthy", "reason": "timeout", "latency_ms": 5000},
    })
    response = await _http_get(
        f"{http_server}/api/login/preflight",
        headers={"Authorization": f"Bearer {api_token}", "X-Nanobot-Robot-Body": '{"controller_host":"10.168.3.21"}'},
    )
    assert response.status_code == 200
    assert response.json()["data"]["ai"]["state"] == "unhealthy"
```

- [ ] **Step 2: Run route tests and verify RED**

Run: `.venv-robot-desktop\\Scripts\\python.exe -m pytest -q tests/channels/test_websocket_http_routes.py -k login_preflight`

Expected: FAIL because the route is not dispatched.

- [ ] **Step 3: Add preflight dispatch before robot/auth routes**

```python
if got == "/api/login/preflight":
    if not self.check_api_token(request):
        return _http_error(401, "Unauthorized")
    body = _robot_body_from_request(request)
    if body is None:
        return _http_error(400, "missing or invalid X-Nanobot-Robot-Body JSON payload")
    try:
        payload = run_login_preflight(body.get("controller_host"))
    except PreflightInputError as exc:
        return _http_error(400, str(exc))
    return _http_json_response({"ok": True, "data": payload})
```

Execute this synchronous preflight via `asyncio.to_thread` from `_dispatch_resolved`, matching existing robot I/O dispatch. Do not add the endpoint to the unauthenticated bootstrap exception list.

- [ ] **Step 4: Run route tests and verify GREEN**

Run: `.venv-robot-desktop\\Scripts\\python.exe -m pytest -q tests/channels/test_websocket_http_routes.py -k login_preflight`

Expected: all selected route tests pass.

### Task 4: Browser API client and legacy-style login UI

**Files:**
- Modify: `nanobot-main-1/webui/src/lib/bootstrap.ts`
- Modify: `nanobot-main-1/webui/src/App.tsx:64-70, 372-389, 528-536`
- Modify: `nanobot-main-1/webui/src/components/LoginPage.tsx`
- Modify: `nanobot-main-1/webui/src/tests/login-page.test.tsx`
- Modify: `nanobot-main-1/webui/src/tests/bootstrap.test.ts`

- [ ] **Step 1: Write failing client and UI tests**

```tsx
it("blocks operator login until the edited controller IP is healthy", () => {
  render(<LoginPage bootstrapOk error={null} preflight={healthy("10.168.3.21")} onPreflight={vi.fn()} onSubmit={vi.fn()} />);
  fireEvent.change(screen.getByLabelText(/controller address/i), { target: { value: "10.168.3.22" } });
  fillCredentials();
  expect(screen.getByRole("button", { name: /login/i })).toBeDisabled();
  expect(screen.getByText(/detect the edited controller address/i)).toBeInTheDocument();
});

it("allows engineer login while controller is unhealthy", () => {
  render(<LoginPage bootstrapOk error={null} preflight={unhealthyController()} onPreflight={vi.fn()} onSubmit={vi.fn()} />);
  fireEvent.click(screen.getByRole("tab", { name: /engineer/i }));
  fillCredentials();
  expect(screen.getByRole("button", { name: /login/i })).toBeEnabled();
});
```

- [ ] **Step 2: Run UI tests and verify RED**

Run: `npm --prefix webui test -- --run src/tests/login-page.test.tsx src/tests/bootstrap.test.ts`

Expected: TypeScript/test failure because `preflight` and `onPreflight` props do not exist.

- [ ] **Step 3: Add the typed preflight client**

```ts
export type PreflightService = {
  state: "healthy" | "unhealthy";
  latency_ms: number;
  reason?: string;
};

export async function fetchLoginPreflight(controllerHost: string, wsToken: string): Promise<LoginPreflightResponse> {
  const res = await fetchWithTimeout("/api/login/preflight", {
    method: "GET",
    credentials: "same-origin",
    headers: {
      Authorization: `Bearer ${wsToken}`,
      "X-Nanobot-Robot-Body": JSON.stringify({ controller_host: controllerHost }),
    },
  }, 8_000);
  if (!res.ok) throw new Error(`login preflight failed: HTTP ${res.status}`);
  return res.json() as Promise<LoginPreflightResponse>;
}
```

- [ ] **Step 4: Wire bootstrap, retry, and role-specific gating in `App.tsx`**

Store the current `LoginPreflightResponse` and checked controller host in the auth state. After successful `fetchBootstrap`, call `fetchLoginPreflight("10.168.3.21", boot.token)` before rendering the login page. Pass a retry callback that uses the newest `wsBootRef.current.wsToken`. A preflight failure must render per-service unhealthy state, not set `bootstrapError`.

- [ ] **Step 5: Replace the minimal form with the legacy center card**

Use semantic labels for controller IP, status messages with `role="status"`, and an accessible reason when operator login is disabled. Keep role tabs, existing error messages, throttle countdown, focus handling, `autoComplete`, and Enter-key submit. Use the selected light blue bordered card, editable IP + detect button, three status rows, and green full-width login button.

- [ ] **Step 6: Run focused frontend tests and verify GREEN**

Run: `npm --prefix webui test -- --run src/tests/login-page.test.tsx src/tests/bootstrap.test.ts`

Expected: all selected tests pass.

### Task 5: Integrated verification

**Files:**
- Test: `nanobot-main-1/tests/webui/test_login_preflight.py`
- Test: `nanobot-main-1/tests/channels/test_websocket_http_routes.py`
- Test: `nanobot-main-1/webui/src/tests/login-page.test.tsx`
- Test: `nanobot-main-1/webui/src/tests/bootstrap.test.ts`

- [ ] **Step 1: Run backend regression tests**

Run: `.venv-robot-desktop\\Scripts\\python.exe -m pytest -q tests/webui/test_login_preflight.py tests/channels/test_websocket_http_routes.py`

Expected: all tests pass.

- [ ] **Step 2: Run frontend regression tests**

Run: `npm --prefix webui test -- --run src/tests/login-page.test.tsx src/tests/bootstrap.test.ts`

Expected: all tests pass.

- [ ] **Step 3: Build the frontend**

Run: `npm --prefix webui run build`

Expected: Vite exits with code 0.

- [ ] **Step 4: Manual runtime check without a robot command**

Open the login page, confirm the editable default `10.168.3.21`, run the preflight once, change the address and confirm the operator button becomes disabled until the new address is rechecked, then switch to engineer and confirm its login button remains available. Do not submit credentials or issue any robot motion.

- [ ] **Step 5: Review the final diff**

Run: `git diff --check -- nanobot/webui/login_preflight.py nanobot/webui/ws_http.py webui/src/lib/bootstrap.ts webui/src/App.tsx webui/src/components/LoginPage.tsx tests/webui/test_login_preflight.py tests/channels/test_websocket_http_routes.py webui/src/tests/login-page.test.tsx webui/src/tests/bootstrap.test.ts`

Expected: no whitespace errors and no unrelated source changes.
