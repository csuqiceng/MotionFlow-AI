from __future__ import annotations

from pathlib import Path

from robot_ai.library.auth import EngineerTokenStore
from robot_ai.library.versioned_registry import VersionedCommandRegistry


def _valid_params(component_id: str) -> dict:
    """Build a complete, schema-valid parameter set for a component by
    introspecting the catalog (keeps these tests correct if the schema changes)."""
    from robot_ai.library.catalog import ComponentCatalog
    comp = ComponentCatalog().get(component_id)
    params: dict = {}
    for pf in comp.parameters:
        if not pf.required:
            continue
        if pf.type == "bool":
            params[pf.name] = False
        elif pf.type == "str":
            params[pf.name] = pf.default if pf.default is not None else ""
        elif pf.type in ("int", "float"):
            lo = pf.minimum
            hi = pf.maximum
            if lo is not None:
                params[pf.name] = lo
            elif hi is not None:
                params[pf.name] = hi
            else:
                params[pf.name] = 1 if pf.type == "int" else 1.0
    return params


def _setup(tmp_path: Path):
    cpath = tmp_path / "commands.json"
    apath = tmp_path / "audit.jsonl"
    reg = VersionedCommandRegistry(cpath, audit_path=apath)
    reg.create_entity("home", "linear_move", "Home", _valid_params("linear_move"))
    reg.publish("home", component_risk_level="high")
    reg.create_entity("scratch", "delay", "Scratch", {"ms": 100})
    store = EngineerTokenStore()
    token = store.issue()
    return cpath, apath, store, token


def _ak(store, token):
    return {"token_store": store, "engineer_token": token}


