"""Thin PyInstaller entry: forward to ``nanobot gateway --foreground``.

The gateway is a Typer subcommand (``pyproject.toml`` defines
``nanobot = nanobot.cli.commands:app``), so a single-file launcher must invoke
the Typer ``app`` object directly rather than re-entering the console script.

``--foreground`` runs the HTTP/WebSocket server in-process (see
``nanobot/cli/gateway.py``) instead of spawning a competing daemon that would
write its own ``run/gateway.json`` state file. ``--verbose`` surfaces boot
diagnostics that the Electron supervisor captures to ``logs/gateway.log``.

Extra ``sys.argv`` is forwarded verbatim, so the Electron shell can pass
``--config`` and ``--port``.
"""

from __future__ import annotations

import sys


def main() -> None:
    from nanobot.cli.commands import app

    argv = ["gateway", "--foreground", "--verbose", *sys.argv[1:]]
    # standalone_mode=False so a Typer error raises instead of calling sys.exit
    # with a printed usage block — keeps the supervisor's restart/retry logic sane.
    app(argv, standalone_mode=False)


if __name__ == "__main__":
    main()
