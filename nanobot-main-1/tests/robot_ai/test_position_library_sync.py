from __future__ import annotations

import importlib.resources
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from robot_platform.adapters.library_management import (
    FileCommandLibraryManagementAdapter,
)
from robot_platform.library.auth import hash_password
from robot_platform.library.mutation_service import (
    RobotLibraryMutationService,
    ensure_published_position_commands,
)
from robot_platform.library.users import UserRegistry, initialize_user_identity
from robot_platform.positions.defaults import ensure_default_positions
from robot_server.identity_api import RobotIdentityService


def test_packaged_position_configuration_is_imported_without_code_defaults(tmp_path) -> None:
    expected = json.loads(
        (
            importlib.resources.files("robot_platform.positions")
            / "seed_positions.json"
        ).read_text(encoding="utf-8")
    )["positions"]
    ensure_default_positions(tmp_path / "positions.json")
    payload = json.loads((tmp_path / "positions.json").read_text(encoding="utf-8"))
    assert payload["positions"] == sorted(expected, key=lambda item: item["name"])


def test_saved_position_is_published_as_a_linear_move_command(tmp_path) -> None:
    service = RobotLibraryMutationService(tmp_path)
    result = service.create_position(
        {
            "name": "测试",
            "pose": {"x": 999.99, "y": 0, "z": 800.04, "rx": -9.6, "ry": 90, "rz": -9.6},
            "spd": 20,
            "move_type": 0,
        },
        actor="operator:test",
    )
    assert result["command"]["published_version"] == 1
    command = result["command"]["versions"]["1"]
    assert command["component_id"] == "linear_move"
    assert command["parameters"]["target_x"] == 999.99

    # Existing positions from an older install are backfilled when the library
    # is opened, not only when they are saved again.
    ensure_published_position_commands(tmp_path)
    commands = json.loads((tmp_path / "commands.json").read_text(encoding="utf-8"))
    assert "测试" in commands["commands"]


def test_position_import_does_not_rewrite_existing_project_motion_command(tmp_path) -> None:
    service = RobotLibraryMutationService(tmp_path)
    service.create_command(
        {
            "name": "配置位置",
            "component_id": "linear_move",
            "parameters": {
                "target_x": 1,
                "target_y": 2,
                "target_z": 3,
                "target_rx": 4,
                "target_ry": 5,
                "target_rz": 6,
                "spd_pct": 20,
                "acc_pct": 37,
                "dec_pct": 43,
                "move_type": 0,
                "stop_cmd": 0,
            },
        },
        actor="engineer:config-import",
    )
    from robot_platform.positions.registry import NamedPosition, PositionRegistry

    PositionRegistry(tmp_path / "positions.json").register(
        NamedPosition("配置位置", [10, 20, 30, 40, 50, 60], spd=10)
    )

    ensure_published_position_commands(tmp_path)
    commands = json.loads((tmp_path / "commands.json").read_text(encoding="utf-8"))
    published = commands["commands"]["配置位置"]["versions"]["1"]
    assert published["parameters"]["acc_pct"] == 37
    assert published["parameters"]["dec_pct"] == 43


def test_position_create_rolls_back_all_files_when_command_write_fails(
    tmp_path, monkeypatch,
) -> None:
    service = RobotLibraryMutationService(tmp_path)

    def fail_after_position_write(*args, **kwargs):
        del args, kwargs
        raise OSError("injected command persistence failure")

    monkeypatch.setattr(service, "_upsert_position_command", fail_after_position_write)

    with pytest.raises(OSError, match="injected command persistence failure"):
        service.create_position({
            "name": "事务位置",
            "pose": {"x": 1, "y": 2, "z": 3, "rx": 4, "ry": 5, "rz": 6},
        }, actor="operator:test")

    assert not (tmp_path / "positions.json").exists()
    assert not (tmp_path / "commands.json").exists()
    audit = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "library_transaction_rollback" in audit


def test_position_update_restores_both_registries_when_command_write_fails(
    tmp_path, monkeypatch,
) -> None:
    service = RobotLibraryMutationService(tmp_path)
    service.create_position({
        "name": "事务位置",
        "pose": {"x": 1, "y": 2, "z": 3, "rx": 4, "ry": 5, "rz": 6},
    }, actor="operator:test")
    before = {
        name: (tmp_path / name).read_bytes()
        for name in ("positions.json", "commands.json")
    }
    audit_before = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")

    def fail_after_position_write(*args, **kwargs):
        del args, kwargs
        raise OSError("injected command persistence failure")

    monkeypatch.setattr(service, "_upsert_position_command", fail_after_position_write)

    with pytest.raises(OSError, match="injected command persistence failure"):
        service.update_position({
            "name": "事务位置",
            "pose": {"x": 10, "y": 20, "z": 30, "rx": 40, "ry": 50, "rz": 60},
        }, actor="engineer:test")

    assert {
        name: (tmp_path / name).read_bytes()
        for name in ("positions.json", "commands.json")
    } == before
    audit_after = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert audit_after.startswith(audit_before)
    assert "library_transaction_rollback" in audit_after[len(audit_before):]


