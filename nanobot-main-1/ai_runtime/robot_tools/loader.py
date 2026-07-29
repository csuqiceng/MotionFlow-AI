"""Compatibility adapters from the existing Nanobot tool API to tool contracts."""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from contextvars import ContextVar
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import dataclass
from threading import Event
from typing import Any

from agent_contracts.tool_invocation import current_tool_call_id
from ai_runtime.tool_contracts import (
    GovernedSideEffectTool, ToolContext, ToolInvocation, ToolResult,
)
from ai_runtime.identity import (
    bind_verified_principal,
    current_verified_principal,
)
from ai_runtime.tool_manifest import ToolManifest
from ai_runtime.tool_runtime import ProductToolRuntime
from robot_platform.operation_control import OperationControl, bind_operation_control
from robot_platform.runtime import current_robot_actor, current_robot_request_session_key


@dataclass(frozen=True)
class SupervisedToolCall:
    future: asyncio.Future[ToolResult]
    cancel_event: Event

    def cancel(self) -> None:
        self.cancel_event.set()


class LegacyRobotToolAdapter(GovernedSideEffectTool):
    """Expose a legacy ``execute(**kwargs)`` tool through the stable contract."""

    def __init__(self, legacy_tool: Any, *, manifest: ToolManifest | None = None) -> None:
        if manifest is not None and manifest.tool_id != str(legacy_tool.name):
            raise ValueError(
                f"Tool manifest '{manifest.tool_id}' does not match legacy tool '{legacy_tool.name}'"
            )
        self._legacy_tool = legacy_tool
        self.manifest = manifest

    @property
    def name(self) -> str:
        return str(self._legacy_tool.name)

    @property
    def parameters(self) -> dict[str, Any]:
        return deepcopy(dict(self._legacy_tool.parameters))

    @property
    def has_explicit_effect_contract(self) -> bool:
        return callable(getattr(
            self._legacy_tool, "canonical_effect_parameters", None,
        ))

    def canonical_effect_parameters(
        self, parameters: dict[str, Any], context: ToolContext | None = None,
    ) -> dict[str, Any]:
        canonicalizer = getattr(
            self._legacy_tool, "canonical_effect_parameters", None,
        )
        if callable(canonicalizer):
            with ExitStack() as stack:
                if context is not None and context.principal is not None:
                    stack.enter_context(bind_verified_principal(context.principal))
                return deepcopy(dict(canonicalizer(deepcopy(parameters))))
        properties = self.parameters.get("properties", {})
        if not isinstance(properties, dict):
            return deepcopy(parameters)
        return {
            key: deepcopy(parameters[key]) for key in properties if key in parameters
        }

    async def execute(self, context: ToolContext, invocation: ToolInvocation) -> ToolResult:
        call = self.start_supervised(context, invocation)
        return await asyncio.shield(call.future)

    def start_supervised(
        self, context: ToolContext, invocation: ToolInvocation,
    ) -> SupervisedToolCall:
        if invocation.name != self.name:
            loop = asyncio.get_running_loop()
            future: asyncio.Future[ToolResult] = loop.create_future()
            future.set_result(ToolResult.failure(
                state="tool_name_mismatch",
                message=f"Invocation for '{invocation.name}' cannot execute '{self.name}'.",
                errors=[{"code": "tool_name_mismatch"}],
            ))
            return SupervisedToolCall(future, Event())
        # Legacy robot tools call synchronous Application/Backend ports.  Run
        # the entire legacy invocation in a supervised worker so such calls do
        # not block the agent event loop and defeat the runtime deadline.
        cancel_event = Event()
        timeout = self.manifest.timeout_seconds if self.manifest is not None else 30.0
        control = OperationControl(
            deadline_monotonic=time.monotonic() + timeout,
            cancel_event=cancel_event,
            effect_operation_id=str(context.metadata.get("effect_operation_id", "")),
            operation_fingerprint=str(context.metadata.get("operation_fingerprint", "")),
            target_device_id=str(context.metadata.get("target_device_id", "")),
        )

        def invoke() -> ToolResult:
            with ExitStack() as stack:
                stack.enter_context(bind_operation_control(control))
                if context.principal is not None:
                    stack.enter_context(bind_verified_principal(context.principal))
                result = self._legacy_tool.execute(**dict(invocation.parameters))
                if inspect.isawaitable(result):
                    result = asyncio.run(result)
                # Do not replace a definitive backend terminal result with a
                # local cancellation raised after dispatch returned.  The
                # caller has already reported the deadline as unknown; the
                # supervised future must retain this result so the durable
                # reconciliation receipt can later prove what happened.
                return _structured_result(result)

        future = asyncio.get_running_loop().run_in_executor(None, invoke)
        return SupervisedToolCall(future, cancel_event)


