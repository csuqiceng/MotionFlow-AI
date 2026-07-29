from __future__ import annotations

import asyncio
import pathlib
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from ai_runtime.tool_contracts import (
    GovernedSideEffectTool, ToolContext, ToolInvocation, ToolResult,
)
from ai_runtime.identity import issue_verified_principal
from ai_runtime.tool_manifest import ToolManifest
from ai_runtime.tool_runtime import ProductToolRuntime, ToolAuditEvent
from ai_runtime.robot_tools.loader import LegacyRobotToolAdapter
from ai_runtime.robot_tools.robot_arm import RobotArmTool
from ai_runtime.tool_operation_store import InMemoryToolOperationStore
from robot_server.tool_operation_store import JsonToolOperationStore


@dataclass
class _Audit:
    events: list[ToolAuditEvent] = field(default_factory=list)
    fail_at: int = 0

    def append(self, event: ToolAuditEvent) -> None:
        if self.fail_at and len(self.events) + 1 == self.fail_at:
            raise OSError("audit unavailable")
        self.events.append(event)


class _Tool(GovernedSideEffectTool):
    name = "demo"
    parameters: dict[str, Any] = {"type": "object"}

    def __init__(self) -> None:
        self.calls = 0
        self.release: asyncio.Event | None = None
        self.entered: asyncio.Event | None = None

    @property
    def has_explicit_effect_contract(self) -> bool:
        return True

    def canonical_effect_parameters(self, parameters, _context=None):
        return dict(parameters)

    async def execute(
        self, context: ToolContext, invocation: ToolInvocation,
    ) -> ToolResult:
        del context
        self.calls += 1
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            await self.release.wait()
        return ToolResult.success(
            state="done", data={"value": invocation.parameters.get("value")},
        )


def _context(
    actor: str = "operator:user-1", session_key: str = "session-1",
) -> ToolContext:
    role, _, actor_id = actor.partition(":")
    principal = issue_verified_principal(
        actor_id=actor_id or actor,
        role=role if role in {"operator", "engineer"} else "operator",
        session_id=session_key,
        auth_source="test",
    )
    return ToolContext(principal=principal, session_key=session_key)


def _runtime(
    tool: _Tool,
    manifest: ToolManifest,
    *,
    enabled: list[str] | None = None,
    audit: _Audit | None = None,
) -> ProductToolRuntime:
    operation_store = InMemoryToolOperationStore(durable=True)
    runtime = ProductToolRuntime(
        capabilities={
            "supports_state_read": True,
            "supports_real_writes": False,
            "motion_primitives": ["axis_move"],
        },
        enabled_tool_ids=["demo"] if enabled is None else enabled,
        audit=audit,
        operation_store=operation_store,
    )
    runtime.register(tool, manifest)
    return runtime


@pytest.mark.asyncio
async def test_runtime_rechecks_enablement_role_and_capability_at_execution() -> None:
    tool = _Tool()
    manifest = ToolManifest(
        "demo", "2", allowed_roles=("engineer",),
        required_capabilities=("real_writes",),
    )
    runtime = _runtime(tool, manifest)

    role = await runtime.execute(_context(), ToolInvocation("demo"))
    capability = await runtime.execute(
        _context("engineer:user-1"), ToolInvocation("demo"),
    )
    disabled = _runtime(_Tool(), ToolManifest("demo", "2"), enabled=[])
    disabled_result = await disabled.execute(_context(), ToolInvocation("demo"))

    assert role.state == "role_forbidden"
    assert capability.state == "capability_missing"
    assert disabled_result.state == "tool_disabled"
    assert tool.calls == 0


@pytest.mark.asyncio
async def test_runtime_enforces_timeout_and_records_sanitized_audit() -> None:
    tool = _Tool()
    tool.release = asyncio.Event()
    audit = _Audit()
    runtime = _runtime(
        tool,
        ToolManifest("demo", "2", timeout_seconds=0.01),
        audit=audit,
    )

    result = await runtime.execute(
        _context(), ToolInvocation("demo", {"token": "secret"}),
    )

    assert result.state == "tool_timeout"
    assert [event.event for event in audit.events] == [
        "tool_started", "tool_timed_out",
    ]
    assert all("secret" not in repr(event) for event in audit.events)


