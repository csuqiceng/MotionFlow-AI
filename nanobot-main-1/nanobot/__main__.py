"""Compatibility module entry point for the robot-control server.

New deployments should use ``robot-server``.  Keeping ``python -m nanobot``
as a thin alias avoids accidentally reviving the removed chat CLI while older
desktop launchers are migrated.
"""

from robot_server.cli import main


if __name__ == "__main__":
    main()
