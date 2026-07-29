"""Static, reviewed Tool manifests for the robot desktop product."""

from ai_runtime.tool_manifest import ToolManifest

PRODUCT_TOOL_MANIFESTS = (
    ToolManifest(
        "robot_arm", "2.0.0", required_capabilities=("state_read",),
        risk_level="motion", timeout_seconds=60, concurrency="exclusive",
        resources=("robot-controller",), audit_policy="required", idempotency="request",
    ),
    ToolManifest(
        "robot_flow", "2.0.0", required_capabilities=("state_read",),
        risk_level="motion", timeout_seconds=120, concurrency="exclusive",
        resources=("robot-controller", "flow-runtime"), audit_policy="required",
        idempotency="request",
    ),
    ToolManifest("robot_knowledge", "2.0.0", timeout_seconds=15,
                 audit_policy="required", idempotency="request"),
    ToolManifest("robot_position", "2.0.0", timeout_seconds=15,
                 audit_policy="required", idempotency="request"),
    ToolManifest(
        "robot_library", "2.0.0", risk_level="system", timeout_seconds=30,
        concurrency="exclusive", resources=("robot-library",), audit_policy="required",
        idempotency="request",
    ),
    ToolManifest(
        "cron", "2.0.0", risk_level="system", timeout_seconds=30,
        concurrency="exclusive", resources=("scheduler",), audit_policy="required",
        idempotency="request",
    ),
)

PRODUCT_TOOL_MANIFESTS_BY_ID = {
    manifest.tool_id: manifest for manifest in PRODUCT_TOOL_MANIFESTS
}
