"""In-process rate limits for the public endpoints: hospital registration and sign-in.

Kept in memory: a restart clears them, and with several API processes each counts on its own. That is enough for
one coordinator on one machine; a larger deployment would keep these counters in a shared store.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional

from app.utils.errors import RateLimited


class RateLimiter:
    """Sliding-window limit per key, plus an optional global cap so changing addresses cannot flood it."""

    def __init__(self, per_key: int, window_seconds: float, global_limit: Optional[int] = None, clock=time.monotonic,
                 message: str = "Too many requests. Try again later."):
        self.per_key = per_key
        self.global_limit = global_limit
        self.window = window_seconds
        self.message = message
        self._clock = clock
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._all: Deque[float] = deque()
        self._lock = threading.Lock()

    def _trim(self, hits: Deque[float], now: float) -> None:
        while hits and now - hits[0] >= self.window:
            hits.popleft()

    def _full(self, key: str, now: float) -> bool:
        hits = self._hits[key]
        self._trim(hits, now)
        self._trim(self._all, now)
        return len(hits) >= self.per_key or (self.global_limit is not None and len(self._all) >= self.global_limit)

    def check(self, key: str) -> None:
        """Count one request for ``key``; raise RateLimited if the limit is already reached."""
        with self._lock:
            now = self._clock()
            if self._full(key, now):
                raise RateLimited(self.message)
            self._hits[key].append(now)
            self._all.append(now)

    def ensure_open(self, key: str) -> None:
        """Raise RateLimited if ``key`` is at its limit, without counting a request."""
        with self._lock:
            if self._full(key, self._clock()):
                raise RateLimited(self.message)

    def record(self, key: str) -> None:
        """Count one event (for example a failed sign-in) without checking."""
        with self._lock:
            now = self._clock()
            self._hits[key].append(now)
            self._all.append(now)
