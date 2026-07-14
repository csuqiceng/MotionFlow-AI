import json
from datetime import datetime
from pathlib import Path

import pytest

from nanobot.session.manager import SessionManager
from nanobot.session.namespace import (
    NamespaceAlreadyBoundError,
    SessionNotAvailableError,
    derive_namespace,
)


def test_derive_namespace_format():
    assert derive_namespace("engineer", "AbCd1234") == "engineer:AbCd1234"
    assert derive_namespace("operator", "Zx9Y") == "operator:Zx9Y"

def test_derive_namespace_rejects_bad_role():
    with pytest.raises(ValueError):
        derive_namespace("admin", "uid")

def test_exception_types():
    assert issubclass(SessionNotAvailableError, Exception)
    assert issubclass(NamespaceAlreadyBoundError, ValueError)


@pytest.fixture()
def manager(tmp_path: Path) -> SessionManager:
    return SessionManager(tmp_path)

def test_stamp_namespace_sets_metadata(manager):
    manager.stamp_namespace("websocket:c1", "engineer:AbCd1234")
    assert manager.get_or_create("websocket:c1").metadata.get("namespace") == "engineer:AbCd1234"

def test_stamp_namespace_idempotent_same_value(manager):
    manager.stamp_namespace("websocket:c2", "operator:Zx9Y")
    manager.stamp_namespace("websocket:c2", "operator:Zx9Y")
    assert manager.get_or_create("websocket:c2").metadata.get("namespace") == "operator:Zx9Y"

def test_stamp_namespace_rejects_different_value(manager):
    manager.stamp_namespace("websocket:c3", "engineer:AbCd1234")
    with pytest.raises(NamespaceAlreadyBoundError):
        manager.stamp_namespace("websocket:c3", "engineer:ATTACKER")
    assert manager.get_or_create("websocket:c3").metadata.get("namespace") == "engineer:AbCd1234"

def test_legacy_session_loads_without_namespace(manager):
    key = "websocket:legacy-1"
    path = manager._get_session_path(key)  # noqa: SLF001
    path.write_text(json.dumps({"_type": "metadata", "key": key,
        "created_at": datetime.now().isoformat(), "updated_at": datetime.now().isoformat(),
        "metadata": {}}) + "\n", encoding="utf-8")
    assert manager.get_or_create(key).metadata.get("namespace") is None


def _write_legacy(manager, key):
    path = manager._get_session_path(key)  # noqa: SLF001
    path.write_text(json.dumps({"_type": "metadata", "key": key,
        "created_at": datetime.now().isoformat(), "updated_at": datetime.now().isoformat(),
        "metadata": {}}) + "\n", encoding="utf-8")

def test_assert_owner_ok(manager):
    manager.stamp_namespace("websocket:o", "engineer:AbCd1234")
    manager.assert_namespace_owner("websocket:o", "engineer:AbCd1234")

def test_assert_owner_cross_user_raises(manager):
    manager.stamp_namespace("websocket:s", "engineer:AbCd1234")
    with pytest.raises(SessionNotAvailableError):
        manager.assert_namespace_owner("websocket:s", "engineer:OTHER")

def test_assert_owner_legacy_raises(manager):
    _write_legacy(manager, "websocket:lg")
    with pytest.raises(SessionNotAvailableError):
        manager.assert_namespace_owner("websocket:lg", "engineer:AbCd1234")

def test_assert_owner_missing_key_indistinguishable(manager):
    with pytest.raises(SessionNotAvailableError):
        manager.assert_namespace_owner("websocket:ghost", "engineer:AbCd1234")

def test_list_sessions_filters_by_namespace(manager):
    manager.stamp_namespace("websocket:a", "engineer:AbCd1234")
    manager.stamp_namespace("websocket:b", "operator:Zx9Y")
    _write_legacy(manager, "websocket:legacy-3")
    eng = manager.list_sessions(namespace="engineer:AbCd1234")
    op = manager.list_sessions(namespace="operator:Zx9Y")
    assert [s["key"] for s in eng] == ["websocket:a"]
    assert [s["key"] for s in op] == ["websocket:b"]
    assert not any(s["key"] == "websocket:legacy-3" for s in eng + op)

def test_list_sessions_no_filter_returns_all(manager):
    manager.stamp_namespace("websocket:c", "engineer:AbCd1234")
    _write_legacy(manager, "websocket:legacy-4")
    rows = manager.list_sessions()
    keys = {s["key"] for s in rows}
    assert "websocket:c" in keys and "websocket:legacy-4" in keys
