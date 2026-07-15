# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the nanobot Robot AI gateway (onedir -> py-runtime).

Built by ``desktop/build-desktop.ps1``:

    pyinstaller nanobot.spec --noconfirm --clean --distpath dist --workpath build

Output: ``desktop/pyinstaller/dist/py-runtime/nanobot_gateway.exe`` (+ ``_internal``).
electron-builder then copies that tree to ``resources/py-runtime`` and the
Electron shell spawns ``nanobot_gateway.exe`` (see desktop/electron/main.ts).

nanobot discovers tools, channels, and providers dynamically via ``pkgutil``
scans, so a plain dependency analysis misses most of the package. We therefore
force-collect every submodule of ``nanobot`` and ``robot_ai`` and ship the
package data files (WebUI dist, templates, skills, seed table).
"""

from __future__ import annotations

import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

# SPECPATH is injected by PyInstaller and points at this file's directory
# (desktop/pyinstaller). The repo root is two levels up.
REPO_ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))

ENTRY = os.path.join(SPECPATH, "nanobot_gateway.py")

# --- data files bundled into the runtime -----------------------------------
datas = [
    (os.path.join(REPO_ROOT, "nanobot", "web", "dist"), "nanobot/web/dist"),
    (os.path.join(REPO_ROOT, "nanobot", "templates"), "nanobot/templates"),
    (os.path.join(REPO_ROOT, "nanobot", "skills"), "nanobot/skills"),
    (
        os.path.join(REPO_ROOT, "robot_ai", "library", "seed_query_table.json"),
        "robot_ai/library",
    ),
]

binaries = []

# --- hidden imports (dynamic discovery) ------------------------------------
hiddenimports = []
hiddenimports += collect_submodules("nanobot")
hiddenimports += collect_submodules("robot_ai")

# --- third-party packages that carry data / dynamic submodules -------------
for pkg in ("tiktoken", "tiktoken_ext"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# certifi CA bundle for outbound HTTPS to LLM/STT/TTS providers.
_certifi_datas, _certifi_binaries, _certifi_hidden = collect_all("certifi")
datas += _certifi_datas
binaries += _certifi_binaries
hiddenimports += _certifi_hidden


block_cipher = None


a = Analysis(
    [ENTRY],
    pathex=[REPO_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "pytest",
        "webview",  # desktop pywebview shell is not used by the gateway
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="nanobot_gateway",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="py-runtime",
)
