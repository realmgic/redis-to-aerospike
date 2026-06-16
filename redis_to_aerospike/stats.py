"""Thread-safe aggregation of migration progress."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class MigrationStats:
    """Counts and timing for a migration run. Safe to update from many threads."""

    scanned: int = 0
    migrated: int = 0
    skipped: int = 0
    errors: int = 0
    # skip/error breakdown keyed by reason/type for quick diagnostics.
    skipped_by_type: Dict[str, int] = field(default_factory=dict)
    errors_by_type: Dict[str, int] = field(default_factory=dict)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def start(self) -> None:
        with self._lock:
            self.started_at = time.monotonic()

    def finish(self) -> None:
        with self._lock:
            self.finished_at = time.monotonic()

    def record_scanned(self, n: int = 1) -> None:
        with self._lock:
            self.scanned += n

    def record_migrated(self, n: int = 1) -> None:
        with self._lock:
            self.migrated += n

    def record_skipped(self, reason: str) -> None:
        with self._lock:
            self.skipped += 1
            self.skipped_by_type[reason] = self.skipped_by_type.get(reason, 0) + 1

    def record_error(self, reason: str) -> None:
        with self._lock:
            self.errors += 1
            self.errors_by_type[reason] = self.errors_by_type.get(reason, 0) + 1

    @property
    def elapsed_s(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.finished_at if self.finished_at is not None else time.monotonic()
        return max(0.0, end - self.started_at)

    @property
    def throughput(self) -> float:
        elapsed = self.elapsed_s
        return self.migrated / elapsed if elapsed > 0 else 0.0

    def summary(self) -> str:
        return (
            f"scanned={self.scanned} migrated={self.migrated} "
            f"skipped={self.skipped} errors={self.errors} "
            f"elapsed={self.elapsed_s:.2f}s throughput={self.throughput:.0f}/s"
        )

    def progress_line(self) -> str:
        """A compact one-line snapshot for the periodic progress heartbeat."""
        with self._lock:
            scanned, migrated = self.scanned, self.migrated
            skipped, errors = self.skipped, self.errors
        return (
            f"progress: scanned={scanned} migrated={migrated} "
            f"skipped={skipped} errors={errors} throughput={self.throughput:.0f}/s"
        )

    def format_report(self) -> str:
        """A multi-line, human-readable end-of-run report.

        Includes the high-level counters and timing plus the skip/error
        breakdowns (only when non-empty), so a user can see at a glance both
        *what happened* and *why* records were skipped or failed.
        """
        with self._lock:
            scanned, migrated = self.scanned, self.migrated
            skipped, errors = self.skipped, self.errors
            skipped_by_type = dict(self.skipped_by_type)
            errors_by_type = dict(self.errors_by_type)

        lines = [
            "migration summary",
            f"  scanned    : {scanned}",
            f"  migrated   : {migrated}",
            f"  skipped    : {skipped}",
            f"  errors     : {errors}",
            f"  elapsed    : {self.elapsed_s:.2f}s",
            f"  throughput : {self.throughput:.0f} records/s",
        ]
        if skipped_by_type:
            lines.append("  skipped by type:")
            for reason, count in sorted(skipped_by_type.items()):
                lines.append(f"    - {reason}: {count}")
        if errors_by_type:
            lines.append("  errors by type:")
            for reason, count in sorted(errors_by_type.items()):
                lines.append(f"    - {reason}: {count}")
        return "\n".join(lines)
