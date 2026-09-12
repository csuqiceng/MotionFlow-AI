# MotionFlow AI Engineering Guide

## Product boundary

MotionFlow AI is a local, single-page desktop application for operating a
robot arm. Electron supervises one `robot_server` process on a loopback port.
The React WebUI communicates with that service by HTTP and WebSocket. There is
no multi-channel message router, external chat integration, DM pairing, or
gateway process in this product.

## Runtime structure

- `robot_platform/`: hardware-neutral robot domain, safety policy, execution,
  library and flows. It must not import `ai_runtime`, `robot_server`, or UI
  code.
- `robot_platform/backends/`: vendor adapters. Add a new controller here;
  do not add vendor protocol details to the WebUI or HTTP/WebSocket contract.
- `ai_runtime/`: adapts the retained Nanobot agent loop and tools to local
  robot runtime events.
- `robot_server/`: the only local HTTP/WebSocket service, auth/session APIs,
  WebUI compatibility endpoints, and robot APIs.
- `webui/`: the retained React application. Preserve its routes and visual
  components; change only transport adapters when the server contract changes.
- `desktop/`: Electron lifecycle, first-run configuration, PyInstaller and
  Windows installer scripts.

## Development and verification

```powershell
# Front end
cd webui
npm test -- --run
npm run build

# Targeted Python API/runtime regression
..\desktop\.build-venv\Scripts\python.exe -m pytest `
  tests\robot_server tests\robot_ai tests\agent -q

# Electron source build and package-contract tests
cd ..\desktop
npm run build
node electron\tests\before-pack.test.js
node electron\tests\packaged-robot-server-launch.test.js
```

Run the desktop application from `desktop` with `npm start` (or the project's
development command). It chooses one ephemeral loopback port and starts
`robot_server`; it must not launch a second Python service.

## Invariants

- All real robot writes require explicit execution authorization; dry-run must
  remain safe and usable without a controller.
- Emergency-stop confirmation may never be weakened by UI, API, or agent work.
- Do not expose provider keys, robot credentials, or user passwords in logs,
  source, documentation, or test output.
- Keep the legacy WebUI event protocol compatible while migrating internal
  runtime producers. In particular preserve token, tool, progress, reasoning,
  and final events.
- A distributable is valid only after a clean PyInstaller build and the
  packaged robot-server smoke test pass.