def test_failed_position_rollback_cannot_erase_concurrent_adapter_commit(
    tmp_path, monkeypatch,
) -> None:
    position_service = RobotLibraryMutationService(tmp_path)
    management = FileCommandLibraryManagementAdapter(tmp_path)
    position_in_second_stage = Event()
    allow_position_failure = Event()
    management_started = Event()
    management_entered = Event()

    def fail_position_command(*args, **kwargs):
        del args, kwargs
        position_in_second_stage.set()
        assert allow_position_failure.wait(2)
        raise OSError("injected second-stage failure")

    original_create = management._create

    def observe_management_entry(body, actor):
        management_entered.set()
        return original_create(body, actor)

    monkeypatch.setattr(
        position_service, "_upsert_position_command", fail_position_command,
    )
    monkeypatch.setattr(management, "_create", observe_management_entry)

    def create_position():
        return position_service.create_position({
            "name": "transaction-position",
            "pose": {"x": 1, "y": 2, "z": 3, "rx": 4, "ry": 5, "rz": 6},
        }, actor="operator:test")

    def create_command():
        management_started.set()
        return management.execute(
            "create",
            "",
            {
                "name": "concurrent-delay",
                "component_id": "delay",
                "parameters": {"delay_sec": 1.0},
            },
            actor="test:engineer-1",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        position_future = pool.submit(create_position)
        assert position_in_second_stage.wait(2)
        command_future = pool.submit(create_command)
        assert management_started.wait(2)
        assert not management_entered.wait(0.1)
        allow_position_failure.set()
        with pytest.raises(OSError, match="injected second-stage failure"):
            position_future.result(timeout=2)
        command_response = command_future.result(timeout=2)

    assert command_response.ok
    commands = json.loads((tmp_path / "commands.json").read_text(encoding="utf-8"))
    assert "concurrent-delay" in commands["commands"]
    audit = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "test:engineer-1" in audit
    assert "library_transaction_rollback" in audit
    assert not (tmp_path / "positions.json").exists()


def test_failed_position_rollback_preserves_concurrent_identity_audit(
    tmp_path, monkeypatch,
) -> None:
    initialize_user_identity(
        users_path=tmp_path / "users.json", audit_path=tmp_path / "audit.jsonl",
    )
    users = UserRegistry(
        tmp_path / "users.json", audit_path=tmp_path / "audit.jsonl",
    )
    admin = users.get_by_username("admin")
    assert admin is not None
    users.bootstrap_set_password(
        admin["user_id"], hash_password("test-password", iterations=100_000),
    )
    identity = RobotIdentityService(tmp_path)
    position_service = RobotLibraryMutationService(tmp_path)
    position_in_second_stage = Event()
    allow_position_failure = Event()

    def fail_position_command(*args, **kwargs):
        del args, kwargs
        position_in_second_stage.set()
        assert allow_position_failure.wait(2)
        raise OSError("injected second-stage failure")

    monkeypatch.setattr(
        position_service, "_upsert_position_command", fail_position_command,
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        position_future = pool.submit(
            position_service.create_position,
            {
                "name": "transaction-position",
                "pose": {"x": 1, "y": 2, "z": 3, "rx": 4, "ry": 5, "rz": 6},
            },
            actor="operator:test",
        )
        assert position_in_second_stage.wait(2)
        login_future = pool.submit(
            identity.login,
            {
                "username": "admin",
                "password": "test-password",
                "role": "engineer",
            },
            client_key="concurrent-login",
        )
        status, _result = login_future.result(timeout=2)
        assert status == 200
        allow_position_failure.set()
        with pytest.raises(OSError, match="injected second-stage failure"):
            position_future.result(timeout=2)

    audit_entries = [
        json.loads(line)
        for line in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(entry.get("action") == "user_login" for entry in audit_entries)
    assert any(
        entry.get("action") == "library_transaction_rollback"
        and entry.get("result") == "compensated"
        for entry in audit_entries
    )
