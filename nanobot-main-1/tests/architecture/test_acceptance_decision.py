import json
from pathlib import Path


def test_physical_split_stays_no_go_until_external_evidence_exists() -> None:
    root = Path(__file__).resolve().parents[2]
    status = json.loads((
        root / "docs" / "architecture" / "motionflow-acceptance-status.json"
    ).read_text(encoding="utf-8"))

    assert status["physical_split_decision"] == "no_go"
    assert status["external_acceptance"]["hardware_motion_and_safety"] == "ready_not_run"
    assert status["external_acceptance"]["second_real_product"] == "not_available"
