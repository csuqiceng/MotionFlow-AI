"""Public, vendor-neutral mechanical-arm platform package."""

from .execution import PendingPlanStore, SessionGateStore
from .flow import FlowEntry, FlowRegistry, FlowStep, VersionedFlowRegistry
from .flow.execution_history import ExecutionHistory
from .flow.execution_registry import LibraryExecutionRegistry
from .library.auth import LoginThrottle, UserSessionStore, hash_password, verify_password
from .library.catalog import ComponentCatalog
from .library.migration import (
    _audit_append, ensure_audit_chain, initialize_robot_libraries,
    verify_audit_chain,
)
from .library.models import normalize_id
from .library.transfer import apply_transfer_payload, build_transfer_payload
from .library.users import LastEngineerError, UserRegistry, initialize_user_identity
from .library.versioned_registry import ConflictError, VersionedCommandRegistry
from .platform import RobotPlatform
from .positions.cleanup import backup_and_apply, build_cleanup_plan, classify_temporary
from .runtime import configure_robot_runtime, get_robot_data_dir

__all__ = [
    "ComponentCatalog", "ConflictError", "ExecutionHistory", "FlowEntry", "FlowRegistry",
    "FlowStep", "LastEngineerError", "LibraryExecutionRegistry", "LoginThrottle",
    "PendingPlanStore", "RobotPlatform", "SessionGateStore", "UserRegistry",
    "UserSessionStore", "VersionedCommandRegistry", "VersionedFlowRegistry", "_audit_append",
    "ensure_audit_chain", "verify_audit_chain",
    "apply_transfer_payload", "backup_and_apply",
    "build_cleanup_plan", "build_transfer_payload", "classify_temporary",
    "configure_robot_runtime", "get_robot_data_dir", "hash_password", "initialize_robot_libraries",
    "initialize_user_identity", "normalize_id", "verify_password",
]
