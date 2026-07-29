"""Process-local transaction coordination for file-backed robot libraries."""

from __future__ import annotations

import secrets
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Iterator, ParamSpec, TypeVar

_locks_guard = RLock()
_locks: dict[Path, RLock] = {}
P = ParamSpec("P")
R = TypeVar("R")


def _lock_for(data_dir: str | Path) -> tuple[Path, RLock]:
    root = Path(data_dir).resolve()
    with _locks_guard:
        return root, _locks.setdefault(root, RLock())


@contextmanager
def library_transaction(
    data_dir: str | Path,
    *,
    rollback_files: tuple[str, ...] = (),
) -> Iterator[None]:
    """Serialize one library operation and optionally restore file preimages."""
    root, lock = _lock_for(data_dir)
    with lock:
        transaction_id = secrets.token_urlsafe(16) if rollback_files else None
        snapshots = {
            root / name: (root / name).read_bytes() if (root / name).is_file() else None
            for name in rollback_files
            if Path(name).suffix != ".jsonl"
        }
        try:
            yield
        except BaseException as exc:
            for path, content in snapshots.items():
                if content is None:
                    path.unlink(missing_ok=True)
                    continue
                rollback = path.with_name(
                    f".{path.name}.{secrets.token_hex(8)}.rollback",
                )
                rollback.write_bytes(content)
                rollback.replace(path)
            if transaction_id is not None:
                from robot_platform.library.migration import _audit_append

                _audit_append(root / "audit.jsonl", {
                    "action": "library_transaction_rollback",
                    "actor": "system:library-transaction",
                    "result": "compensated",
                    "transaction_id": transaction_id,
                    "rolled_back_files": [path.name for path in snapshots],
                    "failure_type": type(exc).__name__,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            raise


def synchronized_library_method(
    method: Callable[P, R],
) -> Callable[P, R]:
    """Run an adapter/service method under its ``_data_dir`` transaction lock."""
    @wraps(method)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        owner: Any = args[0]
        with library_transaction(owner._data_dir):
            return method(*args, **kwargs)

    return wrapped
