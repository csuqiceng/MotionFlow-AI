from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PLACEHOLDER = "__ORGANIZATION_API_KEY__"
CREDENTIAL_FIELD = re.compile(
    r"(?:api[_-]?key|authorization|credential|password|secret|token)$",
    re.IGNORECASE,
)


def _credential_violations(value: Any, path: str = "providers") -> list[str]:
    violations: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            nested_path = f"{path}.{key}"
            if (
                CREDENTIAL_FIELD.search(str(key))
                and nested is not None
                and nested != ""
                and nested != PLACEHOLDER
            ):
                violations.append(nested_path)
            violations.extend(_credential_violations(nested, nested_path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            violations.extend(_credential_violations(nested, f"{path}[{index}]"))
    return violations


def test_tracked_provider_configs_never_contain_real_credentials() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "--", "*.json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    violations: list[str] = []
    for relative in tracked:
        path = ROOT / relative
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and isinstance(payload.get("providers"), dict):
            violations.extend(
                f"{relative}:{field}"
                for field in _credential_violations(payload["providers"])
            )
    assert violations == []


def test_local_desktop_view_config_is_untracked_and_ignored() -> None:
    assert not (ROOT / "desktop" / ".view-config.json").exists()
    ignored = (ROOT / "desktop" / ".gitignore").read_text(encoding="utf-8")
    assert ".view-config.json" in ignored.splitlines()
