"""A low-overhead, periodic progress heartbeat for a running migration.

The reporter runs on a single daemon thread that wakes every ``interval``
seconds and logs one snapshot line from :class:`MigrationStats`. It deliberately
does *not* log per record: at high throughput that would both spam the console
and add measurable overhead. Sleeping via :class:`threading.Event` lets the
thread stop promptly when the run finishes instead of waiting out the interval.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from .stats import MigrationStats

logger = logging.getLogger(__name__)


class ProgressReporter:
    """Periodically logs a one-line snapshot of migration progress."""

    def __init__(
        self,
        stats: MigrationStats,
        interval: float = 5.0,
        log: Optional[logging.Logger] = None,
    ):
        self._stats = stats
        self._interval = interval
        self._logger = log or logger
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def enabled(self) -> bool:
        return self._interval > 0

    def start(self) -> "ProgressReporter":
        if not self.enabled or self._thread is not None:
            return self
        self._thread = threading.Thread(
            target=self._run, name="migrator-progress", daemon=True
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None

    def __enter__(self) -> "ProgressReporter":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    def _run(self) -> None:
        # Event.wait returns True once stop() is called, so the loop exits
        # immediately on shutdown rather than sleeping out the final interval.
        while not self._stop.wait(self._interval):
            self._logger.info("%s", self._stats.progress_line())
