"""PyInstaller entry point for the standalone robot server."""

import sys
from pathlib import Path


# The build virtualenv may carry an editable checkout of another worktree.
# Keep the current checkout first so this artefact always packages the source
# selected by the release command.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from robot_server.cli import main


def _verify_pybullet_runtime() -> None:
    """Import and start the bundled optional runtime without composing a robot."""
    import pybullet

    client = pybullet.connect(pybullet.DIRECT)
    if client < 0:
        raise RuntimeError("pybullet_direct_start_failed")
    try:
        pybullet.stepSimulation(physicsClientId=client)
    finally:
        pybullet.disconnect(physicsClientId=client)
    print("packaged_pybullet_direct_ok")


if __name__ == "__main__":
    if "--verify-pybullet-runtime" in sys.argv:
        _verify_pybullet_runtime()
        raise SystemExit(0)
    main()