@pytest.mark.asyncio
async def test_runtime_cancellation_propagates_and_is_audited() -> None:
    tool = _Tool()
    tool.release = asyncio.Event()
    tool.entered = asyncio.Event()
    audit = _Audit()
    runtime = _runtime(tool, ToolManifest("demo", "2"), audit=audit)
    task = asyncio.create_task(runtime.execute(_context(), ToolInvocation("demo")))
    await tool.entered.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert [event.event for event in audit.events] == [
        "tool_started", "tool_cancelled",
    ]


@pytest.mark.asyncio
async def test_request_idempotency_replays_and_rejects_scope_rebinding() -> None:
    tool = _Tool()
    runtime = _runtime(
        tool,
        ToolManifest("demo", "2", idempotency="request"),
    )
    first = ToolInvocation("demo", {"value": 1}, idempotency_key="request-1")

    result = await runtime.execute(_context(), first)
    replay = await runtime.execute(_context(), first)
    mismatch = await runtime.execute(
        _context(),
        ToolInvocation("demo", {"value": 2}, idempotency_key="request-1"),
    )

    assert result == replay
    assert mismatch.state == "idempotency_scope_mismatch"
    assert tool.calls == 1


@pytest.mark.asyncio
async def test_shared_resource_serializes_distinct_tools() -> None:
    active = 0
    maximum = 0

    class ResourceTool(_Tool):
        def __init__(self, name: str) -> None:
            super().__init__()
            self.name = name

        async def execute(self, context, invocation):
            nonlocal active, maximum
            del context, invocation
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0.01)
            active -= 1
            return ToolResult.success(state="done")

    runtime = ProductToolRuntime(enabled_tool_ids=["first", "second"])
    for name in ("first", "second"):
        runtime.register(
            ResourceTool(name),
            ToolManifest(name, "2", resources=("controller",)),
        )

    await asyncio.gather(*(
        runtime.execute(_context(), ToolInvocation(name))
        for name in ("first", "second")
    ))
    assert maximum == 1


@pytest.mark.asyncio
async def test_required_write_ahead_audit_failure_prevents_execution() -> None:
    tool = _Tool()
    runtime = _runtime(
        tool,
        ToolManifest("demo", "2", audit_policy="required"),
        audit=_Audit(fail_at=1),
    )

    result = await runtime.execute(_context(), ToolInvocation("demo"))

    assert result.state == "tool_audit_unavailable"
    assert tool.calls == 0


@pytest.mark.asyncio
async def test_actor_string_cannot_forge_a_verified_engineer() -> None:
    tool = _Tool()
    runtime = _runtime(
        tool,
        ToolManifest("demo", "2", allowed_roles=("engineer",)),
    )
    result = await runtime.execute(
        ToolContext(actor="engineer:forged", session_key="session-1"),
        ToolInvocation("demo"),
    )
    assert result.state == "role_forbidden"
    assert tool.calls == 0


@pytest.mark.asyncio
async def test_required_terminal_audit_failure_is_outcome_unknown() -> None:
    tool = _Tool()
    runtime = _runtime(
        tool,
        ToolManifest(
            "demo", "2", audit_policy="required", risk_level="system",
            idempotency="request",
        ),
        audit=_Audit(fail_at=2),
    )
    result = await runtime.execute(
        _context(), ToolInvocation("demo", idempotency_key="request-1"),
    )
    assert result.state == "tool_audit_outcome_unknown"
    assert tool.calls == 1


