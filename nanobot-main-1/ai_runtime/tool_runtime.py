"""Governed execution runtime for SDK-neutral product Tools."""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
from copy import deepcopy
from dataclasses import dataclass
from time import time
from typing import Any, Callable, Protocol

from ai_runtime.tool_contracts import (
    GovernedSideEffectTool, Tool, ToolContext, ToolInvocation, ToolResult,
)
from ai_runtime.tool_manifest import ToolManifest
from ai_runtime.tool_registry import ToolRegistry
from ai_runtime.tool_operation_store import (
    ToolOperationStorePort, UnavailableToolOperationStore,
)


@dataclass(frozen=True)
class ToolAuditEvent:
    audit_id: str
    event: str
    tool_id: str
    invocation_id: str
    actor: str
    session_key: str
    parameter_hash: str
    timestamp: float
    state: str = ""
    target_device_id: str = ""
    device_state_hash: str = ""


class ToolAuditPort(Protocol):
    def append(self, event: ToolAuditEvent) -> None: ...


class NullToolAudit:
    def append(self, event: ToolAuditEvent) -> None:
        del event


class UnavailableToolAudit:
    def append(self, event: ToolAuditEvent) -> None:
        del event
        raise OSError("Tool audit adapter is not configured")


@dataclass
class _RegisteredTool:
    tool: Tool
    manifest: ToolManifest


@dataclass
class _IdempotencyRecord:
    fingerprint: str
    result: ToolResult | None = None


class _DispatchNotStarted(Exception):
    """Internal control flow after a fail-closed durable claim failure."""


