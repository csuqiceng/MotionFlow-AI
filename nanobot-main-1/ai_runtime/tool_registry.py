"""SDK-neutral Tool manifest registry and eligibility policy."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass

from ai_runtime.tool_manifest import ToolManifest


@dataclass(frozen=True)
class ToolEligibility:
    eligible: bool
    code: str = ""
    message: str = ""


class ToolRegistry:
    def __init__(self) -> None:
        self._manifests: dict[str, ToolManifest] = {}

    @property
    def manifests(self) -> tuple[ToolManifest, ...]:
        return tuple(self._manifests.values())

    def register(self, manifest: ToolManifest) -> None:
        if manifest.tool_id in self._manifests:
            raise ValueError(f"Tool manifest already registered: {manifest.tool_id}")
        self._manifests[manifest.tool_id] = manifest

    def get(self, tool_id: str) -> ToolManifest | None:
        return self._manifests.get(str(tool_id))

    def evaluate(
        self,
        manifest: ToolManifest,
        *,
        capabilities: Mapping[str, object],
        role: str,
        enabled_tool_ids: Collection[str] | None = None,
    ) -> ToolEligibility:
        enabled = None if enabled_tool_ids is None else {str(item) for item in enabled_tool_ids}
        if enabled is not None and "*" not in enabled and manifest.tool_id not in enabled:
            return ToolEligibility(False, "tool_disabled", f"Tool '{manifest.tool_id}' is disabled.")
        if str(role).strip() not in manifest.allowed_roles:
            return ToolEligibility(False, "role_forbidden", f"Role '{role}' cannot use '{manifest.tool_id}'.")
        missing = tuple(
            capability
            for capability in manifest.required_capabilities
            if not _supports_capability(capabilities, capability)
        )
        if missing:
            return ToolEligibility(
                False,
                "capability_missing",
                f"Tool '{manifest.tool_id}' requires capabilities: {', '.join(missing)}.",
            )
        return ToolEligibility(True)

    def eligible_manifests(
        self,
        *,
        capabilities: Mapping[str, object],
        role: str,
        enabled_tool_ids: Collection[str] | None = None,
    ) -> tuple[ToolManifest, ...]:
        return tuple(
            manifest for manifest in self.manifests
            if self.evaluate(
                manifest,
                capabilities=capabilities,
                role=role,
                enabled_tool_ids=enabled_tool_ids,
            ).eligible
        )


def _supports_capability(capabilities: Mapping[str, object], capability: str) -> bool:
    name = str(capability).strip()
    if name == "state_read":
        return bool(capabilities.get("supports_state_read"))
    if name == "real_writes":
        return bool(capabilities.get("supports_real_writes"))
    primitives = capabilities.get("motion_primitives", ())
    return isinstance(primitives, (list, tuple, set, frozenset)) and name in primitives