def adapt_legacy_robot_tool(
    legacy_tool: Any,
    *,
    manifest: ToolManifest | None = None,
) -> LegacyRobotToolAdapter:
    """Wrap one existing robot tool without changing its schema or result wire format."""
    return LegacyRobotToolAdapter(legacy_tool, manifest=manifest)


class NanobotToolRuntimeAdapter:
    """Expose governed product Tool execution to the retained Nanobot registry."""

    def __init__(
        self,
        runtime: ProductToolRuntime,
        legacy_tool: Any,
        manifest: ToolManifest,
    ) -> None:
        self._runtime = runtime
        self._legacy_tool = legacy_tool
        self.manifest = manifest
        self._request_context: ContextVar[Any | None] = ContextVar(
            f"{manifest.tool_id}_runtime_context", default=None,
        )

    @property
    def name(self) -> str:
        return self.manifest.tool_id

    @property
    def description(self) -> str:
        return str(self._legacy_tool.description)

    @property
    def parameters(self) -> dict[str, Any]:
        return deepcopy(dict(self._legacy_tool.parameters))

    def canonical_effect_parameters(
        self, parameters: dict[str, Any], context: ToolContext | None = None,
    ) -> dict[str, Any]:
        canonicalizer = getattr(
            self._legacy_tool, "canonical_effect_parameters", None,
        )
        if callable(canonicalizer):
            with ExitStack() as stack:
                if context is not None and context.principal is not None:
                    stack.enter_context(bind_verified_principal(context.principal))
                return deepcopy(dict(canonicalizer(deepcopy(parameters))))
        properties = self.parameters.get("properties", {})
        if not isinstance(properties, dict):
            return deepcopy(parameters)
        return {
            key: deepcopy(parameters[key])
            for key in properties
            if key in parameters
        }

    @property
    def read_only(self) -> bool:
        return self.manifest.risk_level == "read"

    @property
    def exclusive(self) -> bool:
        return self.manifest.concurrency != "parallel" or bool(self.manifest.resources)

    @property
    def concurrency_safe(self) -> bool:
        return self.read_only and not self.exclusive

    def set_context(self, context: Any) -> None:
        self._request_context.set(context)
        setter = getattr(self._legacy_tool, "set_context", None)
        if callable(setter):
            setter(context)

    def cast_params(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._legacy_tool.cast_params(params)

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        return self._legacy_tool.validate_params(params)

    def to_schema(self) -> dict[str, Any]:
        return self._legacy_tool.to_schema()

    async def execute(self, **kwargs: Any) -> str:
        request_context = self._request_context.get()
        metadata = getattr(request_context, "metadata", {})
        context = ToolContext(
            actor="",
            session_key=current_robot_request_session_key() or str(
                getattr(request_context, "session_key", "") or ""
            ),
            principal=current_verified_principal(),
            metadata=dict(metadata) if isinstance(metadata, dict) else {},
            on_progress=getattr(request_context, "on_progress", None),
        )
        tool_call_id = current_tool_call_id() or str(
            context.metadata.get("tool_call_id", "")
        )
        invocation = ToolInvocation(
            name=self.name,
            parameters=deepcopy(kwargs),
            invocation_id=tool_call_id,
            idempotency_key=str(context.metadata.get("idempotency_key", "")) or tool_call_id,
        )
        result = await self._runtime.execute(context, invocation)
        return json.dumps(result.to_contract_dict(), ensure_ascii=False)


def _structured_result(result: Any) -> ToolResult:
    if isinstance(result, dict):
        payload = result
    else:
        try:
            payload = json.loads(str(result))
        except (TypeError, ValueError, json.JSONDecodeError):
            return ToolResult.failure(
                state="tool_result_invalid",
                message="Legacy tool returned a non-JSON result.",
                errors=[{"code": "tool_result_invalid"}],
            )
    if not isinstance(payload, dict):
        return ToolResult.failure(
            state="tool_result_invalid",
            message="Legacy tool returned a non-object JSON result.",
            errors=[{"code": "tool_result_invalid"}],
        )
    raw_errors = payload.get("errors") or []
    errors = [dict(error) for error in raw_errors if isinstance(error, dict)]
    raw_data = payload.get("data") or {}
    data = dict(raw_data) if isinstance(raw_data, dict) else {}
    return ToolResult(
        ok=bool(payload.get("ok")),
        state=str(payload.get("state") or "tool_result_missing_state"),
        message=str(payload.get("message") or ""),
        data=data,
        errors=errors,
    )
