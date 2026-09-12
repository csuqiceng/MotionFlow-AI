from unittest.mock import MagicMock

from robot_platform.application import (
    AuthenticatedPrincipal,
    RobotKnowledgeApplicationService,
    RobotKnowledgeQuery,
)


def _principal(role: str = "operator") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal("user-1", role, "session-1", "test")


def test_knowledge_application_whitelists_entries_and_filters_via_port() -> None:
    catalog = MagicMock()
    catalog.query_entries.return_value = [{
        "category": "safety",
        "title": "Stop",
        "content": "Press stop",
        "source": "manual",
        "token": "must-not-leak",
    }]
    service = RobotKnowledgeApplicationService(catalog)

    response = service.query(RobotKnowledgeQuery(
        _principal(), "query", category="safety", keyword="stop",
    ))

    assert response.ok
    assert response.payload == {
        "state": "knowledge_query",
        "entries": [{
            "category": "safety",
            "title": "Stop",
            "content": "Press stop",
            "source": "manual",
        }],
        "count": 1,
    }
    catalog.query_entries.assert_called_once_with(category="safety", keyword="stop")


def test_knowledge_application_rejects_untrusted_role_before_port_read() -> None:
    catalog = MagicMock()
    response = RobotKnowledgeApplicationService(catalog).query(
        RobotKnowledgeQuery(_principal("untrusted"), "list")
    )

    assert response.error.code == "knowledge_forbidden"
    catalog.list_entries.assert_not_called()


def test_knowledge_application_sanitizes_port_failure() -> None:
    catalog = MagicMock()
    catalog.list_entries.side_effect = RuntimeError("token=secret host=10.0.0.1")
    response = RobotKnowledgeApplicationService(catalog).query(
        RobotKnowledgeQuery(_principal(), "list")
    )

    assert response.error.code == "knowledge_state_unavailable"
    assert "secret" not in response.error.message
