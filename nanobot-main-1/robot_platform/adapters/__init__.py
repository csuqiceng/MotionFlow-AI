"""Concrete product adapters selected only by composition roots."""

from .flow import FileRobotFlowAdapter
from .flow_management import FileFlowManagementAdapter
from .library_maintenance import (
    FileLibraryTransferAdapter,
    FilePositionMaintenanceAdapter,
)
from .library_management import FileCommandLibraryManagementAdapter
from .knowledge import FileRobotKnowledgeAdapter
from .position_library import FileRobotPositionLibraryAdapter

__all__ = [
    "FileCommandLibraryManagementAdapter", "FileFlowManagementAdapter",
    "FileLibraryTransferAdapter",
    "FileRobotKnowledgeAdapter",
    "FilePositionMaintenanceAdapter", "FileRobotFlowAdapter",
    "FileRobotPositionLibraryAdapter",
]
