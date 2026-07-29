"""Durable emergency-stop audit outbox with a preallocated mmap spool."""

from __future__ import annotations

import json
import mmap
import os
import struct
import threading
from pathlib import Path
from typing import Any


_HEADER = struct.Struct("<QQQ")
_LENGTH = struct.Struct("<I")
_LEASES_GUARD = threading.Lock()
_LEASED_SPOOLS: set[str] = set()


class EmergencyStopAuditOutbox:
    """At-least-once spool: request threads only copy into preallocated memory."""

    def __init__(
        self, path: str | Path, *, capacity: int = 2048, slot_size: int = 2048,
    ) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._spool_path = self._path.with_suffix(self._path.suffix + ".spool")
        self._lease_key = str(self._spool_path.resolve()).casefold()
        with _LEASES_GUARD:
            if self._lease_key in _LEASED_SPOOLS:
                raise RuntimeError(
                    f"emergency-stop audit spool is already open: {self._spool_path}"
                )
            _LEASED_SPOOLS.add(self._lease_key)
        self._capacity = max(8, int(capacity))
        self._slot_size = max(512, int(slot_size))
        self._lock = threading.Lock()
        self._flush_lock = threading.Lock()
        size = _HEADER.size + self._capacity * self._slot_size
        try:
            self._stream = self._spool_path.open("a+b")
            resized = self._stream.seek(0, os.SEEK_END) != size
            if resized:
                self._stream.truncate(size)
                self._stream.flush()
            self._map = mmap.mmap(self._stream.fileno(), size)
            if resized:
                write_seq = read_seq = overflow = 0
                self._map[:_HEADER.size] = _HEADER.pack(0, 0, 0)
            else:
                write_seq, read_seq, overflow = _HEADER.unpack(
                    self._map[:_HEADER.size]
                )
            if read_seq > write_seq or write_seq - read_seq > self._capacity:
                write_seq = read_seq = overflow = 0
                self._map[:_HEADER.size] = _HEADER.pack(0, 0, 0)
            self._write_seq = int(write_seq)
            self._read_seq = int(read_seq)
            self._overflow_count = int(overflow)
            self._closed = False
        except BaseException:
            mapped = getattr(self, "_map", None)
            if mapped is not None:
                mapped.close()
            stream = getattr(self, "_stream", None)
            if stream is not None:
                stream.close()
            with _LEASES_GUARD:
                _LEASED_SPOOLS.discard(self._lease_key)
            raise

    def spool(self, event: dict[str, Any]) -> bool:
        encoded = json.dumps(
            event, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > self._slot_size - _LENGTH.size:
            with self._lock:
                if not self._closed:
                    self._overflow_count += 1
                    self._write_header_locked()
            return False
        with self._lock:
            if self._closed:
                return False
            if self._write_seq - self._read_seq >= self._capacity:
                self._overflow_count += 1
                self._write_header_locked()
                return False
            offset = self._slot_offset(self._write_seq)
            self._map[offset:offset + _LENGTH.size] = _LENGTH.pack(len(encoded))
            start = offset + _LENGTH.size
            self._map[start:start + len(encoded)] = encoded
            self._write_seq += 1
            self._write_header_locked()
            return True

    def flush_spool(self) -> int:
        with self._flush_lock:
            return self._flush_spool_locked()

    def _flush_spool_locked(self) -> int:
        flushed = 0
        while True:
            with self._lock:
                if self._closed:
                    return flushed
                if self._read_seq >= self._write_seq:
                    overflow = self._overflow_count
                    if overflow == 0:
                        return flushed
                    overflow_event = {
                        "event": "emergency_stop_audit_overflow",
                        "dropped_event_count": overflow,
                    }
                    sequence = None
                else:
                    overflow_event = None
                    sequence = self._read_seq
                if overflow_event is not None:
                    encoded = None
                else:
                    assert sequence is not None
                    offset = self._slot_offset(sequence)
                    length = _LENGTH.unpack(
                        self._map[offset:offset + _LENGTH.size]
                    )[0]
                    if length <= 0 or length > self._slot_size - _LENGTH.size:
                        raise ValueError("emergency-stop audit spool is corrupt")
                    start = offset + _LENGTH.size
                    encoded = bytes(self._map[start:start + length])
            # Durable JSONL I/O happens only on the background worker.
            event = (
                overflow_event
                if overflow_event is not None
                else json.loads(encoded.decode("utf-8"))
            )
            self.append(event)
            with self._lock:
                if overflow_event is not None:
                    self._overflow_count = max(0, self._overflow_count - overflow)
                    self._write_header_locked()
                    flushed += 1
                elif self._read_seq == sequence:
                    self._read_seq += 1
                    self._write_header_locked()
                    flushed += 1

    def append(self, event: dict[str, Any]) -> None:
        encoded = json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
        with self._path.open("a", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())

    def close(self) -> None:
        with self._flush_lock:
            with self._lock:
                if self._closed:
                    return
                self._closed = True
                self._map.flush()
                self._map.close()
                self._stream.close()
                with _LEASES_GUARD:
                    _LEASED_SPOOLS.discard(self._lease_key)

    @property
    def overflow_count(self) -> int:
        with self._lock:
            return self._overflow_count

    def _write_header_locked(self) -> None:
        self._map[:_HEADER.size] = _HEADER.pack(
            self._write_seq, self._read_seq, self._overflow_count,
        )

    def _slot_offset(self, sequence: int) -> int:
        return _HEADER.size + (sequence % self._capacity) * self._slot_size