def test_engineer_commands_list_returns_summaries(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_engineer_commands
    cpath, apath, store, token = _setup(tmp_path)
    status, body = process_engineer_commands(commands_path=str(cpath), **_ak(store, token))
    assert status == 200
    ids = {e["command_id"] for e in body["data"]["entities"]}
    assert ids == {"home", "scratch"}
    sample = body["data"]["entities"][0]
    assert {"command_id", "name", "published_version", "has_draft",
            "draft_revision", "updated_at"} <= set(sample)
    assert "versions" not in sample and "draft" not in sample


def test_engineer_command_detail_and_404(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_engineer_command
    cpath, apath, store, token = _setup(tmp_path)
    s, body = process_engineer_command("home", commands_path=str(cpath), **_ak(store, token))
    assert s == 200 and body["data"]["published_version"] == 1 and "1" in body["data"]["versions"]
    s, _ = process_engineer_command("nope", commands_path=str(cpath), **_ak(store, token))
    assert s == 404


def test_engineer_create_generates_slug_and_initial_draft(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_engineer_create_command
    cpath, apath, store, token = _setup(tmp_path)
    status, body = process_engineer_create_command(
        {"name": "Pick Place", "component_id": "linear_move",
         "parameters": {"target_x": 1.0}, "aliases": ["pp"], "description": "d"},
        commands_path=str(cpath), audit_path=str(apath), **_ak(store, token))
    assert status == 201
    assert body["data"]["command_id"] == "pick-place"
    assert body["data"]["draft"]["revision"] == 1


def test_engineer_create_rejects_duplicate_slug(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_engineer_create_command
    cpath, apath, store, token = _setup(tmp_path)
    status, _ = process_engineer_create_command(
        {"name": "Home", "component_id": "linear_move", "parameters": {}},
        commands_path=str(cpath), audit_path=str(apath), **_ak(store, token))
    assert status == 409


def test_engineer_create_rejects_missing_name_or_component(tmp_path: Path) -> None:
    """Fix 5: empty name -> 400; empty component_id -> 400."""
    from nanobot.api.robot_routes import process_engineer_create_command
    cpath, apath, store, token = _setup(tmp_path)
    s, body = process_engineer_create_command(
        {"name": "", "component_id": "linear_move", "parameters": {}},
        commands_path=str(cpath), audit_path=str(apath), **_ak(store, token))
    assert s == 400
    s, body = process_engineer_create_command(
        {"name": "Some Name", "component_id": "", "parameters": {}},
        commands_path=str(cpath), audit_path=str(apath), **_ak(store, token))
    assert s == 400


def test_engineer_update_draft_full_replacement_and_409(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_engineer_update_draft
    cpath, apath, store, token = _setup(tmp_path)
    s, body = process_engineer_update_draft(
        "scratch", {"expected_revision": 1, "name": "Scratch2", "aliases": [],
                    "description": "", "component_id": "delay", "parameters": {"ms": 200}},
        commands_path=str(cpath), audit_path=str(apath), **_ak(store, token))
    assert s == 200 and body["data"]["draft"]["revision"] == 2
    s, body = process_engineer_update_draft(
        "scratch", {"expected_revision": 99, "name": "X", "aliases": [],
                    "description": "", "component_id": "delay", "parameters": {}},
        commands_path=str(cpath), audit_path=str(apath), **_ak(store, token))
    assert s == 409 and body["data"]["current_revision"] == 2


def test_engineer_start_draft_from_published(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_engineer_start_draft
    cpath, apath, store, token = _setup(tmp_path)
    s, body = process_engineer_start_draft("home", commands_path=str(cpath), audit_path=str(apath), **_ak(store, token))
    assert s == 201 and body["data"]["draft"]["base_version"] == 1 and body["data"]["draft"]["revision"] == 1


def test_engineer_start_draft_404_when_missing(tmp_path: Path) -> None:
    """R6: missing command -> 404, not 409."""
    from nanobot.api.robot_routes import process_engineer_start_draft
    cpath, apath, store, token = _setup(tmp_path)
    s, _ = process_engineer_start_draft("ghost", commands_path=str(cpath), audit_path=str(apath), **_ak(store, token))
    assert s == 404


def test_engineer_start_draft_409_when_draft_exists(tmp_path: Path) -> None:
    """R6/D1: a PUBLISHED command that already has a draft -> 409 (not silent replace)."""
    from nanobot.api.robot_routes import process_engineer_start_draft
    cpath, apath, store, token = _setup(tmp_path)
    s, _ = process_engineer_start_draft("home", commands_path=str(cpath), audit_path=str(apath), **_ak(store, token))  # create draft
    assert s == 201
    s, _ = process_engineer_start_draft("home", commands_path=str(cpath), audit_path=str(apath), **_ak(store, token))  # now exists
    assert s == 409


def test_engineer_start_draft_409_when_no_published_version(tmp_path: Path) -> None:
    """R6: draft-only command (no published version) -> 409."""
    from nanobot.api.robot_routes import process_engineer_start_draft
    cpath, apath, store, token = _setup(tmp_path)
    s, _ = process_engineer_start_draft("scratch", commands_path=str(cpath), audit_path=str(apath), **_ak(store, token))
    assert s == 409


def test_engineer_publish_validates_param_schema_and_derives_risk(tmp_path: Path) -> None:
    """R1: publish validates required/type/bool/range/unknown; derives risk from component."""
    from nanobot.api import robot_routes as routes
    cpath, apath, store, token = _setup(tmp_path)
    routes.process_engineer_start_draft("home", commands_path=str(cpath), audit_path=str(apath), **_ak(store, token))
    s, body = routes.process_engineer_publish("home", commands_path=str(cpath), audit_path=str(apath), **_ak(store, token))
    assert s == 200
    reg = VersionedCommandRegistry(cpath, audit_path=apath)
    e = reg.get_entity("home")
    assert e["published_version"] == 2
    assert e["versions"]["2"]["risk_level"] == "high"  # derived from linear_move


def test_engineer_publish_rejects_missing_required(tmp_path: Path) -> None:
    from nanobot.api import robot_routes as routes
    cpath, apath, store, token = _setup(tmp_path)
    routes.process_engineer_start_draft("home", commands_path=str(cpath), audit_path=str(apath), **_ak(store, token))
    # wipe a required parameter (linear_move has target_x etc. — check the catalog)
    VersionedCommandRegistry(cpath, audit_path=apath).update_draft(
        "home", expected_revision=1, name="Home", aliases=[], description="",
        component_id="linear_move", parameters={})  # missing required params
    s, body = routes.process_engineer_publish("home", commands_path=str(cpath), audit_path=str(apath), **_ak(store, token))
    assert s == 400 and "required" in body["error"]["message"].lower()


def test_engineer_publish_rejects_bool_as_number(tmp_path: Path) -> None:
    from nanobot.api import robot_routes as routes
    cpath, apath, store, token = _setup(tmp_path)
    routes.process_engineer_start_draft("home", commands_path=str(cpath), audit_path=str(apath), **_ak(store, token))
    # Set a numeric field to a bool — must be rejected even though bool is an int subclass.
    reg = VersionedCommandRegistry(cpath, audit_path=apath)
    # Find a numeric field name from the catalog and set it to True
    from robot_ai.library.catalog import ComponentCatalog
    num_field = next(pf.name for pf in ComponentCatalog().get("linear_move").parameters
                     if pf.type in ("int", "float"))
    params = dict(reg.get_entity("home")["draft"]["parameters"])
    params[num_field] = True
    reg.update_draft("home", expected_revision=1, name="Home", aliases=[], description="",
                     component_id="linear_move", parameters=params)
    s, body = routes.process_engineer_publish("home", commands_path=str(cpath), audit_path=str(apath), **_ak(store, token))
    assert s == 400 and "bool" in body["error"]["message"].lower()


def test_engineer_publish_rejects_unknown_parameter(tmp_path: Path) -> None:
    from nanobot.api import robot_routes as routes
    cpath, apath, store, token = _setup(tmp_path)
    routes.process_engineer_start_draft("home", commands_path=str(cpath), audit_path=str(apath), **_ak(store, token))
    VersionedCommandRegistry(cpath, audit_path=apath).update_draft(
        "home", expected_revision=1, name="Home", aliases=[], description="",
        component_id="linear_move",
        parameters={"target_x": 1.0, "totally_unknown_field": 7})  # unknown param
    s, body = routes.process_engineer_publish("home", commands_path=str(cpath), audit_path=str(apath), **_ak(store, token))
    assert s == 400 and "unknown" in body["error"]["message"].lower()


def test_engineer_publish_rejects_out_of_range(tmp_path: Path) -> None:
    from nanobot.api import robot_routes as routes
    from robot_ai.library.catalog import ComponentCatalog
    cpath, apath, store, token = _setup(tmp_path)
    routes.process_engineer_start_draft("home", commands_path=str(cpath), audit_path=str(apath), **_ak(store, token))
    reg = VersionedCommandRegistry(cpath, audit_path=apath)
    comp = ComponentCatalog().get("linear_move")
    ranged = next((pf for pf in comp.parameters if pf.minimum is not None or pf.maximum is not None), None)
    if ranged is None:
        return  # component has no ranged field — skip (no-op) rather than fail
    params = dict(reg.get_entity("home")["draft"]["parameters"])
    params[ranged.name] = (ranged.maximum + 1000) if ranged.maximum is not None else (ranged.minimum - 1000)
    reg.update_draft("home", expected_revision=1, name="Home", aliases=[], description="",
                     component_id="linear_move", parameters=params)
    s, body = routes.process_engineer_publish("home", commands_path=str(cpath), audit_path=str(apath), **_ak(store, token))
    assert s == 400


def test_engineer_publish_namespace_conflict_returns_409(tmp_path: Path) -> None:
    """Fix 2: a draft whose name collides with an already-published command's name
    must return 409 (namespace_conflict). The draft must first pass R1 schema
    validation so the conflict — not a 400 — is what's exercised."""
    from nanobot.api import robot_routes as routes
    cpath, apath, store, token = _setup(tmp_path)
    # 'other' uses io_write with a VALID parameter set so R1 passes; its draft name
    # is renamed to "Home" which collides with the published 'home' command's name.
    VersionedCommandRegistry(cpath, audit_path=apath).create_entity(
        "other", "io_write", "Other", _valid_params("io_write"))
    VersionedCommandRegistry(cpath, audit_path=apath).update_draft(
        "other", expected_revision=1, name="Home", aliases=[], description="",
        component_id="io_write", parameters=_valid_params("io_write"))
    s, body = routes.process_engineer_publish("other", commands_path=str(cpath), audit_path=str(apath), **_ak(store, token))
    assert s == 409
    assert body["error"]["code"] == "namespace_conflict"


def test_engineer_publish_no_draft_returns_404(tmp_path: Path) -> None:
    """Fix 5: publishing a command whose draft is None -> 404 (no_draft)."""
    from nanobot.api import robot_routes as routes
    cpath, apath, store, token = _setup(tmp_path)
    # 'home' is freshly published with no new draft started -> draft is None.
    s, body = routes.process_engineer_publish("home", commands_path=str(cpath), audit_path=str(apath), **_ak(store, token))
    assert s == 404
    assert body["error"]["code"] == "no_draft"


def test_engineer_archive_draft_only_then_409(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_engineer_archive
    cpath, apath, store, token = _setup(tmp_path)
    s, _ = process_engineer_archive("scratch", commands_path=str(cpath), audit_path=str(apath), **_ak(store, token))
    assert s == 200
    s, _ = process_engineer_archive("home", commands_path=str(cpath), audit_path=str(apath), **_ak(store, token))
    assert s == 409


def test_engineer_endpoints_require_engineer_token(tmp_path: Path) -> None:
    from nanobot.api.robot_routes import process_engineer_commands
    cpath, apath, store, _t = _setup(tmp_path)
    s, body = process_engineer_commands(commands_path=str(cpath), token_store=store, engineer_token=None)
    assert s == 401 and body["error"]["code"] == "engineer_unauthorized"
