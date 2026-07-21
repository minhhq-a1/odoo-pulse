# odoo_pulse/core/cache.py
"""Process-local TTL + LRU cache. No background threads; lazy expiry on access."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any


class TTLCache:
    """Bounded cache with per-entry TTL and least-recently-used eviction.

    ttl <= 0 disables caching (every ``get`` misses). Entries expire lazily:
    an expired entry is dropped the next time it is read. Thread-safe.
    """

    def __init__(self, ttl: float, max_entries: int) -> None:
        self.ttl = ttl
        self.max_entries = max_entries
        self._store: OrderedDict[Any, tuple[Any, float]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: Any) -> Any | None:
        if self.ttl <= 0:
            return None
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if expires_at < time.monotonic():
                del self._store[key]
                return None
            self._store.move_to_end(key)
            return value

    def set(self, key: Any, value: Any) -> None:
        if self.max_entries <= 0:
            return
        with self._lock:
            self._store[key] = (value, time.monotonic() + self.ttl)
            self._store.move_to_end(key)
            while len(self._store) > self.max_entries:
                self._store.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
