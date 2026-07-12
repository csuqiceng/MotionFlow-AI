from __future__ import annotations

from pathlib import Path

from robot_ai.library.auth import UserSessionStore, hash_password
from robot_ai.library.users import UserRegistry


def _boot(tmp_path: Path):
    reg = UserRegistry(tmp_path / "users.json", audit_path=tmp_path / "audit.jsonl")
    admin = reg.create("admin", "engineer", hash_password("pw", iterations=100_000))
    op = reg.create("operator", "operator", hash_password("pw", iterations=100_000))
    store = UserSessionStore()
    admin_tok = store.issue({"user_id": admin["user_id"], "username": "admin", "role": "engineer"})
    op_tok = store.issue({"user_id": op["user_id"], "username": "operator", "role": "operator"})
    return reg, store, admin, admin_tok, op_tok


def _actor_of(store, tok):
    s = store.check(tok)
    return {"actor": f"user:{s['user_id']}", "actor_user_id": s["user_id"],
            "actor_username": s["username"], "actor_role": s["role"]}


def test_list_excludes_password_hash(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_users_list
    reg, store, admin, atok, _ = _boot(tmp_path)
    s, body = process_users_list(users_path=str(tmp_path / "users.json"),
                                  token_store=store, user_token=atok)
    assert s == 200
    assert all("password_hash" not in u for u in body["data"]["users"])


def test_create_and_duplicate(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_users_create
    reg, store, admin, atok, _ = _boot(tmp_path)
    s, body = process_users_create({"username": "Bob", "password": "p", "role": "engineer"},
                                    users_path=str(tmp_path / "users.json"), audit_path=str(tmp_path / "audit.jsonl"),
                                    token_store=store, user_token=atok, actor=_actor_of(store, atok))
    assert s == 201 and body["data"]["username"] == "Bob"
    s, _ = process_users_create({"username": "bob", "password": "p", "role": "engineer"},
                                  users_path=str(tmp_path / "users.json"), audit_path=str(tmp_path / "audit.jsonl"),
                                  token_store=store, user_token=atok, actor=_actor_of(store, atok))
    assert s == 409  # normalized dup


def test_disable_last_engineer_blocked(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_users_patch
    reg, store, admin, atok, _ = _boot(tmp_path)
    s, _ = process_users_patch(admin["user_id"], {"enabled": False},
                                users_path=str(tmp_path / "users.json"), audit_path=str(tmp_path / "audit.jsonl"),
                                token_store=store, user_token=atok, actor=_actor_of(store, atok))
    assert s == 409  # last engineer


def test_reset_password_revokes_target_sessions(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_users_reset_password
    reg, store, admin, atok, optok = _boot(tmp_path)
    s, _ = process_users_reset_password(reg.get_by_username("operator")["user_id"], {"new_password": "n"},
                                         users_path=str(tmp_path / "users.json"), audit_path=str(tmp_path / "audit.jsonl"),
                                         token_store=store, user_token=atok, actor=_actor_of(store, atok))
    assert s == 200 and store.check(optok) is None  # operator session revoked


def test_reset_password_rejects_self(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_users_reset_password
    reg, store, admin, atok, _ = _boot(tmp_path)
    s, body = process_users_reset_password(admin["user_id"], {"new_password": "n"},
                                            users_path=str(tmp_path / "users.json"), audit_path=str(tmp_path / "audit.jsonl"),
                                            token_store=store, user_token=atok, actor=_actor_of(store, atok))
    assert s == 409 and body["error"]["code"] == "use_me_password"


def test_me_password_verifies_old_and_revokes_self(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_users_me_password
    reg, store, admin, atok, _ = _boot(tmp_path)
    s, _ = process_users_me_password({"old_password": "wrong", "new_password": "n"},
                                      users_path=str(tmp_path / "users.json"), audit_path=str(tmp_path / "audit.jsonl"),
                                      token_store=store, user_token=atok, actor=_actor_of(store, atok))
    assert s == 401
    s, _ = process_users_me_password({"old_password": "pw", "new_password": "n"},
                                      users_path=str(tmp_path / "users.json"), audit_path=str(tmp_path / "audit.jsonl"),
                                      token_store=store, user_token=atok, actor=_actor_of(store, atok))
    assert s == 200 and store.check(atok) is None  # self revoked


def test_operator_forbidden_from_users_admin(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_users_create
    reg, store, admin, atok, optok = _boot(tmp_path)
    s, _ = process_users_create({"username": "x", "password": "p", "role": "engineer"},
                                  users_path=str(tmp_path / "users.json"), audit_path=str(tmp_path / "audit.jsonl"),
                                  token_store=store, user_token=optok, actor=_actor_of(store, optok))
    assert s == 403
