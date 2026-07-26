# MotionFlow AI Windows Build Guide

## What is built

The Windows installer contains an Electron desktop shell and one bundled
`robot_server.exe`. The shell picks a loopback port, starts that service, and
stops its process tree when the application exits. The React single-page UI is
served by `robot_server`; it is not replaced during packaging.

The product has no gateway executable, external chat channels, or DM pairing
service.

| Output | Location |
| --- | --- |
| Bundled Python runtime | `desktop/pyinstaller/dist-robot-server/py-runtime/` |
| Unpacked Electron application | `desktop/release2/win-unpacked/` |
| NSIS installer | `desktop/release2/motionflow-ai-Setup-<version>.exe` |
| Installer checksum | adjacent `.sha256` file |

`desktop/pyinstaller/robot_server.spec` is a versioned packaging input.  It
collects the configuration-selected ZMotion adapter explicitly and excludes
retired gateway/channel/pairing modules, so a clean checkout can reproduce the
same runtime layout.

## Prerequisites

- Windows 10/11 x64
- Python 3.11 or later
- Node.js 18 or later with npm
- ZMotion SDK files in `vendor/zmotion/`
- Build venv at `desktop/.build-venv/` (the legacy build script creates it)

The release script accepts the organization API key as a PowerShell
`SecureString`; do not place it in source files or shell history.

## Local development checks

```powershell
cd nanobot-main-1\webui
npm test -- --run
npm run build

cd ..\desktop
npm run build
node electron\tests\product-manifest.test.js
node electron\tests\before-pack.test.js
node electron\tests\packaged-robot-server-launch.test.js
```

## Release build

From `nanobot-main-1` run:

```powershell
cd desktop
.\package-win.ps1
```

The script securely prompts for the API key, then performs a clean PyInstaller
build, Electron build, NSIS packaging, release verification, and a smoke test
against the packaged `robot_server.exe`. It deliberately removes only its own
`desktop/pyinstaller/build-robot-server`, `desktop/pyinstaller/dist-robot-server`
and `desktop/release2` output directories before rebuilding.

To validate the packaging path locally without supplying an organization key,
run the PyInstaller command, `npm run build`, `npm run dist`, `npm run
verifyRelease`, and `npm run smokePackagedRobotServer` in that order. The
builder then uses the placeholder key and shows the first-run wizard; this is a
structure/startup regression check only, not a signed production release.

For a development-only full build that recreates the virtual environment, use
`./desktop/build-desktop.ps1` from `nanobot-main-1`. The official release path
is still `package-win.ps1`, because it also performs the installer, checksum,
and runtime smoke validations.

## Release acceptance

- `Analysis-00.toc` must not contain `nanobot.channels`, `nanobot.gateway`, or
  `nanobot.pairing`.
- The packaged smoke test must reach `/health` and the WebUI from a single
  local robot-server process.
- Login, AI preflight, chat streaming (including reasoning/tool/progress),
  command library, automatic tasks, settings, and robot controls must remain
  available through the retained WebUI.
- Test dry-run and real-write safety gates separately; never use a real robot
  to compensate for a failing dry-run test.
