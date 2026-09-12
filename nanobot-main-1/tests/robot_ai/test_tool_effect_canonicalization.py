from __future__ import annotations

from types import SimpleNamespace

from ai_runtime.identity import bind_verified_principal, issue_verified_principal
from ai_runtime.robot_tools.robot_flow import RobotFlowTool
from ai_runtime.robot_tools.robot_library import RobotLibraryTool
from nanobot.agent.tools.cron import CronTool


def _flow() -> dict:
    return {
        "name": "pick", "flow_id": "flow-1", "description": "",
        "steps": [], "step_delay_ms": 1000, "rehearsal_spd": 20,
        "confirmed": True, "version": 3, "state": "published",
    }


def test_flow_name_and_alias_freeze_to_the_same_snapshot() -> None:
    class FlowApplication:
        def query(self, query, **_kwargs):
            assert query.name == "pick" or query.alias == "pick"
            return SimpleNamespace(
                ok=True, payload={"flow": _flow()}, error=None,
            )

    tool = RobotFlowTool(flow_application=FlowApplication())
    principal = issue_verified_principal(
        actor_id="operator-1", role="operator", session_id="session-1",
        auth_source="test",
    )
    with bind_verified_principal(principal):
        by_name = tool.canonical_effect_parameters({
            "action": "run", "name": "pick", "ignored": "noise",
        })
        by_alias = tool.canonical_effect_parameters({
            "action": "run", "flow_alias": "pick",
        })

    assert by_name == by_alias
    assert by_name["name"] == "pick"
    assert len(by_name["_flow_snapshot_hash"]) == 64


def test_cron_defaults_and_unused_fields_have_one_effect_identity() -> None:
    tool = CronTool(object(), default_timezone="Asia/Shanghai")
    implicit = tool.canonical_effect_parameters({
        "action": "add", "message": "daily check", "cron_expr": "0 9 * * *",
    })
    explicit = tool.canonical_effect_parameters({
        "action": "add", "message": "daily check", "name": "daily check",
        "cron_expr": "0 9 * * *", "tz": "Asia/Shanghai",
        "job_id": "ignored", "deliver": False,
    })

    assert implicit == explicit


def test_library_effect_contract_is_action_specific_and_numeric_stable() -> None:
    tool = RobotLibraryTool(library_application=object())
    first = tool.canonical_effect_parameters({
        "action": "preview_save", "resource_type": "position", "name": "A",
        "pose": {"x": 1, "y": 2}, "spd": 50,
        "aliases": ["b", "a"], "confirmation_token": "ignored",
    })
    second = tool.canonical_effect_parameters({
        "action": "preview_save", "resource_type": "position", "name": "A",
        "pose": {"x": 1.0, "y": 2.0}, "spd": 50.0,
        "aliases": ["a", "b"], "unrelated": "noise",
    })

    assert first == second


def test_library_flow_effect_includes_all_persisted_top_level_fields() -> None:
    tool = RobotLibraryTool(library_application=object())
    base = {
        "action": "preview_save",
        "resource_type": "flow",
        "name": "pick",
        "steps": [{"func_id": 110, "params": {"seconds": 1}}],
    }

    implicit_defaults = tool.canonical_effect_parameters(base)
    explicit_defaults = tool.canonical_effect_parameters({
        **base,
        "step_delay_ms": 1000.0,
        "rehearsal_spd": 20.0,
        "description": "",
        "node_graph": None,
    })
    changed = tool.canonical_effect_parameters({
        **base,
        "step_delay_ms": 250,
        "rehearsal_spd": 15,
        "description": "different",
        "node_graph": {"kind": "sequence", "children": []},
    })

    assert implicit_defaults == explicit_defaults
    assert changed != implicit_defaults
    assert changed["step_delay_ms"] == 250.0
    assert changed["rehearsal_spd"] == 15.0
    assert changed["node_graph"] == {"kind": "sequence", "children": []}
