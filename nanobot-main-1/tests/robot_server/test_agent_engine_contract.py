"""Robot Server depends on the stable agent engine contract, not Nanobot."""

from __future__ import annotations

import ast
from pathlib import Path

from ai_runtime.contracts import RuntimeEvent, RuntimeRequest
from ai_runtime.engine_contract import AgentEngine, AgentEvent, AgentRequest


def test_agent_contract_reuses_current_wire_request_and_event_models() -> None:
    assert AgentRequest is RuntimeRequest
    assert AgentEvent is RuntimeEvent
    assert AgentEngine.__name__ == "AgentEngine"


def test_robot_server_imports_only_the_agent_engine_contract() -> None:
    source = Path(__file__).parents[2] / "robot_server" / "app.py"
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert "ai_runtime.agent_runtime" not in imports
    assert "ai_runtime.engine_contract" in imports