class ProductToolRuntime:
    """Apply eligibility, timeout, locking, idempotency and audit at invocation."""

    def __init__(
        self,
        *,
        capabilities: dict[str, object] | None = None,
        enabled_tool_ids: tuple[str, ...] | list[str] | None = None,
        audit: ToolAuditPort | None = None,
        target_device_id: str = "",
        state_reader: Callable[[], Any] | None = None,
        operation_store: ToolOperationStorePort | None = None,
    ) -> None:
        self._capabilities = deepcopy(capabilities or {})
        self._enabled_tool_ids = None if enabled_tool_ids is None else tuple(enabled_tool_ids)
        self._audit = audit or UnavailableToolAudit()
        self._target_device_id = str(target_device_id or "unconfigured-device")
        self._state_reader = state_reader
        self._operation_store = operation_store or UnavailableToolOperationStore()
        self._registry = ToolRegistry()
        self._tools: dict[str, _RegisteredTool] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._idempotency: dict[tuple[str, str], _IdempotencyRecord] = {}
        self._idempotency_locks: dict[tuple[str, str], asyncio.Lock] = {}
        # Durable embargoes are read from the operation store on every call so
        # an audited reconciliation becomes effective without a process
        # restart. This set contains only outcomes not yet persisted.
        self._unresolved_fingerprints: set[str] = set()
        self._reaper_tasks: set[asyncio.Task[None]] = set()

    @property
    def manifests(self) -> tuple[ToolManifest, ...]:
        return self._registry.manifests

    def register(self, tool: Tool, manifest: ToolManifest) -> None:
        if tool.name != manifest.tool_id:
            raise ValueError("Tool name must match its manifest tool_id")
        if manifest.risk_level != "read" and manifest.idempotency != "request":
            raise ValueError("Side-effecting tools require request idempotency")
        if manifest.risk_level != "read" and (
            not isinstance(tool, GovernedSideEffectTool)
            or not bool(getattr(tool, "has_explicit_effect_contract", False))
        ):
            raise ValueError(
                "Side-effecting tools require a reviewed Application-only adapter "
                "with an explicit canonical-effect contract"
            )
        if (
            manifest.risk_level != "read"
            and "real_writes" in manifest.required_capabilities
        ):
            raise ValueError(
                "AI Tools cannot directly own controller writes; use the staged "
                "plan/confirm/permit Application workflow"
            )
        self._registry.register(manifest)
        self._tools[manifest.tool_id] = _RegisteredTool(tool, manifest)

    def exposed_tool_ids(self, *, role: str) -> tuple[str, ...]:
        return tuple(
            manifest.tool_id
            for manifest in self._registry.eligible_manifests(
                capabilities=self._capabilities,
                role=role,
                enabled_tool_ids=self._enabled_tool_ids,
            )
        )

    async def execute(
        self,
        context: ToolContext,
        invocation: ToolInvocation,
    ) -> ToolResult:
        registered = self._tools.get(invocation.name)
        if registered is None:
            return _failure("tool_not_found", "Tool is unavailable.")
        manifest = registered.manifest
        role = context.principal.role if context.principal is not None else "untrusted"
        eligibility = self._registry.evaluate(
            manifest,
            capabilities=self._capabilities,
            role=role,
            enabled_tool_ids=self._enabled_tool_ids,
        )
        if not eligibility.eligible:
            return _failure(eligibility.code, eligibility.message)

        parameter_hash = _parameter_hash(invocation.parameters)
        invocation_id = str(invocation.invocation_id or invocation.idempotency_key).strip()
        if not invocation_id:
            invocation_id = hashlib.sha256(
                f"{manifest.tool_id}|{context.verified_actor}|{context.session_key}|{parameter_hash}".encode()
            ).hexdigest()[:24]
        fingerprint = _fingerprint(context, invocation, parameter_hash)
        try:
            effect_payload = _canonical_effect_parameters(
                registered.tool, invocation.parameters, context,
            )
        except Exception:
            return _failure(
                "tool_effect_canonicalization_failed",
                "The Tool effect could not be frozen safely; execution was not started.",
            )
        effect_hash = _parameter_hash(effect_payload)
        operation_fingerprint = _operation_fingerprint(
            invocation.name, effect_hash, self._target_device_id,
        )
        try:
            durable_unresolved = self._operation_store.unresolved_fingerprints()
        except Exception:
            if manifest.risk_level != "read":
                return _failure(
                    "tool_operation_store_unavailable",
                    "Side-effecting Tool operation state cannot be verified.",
                )
            durable_unresolved = frozenset()
        if (
            "*" in durable_unresolved
            or operation_fingerprint in durable_unresolved
            or operation_fingerprint in self._unresolved_fingerprints
        ):
            return _failure(
                "tool_outcome_unknown",
                "A matching side-effecting operation has an unresolved outcome; reconcile it before retrying.",
            )

        if manifest.idempotency == "request":
            key = str(invocation.idempotency_key).strip()
            if not key:
                return _failure(
                    "idempotency_key_required",
                    "This Tool requires an idempotency key.",
                )
            record_key = (manifest.tool_id, key)
            lock = self._idempotency_locks.setdefault(record_key, asyncio.Lock())
            async with lock:
                durable_required = manifest.risk_level != "read"
                if durable_required and not self._operation_store.durable:
                    return _failure(
                        "tool_operation_store_unavailable",
                        "Side-effecting Tool execution requires durable operation state.",
                    )
                try:
                    persisted = (
                        self._operation_store.get(manifest.tool_id, key)
                        if durable_required else None
                    )
                except Exception:
                    return _failure(
                        "tool_operation_store_unavailable",
                        "Side-effecting Tool operation state cannot be verified.",
                    )
                if persisted is not None and persisted.fingerprint != fingerprint:
                    return _failure(
                        "idempotency_scope_mismatch",
                        "The idempotency key is already bound to another invocation.",
                    )
                if persisted is not None and persisted.state in {"started", "unknown"}:
                    return _failure(
                        "tool_outcome_unknown",
                        "The operation has an unresolved persisted outcome; reconcile before retrying.",
                    )
                if persisted is not None and persisted.state == "completed":
                    return _tool_result_from_dict(persisted.result)
                record = self._idempotency.get(record_key)
                if record is not None and record.fingerprint != fingerprint:
                    return _failure(
                        "idempotency_scope_mismatch",
                        "The idempotency key is already bound to another invocation.",
                    )
                if record is not None and record.result is not None:
                    return deepcopy(record.result)
                effect_operation_id = secrets.token_urlsafe(18)
                try:
                    began = not durable_required or self._operation_store.begin(
                        manifest.tool_id, key, fingerprint,
                        operation_fingerprint=operation_fingerprint,
                        target_device_id=self._target_device_id,
                        effect_payload=effect_payload,
                        readback_predicate=_readback_predicate(
                            ToolInvocation(invocation.name, effect_payload),
                        ),
                        effect_operation_id=effect_operation_id,
                    )
                except Exception:
                    return _failure(
                        "tool_operation_store_unavailable",
                        "Side-effecting Tool operation state cannot be persisted.",
                    )
                if not began:
                    try:
                        persisted = self._operation_store.get(manifest.tool_id, key)
                    except Exception:
                        persisted = None
                    if persisted is not None and persisted.state == "completed":
                        return _tool_result_from_dict(persisted.result)
                    return _failure(
                        "tool_outcome_unknown",
                        "The operation state changed concurrently; reconcile before retrying.",
                    )
                self._idempotency[record_key] = _IdempotencyRecord(fingerprint)
                frozen_invocation = ToolInvocation(
                    name=invocation.name, parameters=deepcopy(effect_payload),
                    invocation_id=invocation.invocation_id,
                    idempotency_key=invocation.idempotency_key,
                )
                frozen_context = ToolContext(
                    actor=context.actor, session_key=context.session_key,
                    principal=context.principal,
                    metadata={
                        **deepcopy(context.metadata),
                        "effect_operation_id": effect_operation_id,
                        "operation_fingerprint": operation_fingerprint,
                        "target_device_id": self._target_device_id,
                    },
                    on_progress=context.on_progress,
                )
                try:
                    result = await self._execute_once(
                        registered, frozen_context, frozen_invocation,
                        invocation_id, parameter_hash,
                        operation_fingerprint,
                        claim_dispatch=(lambda: self._operation_store.claim_effect_dispatch(
                            manifest.tool_id, key, fingerprint,
                            effect_operation_id=effect_operation_id,
                        )) if durable_required else None,
                        record_terminal=(lambda terminal_result: (
                            self._operation_store.record_effect_terminal(
                                manifest.tool_id, key, fingerprint,
                                effect_operation_id=effect_operation_id,
                                result=terminal_result.to_contract_dict(),
                            )
                        )) if durable_required else None,
                    )
                except asyncio.CancelledError:
                    if durable_required:
                        self._record_unknown(
                            manifest.tool_id, key, fingerprint,
                            operation_fingerprint, "cancelled",
                        )
                    raise
                if durable_required:
                    if "unknown" in result.state:
                        self._record_unknown(
                            manifest.tool_id, key, fingerprint,
                            operation_fingerprint, result.state,
                        )
                    else:
                        try:
                            completed = self._operation_store.complete(
                                manifest.tool_id, key, fingerprint,
                                result.to_contract_dict(),
                            )
                        except Exception:
                            completed = False
                    if "unknown" not in result.state and not completed:
                        self._record_unknown(
                            manifest.tool_id, key, fingerprint,
                            operation_fingerprint,
                            "tool_operation_result_persistence_failed",
                        )
                        result = _failure(
                            "tool_outcome_unknown",
                            "Tool result could not be persisted; reconcile before retrying.",
                        )
                self._idempotency[record_key].result = deepcopy(result)
                return result

        return await self._execute_once(
            registered, context, invocation, invocation_id, parameter_hash,
            operation_fingerprint,
        )

    async def _execute_once(
        self,
        registered: _RegisteredTool,
        context: ToolContext,
        invocation: ToolInvocation,
        invocation_id: str,
        parameter_hash: str,
        operation_fingerprint: str,
        claim_dispatch: Callable[[], bool] | None = None,
        record_terminal: Callable[[ToolResult], bool] | None = None,
    ) -> ToolResult:
        manifest = registered.manifest
        started = ToolAuditEvent(
            audit_id=secrets.token_urlsafe(16),
            event="tool_started",
            tool_id=manifest.tool_id,
            invocation_id=invocation_id,
            actor=context.verified_actor,
            session_key=context.session_key,
            parameter_hash=parameter_hash,
            timestamp=time(),
            target_device_id=self._target_device_id,
            device_state_hash=self._device_state_hash(),
        )
        if not self._append_audit(started) and manifest.audit_policy == "required":
            return _failure("tool_audit_unavailable", "Tool audit is unavailable.")

        lock_names = list(manifest.resources)
        if manifest.concurrency == "exclusive":
            lock_names.append("tool-runtime:exclusive")
        elif manifest.concurrency == "actor":
            lock_names.append(f"actor:{context.verified_actor}")
        terminal_event = "tool_completed"
        acquired: list[asyncio.Lock] = []
        locks_transferred = False
        supervised: Any = None
        try:
            for name in sorted(set(lock_names)):
                lock = self._locks.setdefault(name, asyncio.Lock())
                await lock.acquire()
                acquired.append(lock)
            if claim_dispatch is not None and not claim_dispatch():
                result = _failure(
                    "tool_outcome_unknown",
                    "The effect dispatch claim could not be persisted; execution was not started.",
                )
                terminal_event = "tool_dispatch_claim_failed"
                raise _DispatchNotStarted
            starter = getattr(registered.tool, "start_supervised", None)
            if callable(starter):
                supervised = starter(context, invocation)
                result = await asyncio.wait_for(
                    asyncio.shield(supervised.future),
                    timeout=manifest.timeout_seconds,
                )
            else:
                result = await asyncio.wait_for(
                    registered.tool.execute(context, invocation),
                    timeout=manifest.timeout_seconds,
                )
            if not isinstance(result, ToolResult):
                result = _failure("tool_result_invalid", "Tool returned an invalid result.")
            if record_terminal is not None and not record_terminal(result):
                result = _failure(
                    "tool_outcome_unknown",
                    "The Tool terminal receipt could not be persisted; reconcile before retrying.",
                )
        except _DispatchNotStarted:
            pass
        except TimeoutError:
            if supervised is not None:
                if not supervised.future.done():
                    supervised.cancel()
                self._transfer_locks_to_reaper(
                    supervised.future, acquired, record_terminal=record_terminal,
                )
                locks_transferred = True
            result = _failure(
                "tool_timeout" if manifest.risk_level == "read" else "tool_outcome_unknown",
                "Tool execution timed out." if manifest.risk_level == "read" else
                "Tool deadline expired; reconcile the operation outcome before retrying.",
            )
            if manifest.risk_level != "read":
                self._unresolved_fingerprints.add(operation_fingerprint)
            terminal_event = "tool_timed_out"
        except asyncio.CancelledError:
            if supervised is not None:
                if not supervised.future.done():
                    supervised.cancel()
                self._transfer_locks_to_reaper(
                    supervised.future, acquired, record_terminal=record_terminal,
                )
                locks_transferred = True
            if manifest.risk_level != "read":
                self._unresolved_fingerprints.add(operation_fingerprint)
            self._append_audit(ToolAuditEvent(
                audit_id=secrets.token_urlsafe(16),
                event="tool_cancelled",
                tool_id=manifest.tool_id,
                invocation_id=invocation_id,
                actor=context.verified_actor,
                session_key=context.session_key,
                parameter_hash=parameter_hash,
                timestamp=time(),
                state="cancelled",
                target_device_id=self._target_device_id,
                device_state_hash=self._device_state_hash(),
            ))
            raise
        except Exception:
            if manifest.risk_level == "read":
                result = _failure("tool_execution_failed", "Tool execution failed.")
            else:
                result = _failure(
                    "tool_outcome_unknown",
                    "Tool execution failed after dispatch may have started; reconcile before retrying.",
                )
                self._unresolved_fingerprints.add(operation_fingerprint)
                if record_terminal is not None:
                    try:
                        record_terminal(result)
                    except Exception:
                        pass
        finally:
            if not locks_transferred:
                for lock in reversed(acquired):
                    lock.release()

        completed = ToolAuditEvent(
            audit_id=secrets.token_urlsafe(16),
            event=terminal_event,
            tool_id=manifest.tool_id,
            invocation_id=invocation_id,
            actor=context.verified_actor,
            session_key=context.session_key,
            parameter_hash=parameter_hash,
            timestamp=time(),
            state=result.state,
            target_device_id=self._target_device_id,
            device_state_hash=self._device_state_hash(),
        )
        if not self._append_audit(completed) and manifest.audit_policy == "required":
            if manifest.risk_level != "read":
                self._unresolved_fingerprints.add(operation_fingerprint)
            return _failure(
                "tool_audit_outcome_unknown",
                "Tool completed but its terminal audit could not be persisted.",
            )
        if manifest.risk_level != "read" and "unknown" in result.state:
            self._unresolved_fingerprints.add(operation_fingerprint)
        return deepcopy(result)

    def _record_unknown(
        self, tool_id: str, request_key: str, fingerprint: str,
        operation_fingerprint: str, reason: str,
    ) -> None:
        self._unresolved_fingerprints.add(operation_fingerprint)
        try:
            persisted = self._operation_store.mark_unknown(
                tool_id, request_key, fingerprint, reason=reason,
            )
            if persisted:
                self._unresolved_fingerprints.discard(operation_fingerprint)
        except Exception:
            pass

    def _transfer_locks_to_reaper(
        self,
        future: asyncio.Future[ToolResult],
        locks: list[asyncio.Lock],
        *, record_terminal: Callable[[ToolResult], bool] | None = None,
    ) -> None:
        held = tuple(locks)

        async def reap() -> None:
            try:
                terminal_result = await asyncio.shield(future)
                if record_terminal is not None and isinstance(terminal_result, ToolResult):
                    record_terminal(terminal_result)
            except BaseException:
                pass
            finally:
                for lock in reversed(held):
                    lock.release()

        task = asyncio.create_task(reap())
        self._reaper_tasks.add(task)
        task.add_done_callback(self._reaper_tasks.discard)

    def _append_audit(self, event: ToolAuditEvent) -> bool:
        try:
            self._audit.append(event)
            return True
        except Exception:
            return False

    def _device_state_hash(self) -> str:
        if self._state_reader is None:
            return "unavailable"
        try:
            state = self._state_reader()
            encoded = json.dumps(
                state, sort_keys=True, separators=(",", ":"), default=str,
            )
        except Exception:
            return "unavailable"
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _parameter_hash(parameters: dict[str, Any]) -> str:
    try:
        encoded = json.dumps(
            parameters,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=lambda value: f"<{type(value).__name__}>",
        )
    except Exception:
        encoded = "<unserializable>"
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _fingerprint(
    context: ToolContext,
    invocation: ToolInvocation,
    parameter_hash: str,
) -> str:
    source = "|".join((
        invocation.name,
        context.verified_actor,
        context.session_key,
        parameter_hash,
    ))
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _operation_fingerprint(
    tool_name: str, effect_hash: str, target_device_id: str,
) -> str:
    """Identify a physical effect independently of caller/session identity."""
    source = "|".join((str(tool_name), str(target_device_id), effect_hash))
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _canonical_effect_parameters(
    tool: Tool, parameters: dict[str, Any], context: ToolContext,
) -> dict[str, Any]:
    canonicalizer = getattr(tool, "canonical_effect_parameters", None)
    if callable(canonicalizer):
        value = canonicalizer(deepcopy(parameters), context)
        if not isinstance(value, dict):
            raise TypeError("Canonical effect parameters must be an object")
        return deepcopy(value)
    return deepcopy(parameters)


