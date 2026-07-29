"""Local operator/engineer identity service for ``robot_server``."""

from __future__ import annotations

import secrets
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from robot_platform.application import AuthenticatedPrincipal
from robot_platform import (
    LastEngineerError, LoginThrottle, UserRegistry, UserSessionStore, _audit_append,
    hash_password, initialize_user_identity, verify_password,
)


class RobotIdentityService:
    """Authenticate local users without depending on WebUI or gateway tokens."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._users_path = data_dir / "users.json"
        self._audit_path = data_dir / "audit.jsonl"
        self._tokens = UserSessionStore()
        self._throttle = LoginThrottle()

    def login(self, body: Any, *, client_key: str) -> tuple[int, dict[str, Any]]:
        self._ensure_initialized()
        if self._throttle.is_throttled(client_key):
            return 429, {
                "error": {"code": "too_many_attempts", "message": "Too many login attempts."},
                "retry_after": self._throttle.retry_after(client_key),
            }
        if not isinstance(body, dict):
            self._failure(client_key, "invalid_body")
            return _invalid_credentials()
        username = str(body.get("username", ""))
        password = str(body.get("password", ""))
        role = str(body.get("role", ""))
        if role not in {"operator", "engineer"}:
            self._failure(client_key, "invalid_role")
            return _invalid_credentials()

        user = self._registry().get_by_username(username)
        if user is None or user.get("role") != role:
            self._failure(client_key, "invalid_user_or_role")
            return _invalid_credentials()
        if not user.get("enabled"):
            return 403, {"error": {"code": "user_disabled", "message": "Account is disabled."}}
        if not verify_password(password, str(user.get("password_hash", ""))):
            self._failure(client_key, "invalid_password", user)
            return _invalid_credentials()

        self._throttle.reset(client_key)
        token = self._tokens.issue(_public_user(user))
        try:
            _audit_append(self._audit_path, _audit_entry("user_login", user, result="success"))
        except OSError:
            self._tokens.revoke(token)
            return 503, {
                "error": {"code": "audit_write_failed", "message": "Login audit could not be recorded."}
            }
        return 200, {
            "ok": True,
            "data": {
                "user_token": token,
                "expires_in": self._tokens.ttl_seconds,
                "user": _public_user(user),
            },
        }

    def logout(self, token: str) -> tuple[int, dict[str, Any]]:
        session = self._tokens.check(token)
        self._tokens.revoke(token)
        try:
            _audit_append(
                self._audit_path,
                _audit_entry("user_logout", session or {}, result="success"),
            )
        except OSError:
            pass
        return 200, {"ok": True, "data": {"revoked": True}}

    def session(self, token: str) -> tuple[int, dict[str, Any]]:
        session = self._tokens.check(token)
        if session is None:
            return 401, {"error": {"code": "unauthorized", "message": "Valid user token required."}}
        return 200, {"ok": True, "data": {"user": _public_user(session)}}

    def list_users(self, token: str) -> tuple[int, dict[str, Any]]:
        session, error = self._require_engineer(token)
        if error is not None:
            return error
        users = [_public_user(user) | {
            "enabled": bool(user.get("enabled")),
            "created_at": str(user.get("created_at", "")),
            "updated_at": str(user.get("updated_at", "")),
        } for user in self._registry().list_all()]
        return 200, {"ok": True, "data": {"users": users, "actor": _public_user(session)}}

    def create_user(self, token: str, body: Any) -> tuple[int, dict[str, Any]]:
        session, error = self._require_engineer(token)
        if error is not None:
            return error
        if not isinstance(body, dict):
            return _invalid_request("request body must be an object")
        try:
            user = self._registry().create(
                str(body.get("username", "")),
                str(body.get("role", "")),
                hash_password(str(body.get("password", ""))),
                actor=_actor(session),
            )
        except ValueError as exc:
            return 409, {"error": {"code": "user_exists", "message": str(exc)}}
        return 201, {"ok": True, "data": _public_user(user) | {"enabled": user["enabled"]}}

    def update_user(self, token: str, user_id: str, body: Any) -> tuple[int, dict[str, Any]]:
        session, error = self._require_engineer(token)
        if error is not None:
            return error
        if not isinstance(body, dict):
            return _invalid_request("request body must be an object")
        try:
            user = self._registry().update(
                user_id,
                enabled=body.get("enabled"),
                role=body.get("role"),
                actor=_actor(session),
            )
        except LastEngineerError as exc:
            return 409, {"error": {"code": "last_engineer_protected", "message": str(exc)}}
        except ValueError as exc:
            return 404, {"error": {"code": "user_not_found", "message": str(exc)}}
        if body.get("enabled") is False or body.get("role") is not None:
            self._tokens.revoke_by_user_id(user_id)
        return 200, {"ok": True, "data": _public_user(user) | {"enabled": user["enabled"]}}

    def reset_password(self, token: str, user_id: str, body: Any) -> tuple[int, dict[str, Any]]:
        session, error = self._require_engineer(token)
        if error is not None:
            return error
        if session["user_id"] == user_id:
            return 409, {"error": {"code": "use_me_password", "message": "Use the self-service route."}}
        if not isinstance(body, dict):
            return _invalid_request("request body must be an object")
        try:
            self._registry().set_password(
                user_id,
                hash_password(str(body.get("new_password", ""))),
                actor=_actor(session),
                action="user_password_reset",
            )
        except ValueError as exc:
            return 404, {"error": {"code": "user_not_found", "message": str(exc)}}
        self._tokens.revoke_by_user_id(user_id)
        return 200, {"ok": True, "data": {"reset": user_id}}

    def delete_user(self, token: str, user_id: str) -> tuple[int, dict[str, Any]]:
        session, error = self._require_engineer(token)
        if error is not None:
            return error
        if session["user_id"] == user_id:
            return 409, {
                "error": {
                    "code": "cannot_delete_self",
                    "message": "Cannot delete the currently signed-in account.",
                }
            }
        try:
            self._registry().delete(user_id, actor=_actor(session))
        except LastEngineerError as exc:
            return 409, {"error": {"code": "last_engineer_protected", "message": str(exc)}}
        except ValueError as exc:
            return 404, {"error": {"code": "user_not_found", "message": str(exc)}}
        self._tokens.revoke_by_user_id(user_id)
        return 200, {"ok": True, "data": {"deleted": user_id}}

    def change_own_password(self, token: str, body: Any) -> tuple[int, dict[str, Any]]:
        session = self._tokens.check(token)
        if session is None:
            return 401, {"error": {"code": "unauthorized", "message": "Valid user token required."}}
        if not isinstance(body, dict):
            return _invalid_request("request body must be an object")
        user = self._registry().get(session["user_id"])
        if user is None or not verify_password(str(body.get("old_password", "")), user["password_hash"]):
            return _invalid_credentials()
        self._registry().set_password(
            session["user_id"], hash_password(str(body.get("new_password", ""))), actor=_actor(session)
        )
        self._tokens.revoke_by_user_id(session["user_id"])
        return 200, {"ok": True, "data": {"changed": True}}

    def require_engineer_session(
        self, token: str
    ) -> tuple[dict[str, Any], tuple[int, dict[str, Any]] | None]:
        """Return the actor session for robot-management services."""
        return self._require_engineer(token)

    def require_session(
        self, token: str
    ) -> tuple[dict[str, Any], tuple[int, dict[str, Any]] | None]:
        session = self._tokens.check(token)
        if session is None:
            return {}, (401, {"error": {"code": "unauthorized", "message": "Valid user token required."}})
        return session, None

    def require_principal(
        self, token: str
    ) -> tuple[AuthenticatedPrincipal | None, tuple[int, dict[str, Any]] | None]:
        """Resolve a trusted application principal from a server-side session."""
        session, error = self.require_session(token)
        if error is not None:
            return None, error
        return AuthenticatedPrincipal(
            actor_id=str(session["user_id"]),
            role=str(session["role"]),
            session_id=str(session["session_id"]),
            auth_source="robot-user-session",
        ), None

    def _registry(self) -> UserRegistry:
        return UserRegistry(self._users_path, audit_path=self._audit_path)

    def _ensure_initialized(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._recover_legacy_identity_if_placeholder()
        initialize_user_identity(users_path=self._users_path, audit_path=self._audit_path)

    def _recover_legacy_identity_if_placeholder(self) -> None:
        """Recover real legacy users when first-run defaults masked migration.

        Early desktop builds seeded ``robot_platform`` before the platform
        migration could copy an existing ``robot_ai`` runtime.  Recovery is
        deliberately narrow: it only runs when every canonical account is a
        disabled placeholder and the legacy file contains an enabled user.
        The placeholder file is kept as a rollback backup.
        """
        legacy_path = self._data_dir.with_name("robot_ai") / "users.json"
        if not self._users_path.is_file() or not legacy_path.is_file():
            return
        try:
            current = json.loads(self._users_path.read_text(encoding="utf-8"))
            legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
            current_users = [item for item in current.get("users", {}).values() if isinstance(item, dict)]
            legacy_users = [item for item in legacy.get("users", {}).values() if isinstance(item, dict)]
        except (OSError, json.JSONDecodeError, AttributeError):
            return
        placeholders_only = bool(current_users) and all(not bool(user.get("enabled")) for user in current_users)
        legacy_is_usable = any(bool(user.get("enabled")) for user in legacy_users)
        if not placeholders_only or not legacy_is_usable:
            return
        backup_path = self._users_path.with_name("users.pre-legacy-recovery.json")
        if not backup_path.exists():
            shutil.copy2(self._users_path, backup_path)
        shutil.copy2(legacy_path, self._users_path)

    def _require_engineer(self, token: str) -> tuple[dict[str, Any], tuple[int, dict[str, Any]] | None]:
        session = self._tokens.check(token)
        if session is None:
            return {}, (401, {"error": {"code": "unauthorized", "message": "Valid user token required."}})
        if session["role"] != "engineer":
            return {}, (403, {"error": {"code": "forbidden", "message": "role='engineer' required."}})
        return session, None

    def _failure(self, client_key: str, reason: str, user: dict[str, Any] | None = None) -> None:
        self._throttle.record_failure(client_key)
        try:
            _audit_append(self._audit_path, _audit_entry("user_login", user or {}, result="failure", reason=reason))
        except OSError:
            pass


def _public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "user_id": str(user.get("user_id", "")),
        "username": str(user.get("username", "")),
        "role": str(user.get("role", "")),
    }


def _actor(session: dict[str, Any]) -> dict[str, Any]:
    user = _public_user(session)
    return {
        "actor": f"user:{user['user_id']}",
        "actor_user_id": user["user_id"],
        "actor_username": user["username"],
        "actor_role": user["role"],
    }


def _audit_entry(
    action: str, user: dict[str, Any], *, result: str, reason: str | None = None
) -> dict[str, Any]:
    actor = _public_user(user)
    payload: dict[str, Any] = {
        "action": action,
        "actor": f"user:{actor['user_id']}" if actor["user_id"] else "anon",
        "actor_user_id": actor["user_id"] or None,
        "actor_username": actor["username"] or None,
        "actor_role": actor["role"] or None,
        "result": result,
        "audit_id": secrets.token_urlsafe(16),
        "timestamp": datetime.now().isoformat(),
    }
    if reason is not None:
        payload["reason"] = reason
    return payload


def _invalid_credentials() -> tuple[int, dict[str, Any]]:
    return 401, {"error": {"code": "invalid_credentials", "message": "Invalid credentials."}}


def _invalid_request(message: str) -> tuple[int, dict[str, Any]]:
    return 400, {"error": {"code": "invalid_request", "message": message}}