@pytest.mark.asyncio
async def test_terminal_receipt_precedes_required_terminal_audit_failure() -> None:
    tool = _Tool()
    store = InMemoryToolOperationStore(durable=True)
    runtime = ProductToolRuntime(
        enabled_tool_ids=["demo"], audit=_Audit(fail_at=2),
        operation_store=store, target_device_id="controller-1",
    )
    runtime.register(tool, ToolManifest(
        "demo", "2", audit_policy="required", risk_level="system",
        idempotency="request",
    ))

    result = await runtime.execute(
        _context(), ToolInvocation("demo", idempotency_key="request-1"),
    )

    record = store.get("demo", "request-1")
    assert result.state == "tool_audit_outcome_unknown"
    assert record is not None and record.state == "unknown"
    assert record.dispatch_state == "terminal"
    assert record.effect_receipt["resolution"] == "confirmed_tool_effect_completed"


@pytest.mark.asyncio
async def test_terminal_receipt_survives_result_commit_failure() -> None:
    class CommitFailStore(InMemoryToolOperationStore):
        def complete(self, *_args, **_kwargs):
            return False

    tool = _Tool()
    store = CommitFailStore(durable=True)
    runtime = ProductToolRuntime(
        enabled_tool_ids=["demo"], audit=_Audit(), operation_store=store,
    )
    runtime.register(tool, ToolManifest(
        "demo", "2", audit_policy="required", risk_level="system",
        idempotency="request",
    ))

    result = await runtime.execute(
        _context(), ToolInvocation("demo", idempotency_key="request-1"),
    )

    record = store.get("demo", "request-1")
    assert result.state == "tool_outcome_unknown"
    assert record is not None and record.state == "unknown"
    assert record.effect_receipt["resolution"] == "confirmed_tool_effect_completed"


@pytest.mark.asyncio
async def test_side_effect_canonicalization_failure_is_fail_closed() -> None:
    class BrokenCanonicalTool(_Tool):
        def canonical_effect_parameters(self, _parameters, _context=None):
            raise ValueError("position catalog unavailable")

    tool = BrokenCanonicalTool()
    store = InMemoryToolOperationStore(durable=True)
    runtime = ProductToolRuntime(
        enabled_tool_ids=["demo"], audit=_Audit(), operation_store=store,
    )
    runtime.register(tool, ToolManifest(
        "demo", "2", risk_level="system", idempotency="request",
    ))

    first = await runtime.execute(_context(), ToolInvocation(
        "demo", {"effect": 1, "noise": 1}, idempotency_key="request-1",
    ))
    second = await runtime.execute(_context(), ToolInvocation(
        "demo", {"effect": 1, "noise": 2}, idempotency_key="request-2",
    ))

    assert first.state == second.state == "tool_effect_canonicalization_failed"
    assert tool.calls == 0
    assert store.unresolved_records() == ()


@pytest.mark.asyncio
async def test_cancel_while_waiting_for_resource_proves_not_dispatched() -> None:
    blocker = _Tool()
    blocker.name = "blocker"
    blocker.entered = asyncio.Event()
    blocker.release = asyncio.Event()
    effect = _Tool()
    effect.name = "effect"
    store = InMemoryToolOperationStore(durable=True)
    runtime = ProductToolRuntime(
        enabled_tool_ids=["blocker", "effect"], audit=_Audit(),
        operation_store=store,
    )
    runtime.register(blocker, ToolManifest(
        "blocker", "2", resources=("controller",),
    ))
    runtime.register(effect, ToolManifest(
        "effect", "2", resources=("controller",), risk_level="system",
        idempotency="request", audit_policy="required",
    ))
    holding = asyncio.create_task(runtime.execute(
        _context(), ToolInvocation("blocker"),
    ))
    await blocker.entered.wait()
    waiting = asyncio.create_task(runtime.execute(
        _context(), ToolInvocation("effect", idempotency_key="request-1"),
    ))
    await asyncio.sleep(0.01)
    waiting.cancel()

    with pytest.raises(asyncio.CancelledError):
        await waiting
    record = store.get("effect", "request-1")
    assert effect.calls == 0
    assert record is not None and record.state == "unknown"
    assert record.effect_receipt["resolution"] == "confirmed_tool_effect_not_started"
    assert record.effect_receipt["source"] == "operation_store_pre_dispatch_state"
    blocker.release.set()
    await holding


