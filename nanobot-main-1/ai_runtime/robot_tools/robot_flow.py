"""AI-facing adapter for published Flow query and trusted automatic execution."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from contextvars import ContextVar
from typing import Any

from ai_runtime.robot_tools.base import Tool, tool_parameters
from ai_runtime.robot_tools.context import ContextAware, RequestContext
from ai_runtime.robot_tools.principal import current_application_principal
from robot_platform.application import (
    RobotAutomaticFlowApplicationPort,
    RobotAutomaticFlowCommand,
    RobotFlowApplicationPort,
    RobotFlowQuery,
)
from robot_platform.models import ToolResult
from robot_platform.runtime import get_robot_execution_mode

_PARAMETERS = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["list", "get", "run"]},
        "name": {"type": "string"},
        "flow_alias": {"type": "string"},
    },
    "required": ["action"],
    "additionalProperties": True,
}


@tool_parameters(_PARAMETERS)
class RobotFlowTool(Tool, ContextAware):
    def __init__(
        self,
        registry_path: str | None = None,
        *,
        alias_path: str | None = None,
        platform: Any = None,
        dry_run_application: Any = None,
        flow_application: RobotFlowApplicationPort | None = None,
        automatic_flow_application: RobotAutomaticFlowApplicationPort | None = None,
    ) -> None:
        # Retained arguments keep source compatibility while concrete stores and
        # Platform construction remain exclusively owned by the composition root.
        self._registry_path = registry_path
        self._alias_path = alias_path
        self._platform = platform
        self._dry_run_application = dry_run_application
        self._flow_application = flow_application
        self._automatic_flow_application = automatic_flow_application
        self._request_ctx: ContextVar[RequestContext | None] = ContextVar(
            "robot_flow_request_ctx", default=None,
        )

    def set_context(self, ctx: RequestContext) -> None:
        self._request_ctx.set(ctx)

    def canonical_effect_parameters(self, parameters: dict[str, Any]) -> dict[str, Any]:
        action = str(parameters.get("action") or "").strip()
        if action == "list":
            return {"action": action}
        if action not in {"get", "run"} or self._flow_application is None:
            return {"action": action}
        response = self._flow_application.query(RobotFlowQuery(
            principal=current_application_principal(), action="get",
            name=str(parameters.get("name") or ""),
            alias=str(parameters.get("flow_alias") or ""),
        ))
        if not response.ok or not isinstance(response.payload, dict):
            error = response.error
            return {"action": action, "_flow_resolution_error": {
                "ok": False,
                "state": getattr(error, "code", "flow_unavailable"),
                "message": getattr(error, "message", "Flow service is unavailable."),
                "data": {},
                "errors": [{"code": getattr(error, "code", "flow_unavailable")}],
            }}
        flow = response.payload.get("flow")
        if not isinstance(flow, dict):
            return {"action": action, "_flow_resolution_error": {
                "ok": False, "state": "flow_state_unavailable",
                "message": "Flow service returned an invalid snapshot.",
                "data": {}, "errors": [{"code": "flow_state_unavailable"}],
            }}
        return {
            "action": action,
            "name": str(flow.get("name") or ""),
            "_flow_snapshot_hash": hashlib.sha256(json.dumps(
                flow, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")).hexdigest(),
        }

    @property
    def name(self) -> str:
        return "robot_flow"

    @property
    def description(self) -> str:
        return (
            "List, inspect, and run named persisted robot flows. In automatic "
            "mode the trusted server stages safety, issues one-use permits, and "
            "executes only after checks pass."
        )

    @property
    def read_only(self) -> bool:
        return False

    @property
    def exclusive(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        action = str(kwargs.get("action") or "").strip()
        frozen_error = kwargs.get("_flow_resolution_error")
        if isinstance(frozen_error, dict):
            return json.dumps(frozen_error, ensure_ascii=False)
        if action not in {"list", "get", "run"}:
            return _render_failure("unknown_flow_action", "Unknown flow action.")
        if action == "run" and get_robot_execution_mode() == "auto_after_safety_check":
            automatic = self._automatic_flow_application
            if automatic is None:
                return _render_failure(
                    "staged_execution_required",
                    "AI tools cannot acquire real-execution credentials without the trusted server Flow service.",
                )
            response = automatic.execute(RobotAutomaticFlowCommand(
                principal=current_application_principal(),
                flow_name=str(kwargs.get("name") or ""),
                alias=str(kwargs.get("flow_alias") or ""),
                expected_snapshot_hash=str(kwargs.get("_flow_snapshot_hash") or ""),
            ))
            if not response.ok or not isinstance(response.payload, dict):
                error = response.error
                return _render_failure(
                    getattr(error, "code", "automatic_flow_failed"),
                    getattr(error, "message", "Automatic Flow did not complete."),
                )
            return json.dumps(response.payload, ensure_ascii=False)
        application = self._flow_application
        if application is None:
            return _render_failure("flow_unavailable", "Flow service is unavailable.")
        principal = current_application_principal()
        resolved: dict[str, Any] = {}

        def on_resolved(flow: dict[str, Any]) -> None:
            resolved.update(flow)
            try:
                asyncio.get_running_loop().create_task(self._emit_progress(
                    f"开始执行流程 {flow['name']}（共 {len(flow['steps'])} 步）",
                ))
            except RuntimeError:
                pass

        def on_step(index: int, status: str, result: dict[str, Any] | None) -> None:
            del result
            if status != "running":
                return
            steps = resolved.get("steps", [])
            description = ""
            if isinstance(steps, list) and 0 < index <= len(steps):
                description = str(steps[index - 1].get("description", ""))
            text = f"流程 {resolved.get('name', '')} 第 {index}/{len(steps)} 步"
            if description:
                text += f"：{description}"
            try:
                asyncio.get_running_loop().create_task(self._emit_progress(text))
            except RuntimeError:
                pass

        response = application.query(
            RobotFlowQuery(
                principal=principal,
                action="preview" if action == "run" else action,
                name=str(kwargs.get("name") or ""),
                alias=str(kwargs.get("flow_alias") or ""),
                expected_snapshot_hash=str(
                    kwargs.get("_flow_snapshot_hash") or ""
                ),
            ),
            on_resolved=on_resolved if action == "run" else None,
            on_step=on_step if action == "run" else None,
        )
        if not response.ok or not isinstance(response.payload, dict):
            error = response.error
            return _render_failure(
                getattr(error, "code", "flow_unavailable"),
                getattr(error, "message", "Flow service is unavailable."),
            )
        if action == "list":
            payload = response.payload
            return json.dumps(ToolResult.success(
                state="flow_list",
                message=f"{payload['count']} flow(s) registered.",
                data=payload,
            ).to_dict(), ensure_ascii=False)
        if action == "get":
            return json.dumps(ToolResult.success(
                state="flow_found",
                message=f"Flow '{response.payload['flow']['name']}' found.",
                data=response.payload,
            ).to_dict(), ensure_ascii=False)
        return json.dumps(response.payload["result"], ensure_ascii=False)

    async def _emit_progress(self, text: str) -> None:
        context = self._request_ctx.get()
        if context is None or context.on_progress is None:
            return
        try:
            result = context.on_progress(text, tool_hint=True)
            if inspect.isawaitable(result):
                await result
        except Exception:
            pass


def _render_failure(code: str, message: str) -> str:
    return json.dumps(ToolResult.failure(
        state=code,
        message=message,
        errors=[{"code": code}],
    ).to_dict(), ensure_ascii=False)
