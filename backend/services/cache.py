"""Tiny TTL cache. Replace with Redis once we outgrow a single process."""

import time
from threading import Lock
from typing import Any


class TTLCache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at < time.monotonic():
                self._store.pop(key, None)
                return None
            return value

    def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        with self._lock:
            self._store[key] = (time.monotonic() + ttl_seconds, value)

    def sweep(self) -> int:
        """Drop every expired entry; returns the count removed.

        Expiry otherwise only happens on a get() of the SAME key, so
        date-rotated keys (bars:{sym}:{tf}:{date}, has_0dte:{sym}:{date}, …)
        become unreachable garbage at the day roll and accumulate for the
        life of the process — bar lists being the heavy case. A scheduler
        job calls this periodically.
        """
        now = time.monotonic()
        with self._lock:
            dead = [k for k, (expires_at, _) in self._store.items() if expires_at < now]
            for k in dead:
                self._store.pop(k, None)
            return len(dead)


cache = TTLCache()
