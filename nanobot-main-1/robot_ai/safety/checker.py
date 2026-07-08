"""L1 robot safety checker for motion confirmation.

Ported from the legacy Qt project (``robot_modbus_lite/robot_safety_checker.py``)
with only the L1 path retained. The legacy L2 inverse-kinematics preflight and
the pose-angle checker are intentionally dropped (they depend on
``MotionPlanService``/``KinematicsEngine`` and ``CommandDraft``/pose limits
that do not exist in this project yet). With ``strict_l2=False`` (the default)
an unavailable L2 is a soft pass, so the checker's verdict reduces to: L1 fail
-> unsafe; L1 pass -> safe. The output dict keeps the legacy field shape so a
future L2/pose layer can slot in without changing callers.
"""

from __future__ import annotations

from typing import Any, Iterable

from robot_ai.safety.precheck import SafetyPrecheckService


class RobotSafetyChecker:
    """Run the L1 precheck and report a legacy-shape safety verdict."""

    def __init__(
        self,
        *,
        l1_service: SafetyPrecheckService,
        strict_l2: bool = False,
    ) -> None:
        self.l1_service = l1_service
        # L2 is unavailable in this project; kept for signature stability.
        self.strict_l2 = bool(strict_l2)

    def check_target(
        self,
        *,
        target_pose: Iterable[float],
        snapshot: dict[str, Any],
        speed: dict[str, Any] | None = None,
        start_pose: Iterable[float] | None = None,
        plan_id: str = "adhoc",
        func_id: int = 108,
        param_sources: dict[str, str] | None = None,
        position_increment: bool = False,
    ) -> dict[str, Any]:
        pose = self._six_tuple(target_pose)
        l1_plan = {
            "plan_id": plan_id,
            "func_id": int(func_id),
            "action_type": "move",
            "target": {"x": pose[0], "y": pose[1], "z": pose[2]},
            "speed": dict(speed or {}),
        }
        l1 = self.l1_service.run_l1(snapshot, l1_plan)
        items = [dict(item) for item in l1.get("items", [])]
        if l1.get("status") != "pass":
            return self._result(
                safe=False,
                position_ok=False,
                ik_ok=None,
                pose_ok=None,
                blocking_level="L1",
                detail_zh=self._failure_detail("L1安全预判未通过", items),
                suggestion_zh=self._l1_operator_suggestion(items),
                items=items,
                l1=l1,
                l2=None,
                pose_angles=None,
            )

        # L2 inverse-kinematics is not available in this project. Non-strict
        # callers treat that as a soft pass (safe=True); strict callers block.
        detail = "L2逆解预判暂不可用：未配置运动规划服务。"
        return self._result(
            safe=not self.strict_l2,
            position_ok=True,
            ik_ok=None,
            pose_ok=None,
            blocking_level="L2" if self.strict_l2 else None,
            detail_zh=detail,
            suggestion_zh="请接入 FrameTrans2(mode=2) 逆解服务后再执行。" if self.strict_l2 else "需现场确认后再执行。",
            items=items,
            l1=l1,
            l2=None,
            pose_angles=None,
        )

    @staticmethod
    def _result(
        *,
        safe: bool,
        position_ok: bool,
        ik_ok: bool | None,
        pose_ok: bool | None,
        blocking_level: str | None,
        detail_zh: str,
        suggestion_zh: str | None,
        items: list[dict[str, Any]],
        l1: dict[str, Any],
        l2: dict[str, Any] | None,
        pose_angles: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "safe": bool(safe),
            "position_ok": bool(position_ok),
            "ik_ok": ik_ok,
            "pose_ok": pose_ok,
            "blocking_level": blocking_level,
            "detail_zh": detail_zh,
            "suggestion_zh": suggestion_zh,
            "items": items,
            "l1": l1,
            "l2": l2,
            "pose_angles": pose_angles,
            "ik_result": None,
        }

    @staticmethod
    def _failure_detail(prefix: str, items: list[dict[str, Any]]) -> str:
        failed = [
            str(item.get("message") or "").strip()
            for item in items
            if str(item.get("status") or "") == "fail" and str(item.get("message") or "").strip()
        ]
        if not failed:
            return f"{prefix}。"
        return f"{prefix}：{'；'.join(failed[:3])}"

    def _l1_operator_suggestion(self, items: list[dict[str, Any]]) -> str:
        failed_ids = {
            str(item.get("id") or "")
            for item in items
            if str(item.get("status") or "") == "fail"
        }
        config = self.l1_service.config
        suggestions: list[str] = []
        if "target_x_range" in failed_ids:
            suggestions.append(f"将目标 X 调整到软限位 {config.x[0]:.1f}~{config.x[1]:.1f}mm 内")
        if "target_y_range" in failed_ids:
            suggestions.append(f"将目标 Y 调整到软限位 {config.y[0]:.1f}~{config.y[1]:.1f}mm 内")
        if "target_z_range" in failed_ids:
            suggestions.append(f"将目标 Z 调整到软限位 {config.z[0]:.1f}~{config.z[1]:.1f}mm 内")
        if "target_safe_z_range" in failed_ids:
            suggestions.append(f"将目标 Z 调整到安全高度 {config.safe_z_min:.1f}~{config.safe_z_max:.1f}mm 内")
        if "target_r_range" in failed_ids:
            if float(getattr(config, "safe_r_min", 0.0) or 0.0) > 0:
                suggestions.append(
                    f"将目标 X/Y 调整到安全半径 R>={config.safe_r_min:.1f}mm，避免靠近中心盲区"
                )
            if float(getattr(config, "safe_r_max", 0.0) or 0.0) > 0:
                suggestions.append(f"确保目标外径不超过 {config.safe_r_max:.1f}mm")
        if "target_base_angle_range" in failed_ids:
            suggestions.append("调整 X/Y 方向，使底座角度落在 ±160° 内")
        if {"speed_pct", "acc_pct", "dec_pct"} & failed_ids:
            suggestions.append("降低速度/加速度/减速度百分比后重试")
        if {"current_r_range", "current_z_range", "controller", "realtime_feedback"} & failed_ids:
            suggestions.append("先确认控制器在线、实时反馈和当前位姿正确")
        if {"estop", "alarm", "paused", "channel_idle"} & failed_ids:
            suggestions.append("先解除急停/报警/暂停或等待当前任务结束")
        if not suggestions:
            return "请处理失败项后再执行。"
        return "建议：" + "；".join(dict.fromkeys(suggestions)) + "。"

    @staticmethod
    def _six_tuple(values: Iterable[float]) -> tuple[float, float, float, float, float, float]:
        padded = [float(value) for value in list(values)[:6]]
        padded += [0.0] * max(0, 6 - len(padded))
        return tuple(padded[:6])  # type: ignore[return-value]
