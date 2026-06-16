"""Tests for the periodic progress heartbeat."""

import logging

from redis_to_aerospike.progress import ProgressReporter
from redis_to_aerospike.stats import MigrationStats


def test_disabled_when_interval_is_zero():
    reporter = ProgressReporter(MigrationStats(), interval=0)
    assert reporter.enabled is False
    reporter.start()  # no-op
    reporter.stop()


def test_emits_at_least_one_line_then_stops(caplog):
    stats = MigrationStats()
    stats.start()
    stats.record_migrated()

    log = logging.getLogger("test.progress")
    reporter = ProgressReporter(stats, interval=0.01, log=log)

    with caplog.at_level(logging.INFO, logger="test.progress"):
        with reporter:
            # Give the heartbeat thread time to tick at least once.
            import time

            time.sleep(0.05)

    messages = [r.message for r in caplog.records]
    assert any("progress:" in m for m in messages)
    # The thread is joined on exit, so it is no longer running.
    assert reporter._thread is None


def test_context_manager_stops_cleanly_without_ticking():
    stats = MigrationStats()
    # A long interval means no tick fires before we exit; stop() must not block.
    with ProgressReporter(stats, interval=1000):
        pass
