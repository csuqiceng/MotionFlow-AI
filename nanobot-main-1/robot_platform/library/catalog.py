"""Read-only catalog of platform-controlled components (4 built-in).

Components are NOT engineer-editable (design §4.2), so the catalog is pure
in-memory dataclasses — no ``components.json`` persistence in A1.
"""

from __future__ import annotations

from robot_platform.library.models import Component, ParameterField


def _system_action() -> Component:
    return Component(
        id="system_action",
        func_num=104,
        name="系统动作",
        description="Func104 safety/control bits (estop/pause/cancel/reset).",
        risk_level="high",
        required_safety_state="operator_only",
        parameters=[
            ParameterField("stop_mode", "int", minimum=0, maximum=1),
            ParameterField("estop_ctrl", "int", minimum=0, maximum=2),
            ParameterField("pause_ctrl", "int", minimum=0, maximum=2),
            ParameterField("cancel_ctrl", "int", minimum=0, maximum=2),
            ParameterField("reset_ctrl", "int", minimum=0, maximum=1),
        ],
    )


def _linear_move() -> Component:
    return Component(
        id="linear_move",
        func_num=108,
        name="直线/位姿移动",
        description="Func108 linear/pose move to a 6-DOF target.",
        risk_level="high",
        parameters=[
            ParameterField("target_x", "float", unit="mm"),
            ParameterField("target_y", "float", unit="mm"),
            ParameterField("target_z", "float", unit="mm"),
            ParameterField("target_rx", "float", unit="deg"),
            ParameterField("target_ry", "float", unit="deg"),
            ParameterField("target_rz", "float", unit="deg"),
            ParameterField("spd_pct", "float", unit="%", minimum=0, maximum=100),
            ParameterField("acc_pct", "float", unit="%", minimum=0, maximum=100),
            ParameterField("dec_pct", "float", unit="%", minimum=0, maximum=100),
            ParameterField("move_type", "int", minimum=0, maximum=1),
            ParameterField("stop_cmd", "int", minimum=0, maximum=1),
            ParameterField("fuzzy_pos", "int", minimum=0, maximum=1, required=False, default=0),
            ParameterField("fuzzy_spd", "int", minimum=0, maximum=1, required=False, default=0),
            ParameterField("fuzzy_acc", "int", minimum=0, maximum=1, required=False, default=0),
            ParameterField("fuzzy_dec", "int", minimum=0, maximum=1, required=False, default=0),
        ],
    )


def _delay() -> Component:
    return Component(
        id="delay",
        func_num=110,
        name="延时",
        description="Func110 delay (can run parallel to motion).",
        risk_level="low",
        parameters=[ParameterField("delay_sec", "float", unit="sec", minimum=0)],
    )


def _io_write() -> Component:
    return Component(
        id="io_write",
        func_num=120,
        name="IO 写",
        description="Func120 set a digital output.",
        risk_level="medium",
        parameters=[
            ParameterField("io_no", "int", minimum=0),
            ParameterField("io_action", "int", minimum=0, maximum=1),
        ],
    )


class ComponentCatalog:
    """In-memory, read-only catalog of the 4 v1 components."""

    def __init__(self) -> None:
        self._components: dict[str, Component] = {}
        for factory in (_system_action, _linear_move, _delay, _io_write):
            comp = factory()
            self._components[comp.id] = comp

    def list_all(self) -> list[Component]:
        return sorted(self._components.values(), key=lambda c: c.id)

    def get(self, component_id: str) -> Component | None:
        return self._components.get(component_id)

    def func_to_id(self, func_num: int) -> str | None:
        for comp in self._components.values():
            if comp.func_num == func_num:
                return comp.id
        return None
