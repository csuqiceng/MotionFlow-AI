"""PyInstaller entry point for the standalone robot server."""

import sys
from pathlib import Path


# The build virtualenv may carry an editable checkout of another worktree.
# Keep the current checkout first so this artefact always packages the source
# selected by the release command.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from robot_server.cli import main


if __name__ == "__main__":
    main()