@pytest.mark.asyncio
async def test_write_tool_timeout_is_never_reported_as_completed() -> None:
    tool = _Tool()
    tool.release = asyncio.Event()
    audit = _Audit()
    runtime = _runtime(
        tool,
        ToolManifest(
            "demo", "2", timeout_seconds=0.01,
            risk_level="motion", audit_policy="required", idempotency="request",
        ),
        audit=audit,
    )
    result = await runtime.execute(
        _context(), ToolInvocation("demo", idempotency_key="request-1"),
    )
    assert result.state == "tool_outcome_unknown"
    assert [event.event for event in audit.events] == [
        "tool_started", "tool_timed_out",
    ]


@pytest.mark.asyncio
async def test_supervised_timeout_holds_resource_until_worker_really_stops() -> None:
    entered = threading.Event()
    release = threading.Event()

    class BlockingLegacy:
        name = "physical"
        parameters = {"type": "object"}

        def canonical_effect_parameters(self, parameters):
            return dict(parameters)

        def execute(self, **_kwargs):
            entered.set()
            release.wait(timeout=2)
            return {"ok": True, "state": "late_completion", "data": {}, "errors": []}

    second = _Tool()
    second.name = "second"
    audit = _Audit()
    operation_store = InMemoryToolOperationStore(durable=True)
    runtime = ProductToolRuntime(
        enabled_tool_ids=["physical", "second"], audit=audit,
        operation_store=operation_store,
    )
    physical_manifest = ToolManifest(
        "physical", "2", timeout_seconds=0.02, risk_level="motion",
        resources=("controller",), audit_policy="required", idempotency="request",
    )
    runtime.register(
        LegacyRobotToolAdapter(BlockingLegacy(), manifest=physical_manifest),
        physical_manifest,
    )
    runtime.register(second, ToolManifest(
        "second", "2", resources=("controller",), audit_policy="required",
    ))

    first = await runtime.execute(
        _context(), ToolInvocation("physical", {"target": 1}, idempotency_key="one"),
    )
    assert entered.is_set() and first.state == "tool_outcome_unknown"
    blocked = asyncio.create_task(runtime.execute(_context(), ToolInvocation("second")))
    await asyncio.sleep(0.03)
    assert not blocked.done()
    retry = await runtime.execute(
        _context(), ToolInvocation("physical", {"target": 1}, idempotency_key="two"),
    )
    assert retry.state == "tool_outcome_unknown"

    release.set()
    assert (await asyncio.wait_for(blocked, timeout=1)).state == "done"
    await asyncio.sleep(0)
    record = operation_store.get("physical", "one")
    assert record is not None
    assert record.effect_operation_id
    assert record.effect_receipt == {
        "schema_version": 1,
        "source": "authenticated_application_tool_terminal",
        "effect_operation_id": record.effect_operation_id,
        "operation_fingerprint": record.operation_fingerprint,
        "target_device_id": "unconfigured-device",
        "resolution": "confirmed_tool_effect_completed",
        "terminal_state": "late_completion",
        "result_hash": record.effect_receipt["result_hash"],
        "observed_at": record.effect_receipt["observed_at"],
    }


