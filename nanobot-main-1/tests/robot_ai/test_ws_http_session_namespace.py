import pytest

from nanobot.session.namespace import SessionNotAvailableError


@pytest.fixture()
def store():
    from robot_ai.library.auth import get_user_session_store
    return get_user_session_store()

def test_derive_namespace_from_user_token(store):
    from nanobot.webui.ws_http import derive_namespace_from_user_token
    tok = store.issue({"user_id": "AbCd1234", "username": "e", "role": "engineer"})
    assert derive_namespace_from_user_token(tok) == "engineer:AbCd1234"

def test_derive_namespace_rejects_missing(store):
    from nanobot.webui.ws_http import derive_namespace_from_user_token
    assert derive_namespace_from_user_token("") is None
    assert derive_namespace_from_user_token("bogus") is None

def test_enforce_owner_raises_cross_namespace(tmp_path, store):
    from nanobot.session.manager import SessionManager
    from nanobot.webui.ws_http import enforce_session_owner
    mgr = SessionManager(tmp_path)
    mgr.stamp_namespace("websocket:vic", "engineer:OWNER")
    with pytest.raises(SessionNotAvailableError):
        enforce_session_owner(mgr, "websocket:vic", "engineer:ATTACKER")

def test_validate_namespace_param():
    from nanobot.webui.ws_http import validate_namespace_param
    assert validate_namespace_param(derived="engineer:X", supplied="engineer:X")
    assert not validate_namespace_param(derived="engineer:X", supplied="engineer:Y")
    assert validate_namespace_param(derived="engineer:X", supplied=None)

def test_list_webui_sessions_filters_by_namespace(tmp_path):
    from nanobot.session.manager import SessionManager
    from nanobot.webui.session_list_index import list_webui_sessions
    mgr = SessionManager(tmp_path)
    mgr.stamp_namespace("websocket:mine", "engineer:AbCd1234")
    mgr.stamp_namespace("websocket:yours", "engineer:OTHER")
    rows = list_webui_sessions(mgr, namespace="engineer:AbCd1234")
    assert [r["key"] for r in rows] == ["websocket:mine"]

def test_index_version_bumped_forces_rebuild(tmp_path):
    import json as _json
    from nanobot.session.manager import SessionManager
    from nanobot.webui.session_list_index import _INDEX_VERSION, _INDEX_FILENAME, list_webui_sessions
    assert _INDEX_VERSION >= 3
    mgr = SessionManager(tmp_path)
    mgr.stamp_namespace("websocket:x", "engineer:AbCd1234")
    # write a stale v2 cache (no namespace) that must be ignored/rebuilt
    (mgr.sessions_dir / _INDEX_FILENAME).write_text(_json.dumps(
        {"version": 2, "sessions": [{"key": "websocket:x", "created_at": "x",
         "updated_at": "x", "title": "", "preview": "", "file": "x"}]}) + "\n", encoding="utf-8")
    rows = list_webui_sessions(mgr, namespace="engineer:AbCd1234")
    assert any(r["key"] == "websocket:x" for r in rows)  # stale v2 cache ignored, rebuilt with ns
