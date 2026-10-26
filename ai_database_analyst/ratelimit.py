"""Sliding-window rate limiter (in memory, per process)."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable


class RateLimiter:
    """Allow at most ``max_events`` per ``window_s`` seconds for each key."""

    def __init__(self, max_events: int, window_s: float = 60.0, clock: Callable[[], float] = time.monotonic) -> None:
        if max_events < 1:
            raise ValueError("max_events must be at least 1")
        self._max = max_events
        self._window = window_s
        self._clock = clock
        self._events: dict = {}
        self._lock = threading.Lock()

    def acquire(self, key: str) -> float:
        """Record an event. Returns 0.0 if allowed, else seconds until a slot frees up."""
        now = self._clock()
        with self._lock:
            events = self._events.setdefault(key, deque())
            while events and now - events[0] >= self._window:
                events.popleft()
            if len(events) >= self._max:
                return max(0.001, self._window - (now - events[0]))
            events.append(now)
            return 0.0