def _readback_predicate(invocation: ToolInvocation) -> dict[str, Any]:
    """Describe controller evidence that can prove this exact effect completed."""
    parameters = dict(invocation.parameters)
    action = str(parameters.get("action", "")).strip()
    if action == "linear_move" and isinstance(parameters.get("target_pose"), dict):
        return {
            "kind": "axes_equal",
            "expected": {
                axis: float(parameters["target_pose"][axis])
                for axis in ("x", "y", "z", "rx", "ry", "rz")
                if axis in parameters["target_pose"]
            },
            "tolerance": 0.001,
        }
    if action == "io" and isinstance(parameters.get("io_number"), int):
        return {
            "kind": "io_output_equal", "io_number": parameters["io_number"],
            "expected": parameters.get("enabled"),
        }
    expected_modes = {
        "pause": ("paused",), "resume": ("idle", "running"),
        "stop_current": ("idle", "stopped"),
        "release_emergency_stop": ("idle",),
        "release_cancel": ("idle",),
    }
    if action in expected_modes:
        predicate: dict[str, Any] = {
            "kind": "robot_mode_in", "expected": list(expected_modes[action]),
        }
        if action == "release_cancel":
            predicate["cancel_latch"] = False
        return predicate
    return {"kind": "unsupported"}


def _failure(code: str, message: str) -> ToolResult:
    return ToolResult.failure(
        state=code,
        message=message,
        errors=[{"code": code}],
    )


def _tool_result_from_dict(value: dict[str, Any] | None) -> ToolResult:
    if not isinstance(value, dict):
        return _failure("tool_outcome_unknown", "Persisted Tool result is invalid.")
    try:
        return ToolResult(
            ok=bool(value["ok"]), state=str(value["state"]),
            message=str(value.get("message", "")),
            data=dict(value.get("data") or {}),
            errors=[dict(item) for item in value.get("errors") or []],
        )
    except Exception:
        return _failure("tool_outcome_unknown", "Persisted Tool result is invalid.")
