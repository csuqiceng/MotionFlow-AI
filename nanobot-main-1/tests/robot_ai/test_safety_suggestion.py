from __future__ import annotations

from robot_ai.safety import SafetyLimits, SafetySuggestionService


def _service() -> SafetySuggestionService:
    return SafetySuggestionService(SafetyLimits.default())


def test_clamp_target_x_into_soft_limit() -> None:
    result = _service().suggest({"target": {"x": 9999.0, "y": 0.0, "z": 999.0}, "speed": {}})
    assert result["available"] is True
    assert result["adjusted_plan"]["target"]["x"] == 3000.0
    assert any("X" in msg for msg in result["messages"])


def test_clamp_speed_into_limit() -> None:
    result = _service().suggest({"target": {}, "speed": {"spd_pct": 200.0}})
    assert result["adjusted_plan"]["speed"]["spd_pct"] == 100.0
    assert result["available"] is True


def test_no_suggestion_when_already_in_range() -> None:
    result = _service().suggest({"target": {"x": 0.0}, "speed": {"spd_pct": 5.0}})
    assert result["available"] is False
    assert result["messages"] == []
