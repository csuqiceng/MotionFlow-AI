# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for the standalone ``robot_server.exe``."""

import os
from pathlib import Path


REPO_ROOT = Path(SPECPATH).resolve().parent.parent

a = Analysis(
    [str(REPO_ROOT / "desktop" / "pyinstaller" / "robot_server_launcher.py")],
    pathex=[str(REPO_ROOT)],
    binaries=[],
    datas=[
        (str(REPO_ROOT / "robot_server" / "webui"), os.path.join("robot_server", "webui")),
        (str(REPO_ROOT / "nanobot" / "templates"), os.path.join("nanobot", "templates")),
        (
            str(REPO_ROOT / "robot_platform" / "library" / "seed_query_table.json"),
            os.path.join("robot_platform", "library"),
        ),
        (
            str(REPO_ROOT / "desktop" / "electron" / "defaults" / "robot_ai"),
            os.path.join("defaults", "robot_platform"),
        ),
        (str(REPO_ROOT / "vendor" / "zmotion"), os.path.join("vendor", "zmotion")),
    ],
    hiddenimports=[
        "aiohttp",
        "ai_runtime",
        "ai_runtime.agent_runtime",
        "ai_runtime.nanobot_engine",
        "ai_runtime.tool_loader",
        "robot_server",
        "robot_server.app",
        "robot_server.runtime",
        "robot_server.robot_api",
        "robot_platform",
        "robot_platform.backends",
        # Product wiring imports this optional adapter only when selected by
        # configuration, so PyInstaller cannot discover it statically.
        "robot_platform.backends.zmotion_plugin",
        "robot_platform.backends.zmotion_adapter",
        "robot_platform.backends.zmotion_backend",
        "robot_platform.backends.zmotion_sdk",
        "robot_platform.flow",
        "robot_platform.library",
        "robot_platform.safety",
        "robot_platform.execution",
        "nanobot.agent.loop",
        "nanobot.bus",
        "nanobot.agent.tools.robot_arm",
        "nanobot.agent.tools.robot_flow",
        "nanobot.agent.tools.robot_knowledge",
        "nanobot.agent.tools.robot_position",
        "nanobot.providers.openai_compat_provider",
    ],
    excludes=[
        "tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6", "IPython", "notebook",
        # The product UI accepts text prompts only.  These optional document,
        # image and Bedrock integrations are deliberately not shipped.
        "boto3", "botocore", "s3transfer", "jmespath",
        "docx", "openpyxl", "pptx", "pypdf", "fitz", "pymupdf", "PIL",
        "nanobot.providers.bedrock_provider",
        "nanobot.command.builtin",
        # The product is one local robot service.  Retired multi-channel
        # transport and DM-pairing code must not enter the package.
        "nanobot.channels",
        "nanobot.gateway",
        "nanobot.pairing",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="robot_server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon=str(REPO_ROOT / "desktop" / "electron" / "assets" / "robot-arm-app-icon.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="py-runtime")
