# 已知运行时问题

## 控制器恢复后仍被未结算执行许可阻止

**现象（2026-07-31）**：现场 ZMotion 下位机已确认恢复为 `idle`、无报警、`cancel_latch=false`，但新的真实运动和系统动作在签发执行许可时被拒绝：

```text
controller has an unresolved execution; reconcile operation
'robot-operation:e04504f86c41df94' before issuing another permit
```

**已确认的边界**：这不是控制器仍在报警，也不能通过 `release_cancel` 或空闲状态下的 `stop_current` 清除。前者只处理控制器取消锁存，后者在 `idle` 时应被拒绝。

**风险与处理原则**：遗留许可用于避免通信结果不确定时重复下发真实运动；不得通过删除许可文件、重启服务或绕过许可检查来恢复。应在重新读取并确认下位机实际状态后，提供仅限认证操作员的受控 reconciliation/结算流程，并留下审计记录。

**待办**：梳理 Qt 参考工程及当前 WebUI/服务端到下位机的状态、急停、报警复位和许可状态机，确定恢复流程差异后再设计修复与回归测试。