@pytest.mark.asyncio
async def test_side_effect_cancel_is_unknown_and_persists_across_runtime_restart(
    tmp_path,
) -> None:
    entered = asyncio.Event()

    class EffectTool(_Tool):
        name = "effect"

        async def execute(self, context, invocation):
            del context, invocation
            self.calls += 1
            entered.set()
            await asyncio.Event().wait()
            return ToolResult.success(state="done")

    manifest = ToolManifest(
        "effect", "2", risk_level="system", idempotency="request",
        resources=("controller",), audit_policy="required",
    )
    path = tmp_path / "tool_operations.json"
    first_tool = EffectTool()
    first_runtime = ProductToolRuntime(
        enabled_tool_ids=["effect"], audit=_Audit(),
        operation_store=JsonToolOperationStore(path),
    )
    first_runtime.register(first_tool, manifest)
    invocation = ToolInvocation("effect", {"value": 1}, idempotency_key="request-1")
    task = asyncio.create_task(first_runtime.execute(_context(), invocation))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    same_runtime = await first_runtime.execute(_context(), invocation)
    restarted_tool = EffectTool()
    restarted_runtime = ProductToolRuntime(
        enabled_tool_ids=["effect"], audit=_Audit(),
        operation_store=JsonToolOperationStore(path),
    )
    restarted_runtime.register(restarted_tool, manifest)
    after_restart = await restarted_runtime.execute(
        _context(session_key="new-conversation"), invocation,
    )
    changed_request_key = await restarted_runtime.execute(
        _context(session_key="another-conversation"),
        ToolInvocation("effect", {"value": 1}, idempotency_key="request-2"),
    )

    assert same_runtime.state == "tool_outcome_unknown"
    assert after_restart.state == "tool_outcome_unknown"
    assert changed_request_key.state == "tool_outcome_unknown"
    assert first_tool.calls == 1
    assert restarted_tool.calls == 0


@pytest.mark.asyncio
async def test_robot_arm_ignored_parameters_cannot_bypass_effect_embargo() -> None:
    class UnknownDryRun:
        def __init__(self) -> None:
            self.calls = 0

        def preview_command(self, _command, _parameters):
            self.calls += 1
            return SimpleNamespace(
                ok=True,
                payload={
                    "ok": False, "state": "operation_outcome_unknown",
                    "message": "unknown", "data": {}, "errors": [],
                },
                error=None,
            )

    dry_run = UnknownDryRun()
    tool = LegacyRobotToolAdapter(
        RobotArmTool(dry_run_application=dry_run),
        manifest=ToolManifest(
            "robot_arm", "2", risk_level="system", idempotency="request",
            audit_policy="required",
        ),
    )
    operation_store = InMemoryToolOperationStore(durable=True)
    runtime = ProductToolRuntime(
        enabled_tool_ids=["robot_arm"], audit=_Audit(),
        target_device_id="controller-1",
        operation_store=operation_store,
    )
    runtime.register(tool, tool.manifest)

    first = await runtime.execute(_context(), ToolInvocation(
        "robot_arm", {"action": "io", "io_number": 1, "enabled": True},
        idempotency_key="request-1",
    ))
    unresolved_before_bypass = operation_store.unresolved_records()
    bypass = await runtime.execute(
        _context(session_key="new-conversation"), ToolInvocation(
            "robot_arm", {
                "action": "io", "io_number": 1, "enabled": True,
                "ignored_noise": "must-not-change-effect",
            },
            idempotency_key="request-2",
        ),
    )

    assert first.state == "operation_outcome_unknown"
    assert unresolved_before_bypass[0].effect_payload == {
        "action": "io", "io_number": 1, "enabled": True,
    }
    assert bypass.state == "tool_outcome_unknown"
    assert dry_run.calls == 1


