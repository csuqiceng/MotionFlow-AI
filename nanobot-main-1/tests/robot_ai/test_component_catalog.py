from __future__ import annotations

from robot_ai.library.catalog import ComponentCatalog


def test_catalog_has_four_built_in_components() -> None:
    catalog = ComponentCatalog()
    ids = {c.id for c in catalog.list_all()}
    assert ids == {"system_action", "linear_move", "delay", "io_write"}


def test_catalog_get_found_and_missing() -> None:
    catalog = ComponentCatalog()
    assert catalog.get("linear_move") is not None
    assert catalog.get("nope") is None


def test_func_to_id_maps_allowlist_only() -> None:
    catalog = ComponentCatalog()
    assert catalog.func_to_id(104) == "system_action"
    assert catalog.func_to_id(108) == "linear_move"
    assert catalog.func_to_id(110) == "delay"
    assert catalog.func_to_id(120) == "io_write"
    assert catalog.func_to_id(106) is None  # joint — not in v1
    assert catalog.func_to_id(107) is None
    assert catalog.func_to_id(109) is None
    assert catalog.func_to_id(11) is None


def test_linear_move_schema_has_expected_fields() -> None:
    catalog = ComponentCatalog()
    comp = catalog.get("linear_move")
    names = {pf.name for pf in comp.parameters}
    assert {"target_x", "target_y", "target_z", "target_rx", "target_ry", "target_rz"}.issubset(names)
    assert {"spd_pct", "acc_pct", "dec_pct", "move_type"}.issubset(names)


def test_system_action_schema_has_control_fields() -> None:
    catalog = ComponentCatalog()
    names = {pf.name for pf in catalog.get("system_action").parameters}
    assert names == {"stop_mode", "estop_ctrl", "pause_ctrl", "cancel_ctrl", "reset_ctrl"}
