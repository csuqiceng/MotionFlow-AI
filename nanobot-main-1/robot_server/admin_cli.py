"""Local maintenance CLI for robot-platform identities.

This is intentionally separate from the chat-agent command line.  Passwords
are requested through ``getpass`` only and are never accepted as arguments.
"""

from __future__ import annotations

import getpass
from pathlib import Path

import typer

from robot_platform import UserRegistry, get_robot_data_dir, hash_password


app = typer.Typer(help="Robot platform maintenance commands.")
engineer_app = typer.Typer(help="Engineer account maintenance.")
users_app = typer.Typer(help="User bootstrap and password maintenance.")
app.add_typer(engineer_app, name="engineer")
app.add_typer(users_app, name="users")


def _registry(users_path: str | None, audit_path: str | None) -> UserRegistry:
    root = get_robot_data_dir()
    user_file = Path(users_path).expanduser() if users_path else root / "users.json"
    audit_file = Path(audit_path).expanduser() if audit_path else root / "audit.jsonl"
    return UserRegistry(user_file, audit_path=audit_file)


def _prompt_password(label: str) -> str:
    password = getpass.getpass(label)
    confirmation = getpass.getpass("Confirm password: ")
    if not password or password != confirmation:
        typer.echo("passwords do not match or are empty", err=True)
        raise typer.Exit(1)
    return password


@engineer_app.callback()
def engineer_main() -> None:
    """Engineer account maintenance commands."""


@engineer_app.command("set-password")
def engineer_set_password(
    config: str | None = typer.Option(None, "--config", "-c", help="Deprecated and ignored"),
    users_path: str | None = typer.Option(None, "--users-path", help="Path to users.json"),
    audit_path: str | None = typer.Option(None, "--audit-path", help="Path to audit.jsonl"),
) -> None:
    """Set the existing ``admin`` engineer password."""
    del config
    password = _prompt_password("Enter engineer password: ")
    registry = _registry(users_path, audit_path)
    admin = registry.get_by_username("admin")
    if admin is None:
        raise typer.BadParameter("admin user not found; bootstrap it first")
    actor = {"actor": "system:robot-admin", "actor_role": "system"}
    if admin["enabled"]:
        registry.set_password(admin["user_id"], hash_password(password), actor=actor)
    else:
        registry.bootstrap_set_password(admin["user_id"], hash_password(password), actor=actor)
    typer.echo("admin password updated")


@users_app.callback()
def users_main() -> None:
    """User bootstrap and password maintenance commands."""


@users_app.command("set-bootstrap-password")
def users_set_bootstrap_password(
    username: str = typer.Option(..., "--username", help="Existing username to enable/reset"),
    users_path: str | None = typer.Option(None, "--users-path", help="Path to users.json"),
    audit_path: str | None = typer.Option(None, "--audit-path", help="Path to audit.jsonl"),
) -> None:
    """Enable an existing user and atomically set its password."""
    registry = _registry(users_path, audit_path)
    user = registry.get_by_username(username)
    if user is None:
        raise typer.BadParameter(f"user {username!r} not found")
    password = _prompt_password(f"New password for {username}: ")
    registry.bootstrap_set_password(
        user["user_id"],
        hash_password(password),
        actor={"actor": "system:robot-admin", "actor_role": "system"},
    )
    typer.echo(f"password set and {username!r} enabled")


if __name__ == "__main__":
    app()
