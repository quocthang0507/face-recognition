"""In-process change counters used to invalidate hot-path caches.

The camera pipeline keeps the student gallery and the active lesson in memory
instead of querying SQLite on every frame. Services bump these counters when
the underlying data changes; caches also expire after a short TTL so that a
second worker process cannot serve stale data for long.
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_versions = {"students": 0, "sessions": 0}


def bump(name: str) -> None:
    """Mark one cached data set as changed."""

    with _lock:
        _versions[name] += 1


def version(name: str) -> int:
    """Return the current change counter of a cached data set."""

    return _versions[name]
