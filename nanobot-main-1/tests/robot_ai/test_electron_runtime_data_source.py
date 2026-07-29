from __future__ import annotations

from pathlib import Path
import json


ROOT = Path(__file__).resolve().parents[2]


def test_electron_uses_dedicated_runtime_child_and_explicit_portable_flag() -> None:
    source = (ROOT / "desktop" / "electron" / "main.ts").read_text(encoding="utf-8")

    manifest = (ROOT / "desktop" / "electron" / "product-manifest.ts").read_text(encoding="utf-8")

    assert "loadProductManifest" in source
    assert "productManifest.resolveDataDir()" in source
    assert 'context.argv.includes("--portable")' in manifest
    assert 'path.join(path.dirname(context.execPath), "data", "nanobot")' in manifest


def test_electron_forces_nanobot_home_after_desktop_environment_expansion() -> None:
    source = (ROOT / "desktop" / "electron" / "main.ts").read_text(encoding="utf-8")
    manifest = (ROOT / "desktop" / "electron" / "product-manifest.ts").read_text(encoding="utf-8")

    assert "productManifest.serverEnvironment(" in source
    assert "...persisted," in manifest
    assert "NANOBOT_HOME: dataDir," in manifest
    assert manifest.index("...persisted,") < manifest.index("NANOBOT_HOME: dataDir,")


def test_electron_passes_one_server_port_without_gateway_runtime_overrides() -> None:
    source = (ROOT / "desktop" / "electron" / "main.ts").read_text(encoding="utf-8")
    manifest = (ROOT / "desktop" / "electron" / "product-manifest.ts").read_text(encoding="utf-8")

    assert "ROBOT_SERVER_PORT: String(port)" in manifest
    assert "const serverCommand = productManifest.serverCommand(serverPort, configPath);" in source
    assert "NANOBOT_RUNTIME_CHANNEL_PORT" not in source
    assert "NANOBOT_RUNTIME_GATEWAY_PORT" not in source


def test_windows_dev_launcher_bypasses_the_node_electron_cli_wrapper() -> None:
    package = json.loads((ROOT / "desktop" / "package.json").read_text(encoding="utf-8"))
    command = package["scripts"]["dev"]

    assert "cross-env" not in command
    assert "electron\\dist\\electron.exe" in command


def test_electron_rejects_uninjected_key_and_writes_wizard_to_runtime_root() -> None:
    source = (ROOT / "desktop" / "electron" / "main.ts").read_text(encoding="utf-8")

    assert '"__ORGANIZATION_API_KEY__"' in source
    assert "resolveRuntimeDataDir()" in source
    assert 'path.join(app.getPath("userData"), "config.json")' not in source


def test_packaging_uses_a_template_and_ci_generation_not_a_repo_secret() -> None:
    builder = (ROOT / "desktop" / "electron-builder.yml").read_text(encoding="utf-8")
    generator = ROOT / "desktop" / "electron" / "before-pack.js"
    template = ROOT / "desktop" / "electron" / "config.default.template.json"

    assert "beforePack: electron/before-pack.js" in builder
    assert generator.exists()
    assert template.exists()
    assert "NANOBOT_ORGANIZATION_API_KEY" in generator.read_text(encoding="utf-8")