@pytest.mark.asyncio
async def test_robot_arm_executes_the_same_frozen_named_position_effect() -> None:
    class ChangingPositionApplication:
        def __init__(self) -> None:
            self.reads = 0

        def query(self, _request):
            self.reads += 1
            return SimpleNamespace(ok=True, payload={"pose": {
                "x": self.reads, "y": 2, "z": 3, "rx": 4, "ry": 5, "rz": 6,
            }}, error=None)

    class CapturingDryRun:
        def __init__(self) -> None:
            self.pose = None

        def preview_command(self, _command, parameters):
            self.pose = parameters["target_pose"]
            return SimpleNamespace(ok=True, payload={
                "ok": True, "state": "zmotion_operator_dry_run",
                "data": {"real_execution": False}, "errors": [],
            }, error=None)

    positions = ChangingPositionApplication()
    dry_run = CapturingDryRun()
    manifest = ToolManifest(
        "robot_arm", "2", risk_level="system", idempotency="request",
        audit_policy="required",
    )
    store = InMemoryToolOperationStore(durable=True)
    runtime = ProductToolRuntime(
        enabled_tool_ids=["robot_arm"], audit=_Audit(),
        target_device_id="controller-1", operation_store=store,
    )
    runtime.register(LegacyRobotToolAdapter(RobotArmTool(
        dry_run_application=dry_run, position_application=positions,
    ), manifest=manifest), manifest)

    result = await runtime.execute(_context(), ToolInvocation(
        "robot_arm", {"action": "linear_move", "position": "A"},
        idempotency_key="request-1",
    ))

    record = store.get("robot_arm", "request-1")
    assert result.ok is True
    assert positions.reads == 1
    assert record.effect_payload["target_pose"]["x"] == 1.0
    assert dry_run.pose["x"] == 1.0


@pytest.mark.asyncio
async def test_side_effect_tool_fails_closed_without_durable_operation_store() -> None:
    tool = _Tool()
    runtime = ProductToolRuntime(enabled_tool_ids=["demo"], audit=_Audit())
    runtime.register(tool, ToolManifest(
        "demo", "2", risk_level="system", idempotency="request",
    ))
    result = await runtime.execute(
        _context(), ToolInvocation("demo", idempotency_key="request-1"),
    )
    assert result.state == "tool_operation_store_unavailable"
    assert tool.calls == 0


def test_side_effect_tool_cannot_claim_direct_controller_write_capability() -> None:
    runtime = ProductToolRuntime(enabled_tool_ids=["demo"], audit=_Audit())
    with pytest.raises(ValueError, match="cannot directly own controller writes"):
        runtime.register(_Tool(), ToolManifest(
            "demo", "2", required_capabilities=("real_writes",),
            risk_level="motion", idempotency="request",
        ))


def test_arbitrary_side_effect_tool_is_rejected_without_reviewed_adapter() -> None:
    class ArbitraryTool:
        name = "arbitrary"
        parameters = {"type": "object"}

        async def execute(self, _context, _invocation):
            return ToolResult.success(state="direct_write")

    runtime = ProductToolRuntime(enabled_tool_ids=["arbitrary"], audit=_Audit())
    with pytest.raises(ValueError, match="reviewed Application-only adapter"):
        runtime.register(ArbitraryTool(), ToolManifest(
            "arbitrary", "2", risk_level="system", idempotency="request",
        ))


def test_second_live_store_instance_does_not_recover_active_operation(tmp_path) -> None:
    path = tmp_path / "tool_operations.json"
    first = JsonToolOperationStore(path)
    assert first.begin(
        "robot_arm", "request-1", "fingerprint-1",
        effect_operation_id="effect-operation-1",
    ) is True

    concurrent = JsonToolOperationStore(path)
    record = concurrent.get("robot_arm", "request-1")

    assert record is not None
    assert record.state == "started"
    assert record.fingerprint == "fingerprint-1"
    assert "fingerprint-1" in concurrent.unresolved_fingerprints()


def test_started_operation_recovers_only_after_owner_process_exits(tmp_path) -> None:
    path = tmp_path / "tool_operations.json"
    script = (
        "import sys; from robot_server.tool_operation_store import JsonToolOperationStore; "
        "s=JsonToolOperationStore(sys.argv[1]); "
        "print(s.begin('robot_arm','request-1','fingerprint-1',"
        "effect_operation_id='effect-operation-1'),flush=True)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script, str(path)],
        cwd=str(pathlib.Path.cwd()), capture_output=True, text=True, check=True,
    )
    assert completed.stdout.strip() == "True"

    recovered = JsonToolOperationStore(path)
    record = recovered.get("robot_arm", "request-1")
    assert record is not None and record.state == "unknown"
    assert record.effect_receipt["resolution"] == "confirmed_tool_effect_not_started"
