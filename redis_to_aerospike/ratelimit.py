"""A small, thread-safe token-bucket rate limiter.

Used to optionally throttle the migration's two hot paths so neither side is
overwhelmed: the Redis SCAN (producer) and the Aerospike inserts (workers).

The write limiter is shared by every worker thread, so :class:`TokenBucket`
must be safe under concurrency. Tokens are refilled lazily against a monotonic
clock; an :meth:`acquire` that cannot be satisfied immediately reserves the
tokens (the balance may go negative) and sleeps *outside* the lock, so
concurrent callers pipeline their waits and the aggregate rate stays correct.
"""

from __future__ import annotations

import threading
import time
from typing import Optional


class TokenBucket:
    """A token bucket allowing up to ``capacity`` burst at ``rate`` tokens/sec.

    A ``rate <= 0`` produces a disabled bucket whose :meth:`acquire` is a no-op,
    so callers can construct one unconditionally and let configuration decide
    whether any throttling happens.
    """

    def __init__(self, rate: float, capacity: Optional[float] = None):
        self.rate = rate
        self.enabled = self.rate > 0
        # Default the burst to one second's worth of rate.
        self.capacity = capacity if capacity is not None else self.rate
        self._tokens = self.capacity
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, tokens: float = 1.0) -> None:
        """Block until ``tokens`` are available, then consume them.

        Returns immediately when the bucket is disabled or no wait is needed.
        """
        if not self.enabled:
            return

        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._last = now
            # Refill, capping at capacity so idle time can't build infinite burst.
            self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)

            if self._tokens >= tokens:
                wait = 0.0
            else:
                wait = (tokens - self._tokens) / self.rate
            # Reserve the tokens now (balance may go negative); the next caller
            # refills from this deficit, so the aggregate rate is preserved even
            # though we sleep outside the lock.
            self._tokens -= tokens

        if wait > 0:
            time.sleep(wait)
