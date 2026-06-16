import threading

from redis_to_aerospike.stats import MigrationStats


def test_basic_counting():
    stats = MigrationStats()
    stats.record_scanned()
    stats.record_migrated()
    stats.record_skipped("stream")
    stats.record_error("write:TimeoutError")
    assert stats.scanned == 1
    assert stats.migrated == 1
    assert stats.skipped == 1
    assert stats.errors == 1
    assert stats.skipped_by_type == {"stream": 1}
    assert stats.errors_by_type == {"write:TimeoutError": 1}


def test_thread_safe_counting():
    stats = MigrationStats()
    iterations = 5000
    threads = 8

    def work():
        for _ in range(iterations):
            stats.record_migrated()

    workers = [threading.Thread(target=work) for _ in range(threads)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()

    assert stats.migrated == iterations * threads


def test_summary_contains_counts():
    stats = MigrationStats()
    stats.start()
    stats.record_migrated()
    stats.finish()
    summary = stats.summary()
    assert "migrated=1" in summary
    assert "throughput=" in summary


def test_format_report_includes_counters_and_breakdowns():
    stats = MigrationStats()
    stats.start()
    stats.record_scanned()
    stats.record_migrated()
    stats.record_skipped("stream")
    stats.record_error("write:TimeoutError")
    stats.finish()

    report = stats.format_report()
    assert "migration summary" in report
    assert "migrated   : 1" in report
    assert "skipped by type:" in report
    assert "- stream: 1" in report
    assert "errors by type:" in report
    assert "- write:TimeoutError: 1" in report


def test_format_report_omits_empty_breakdowns():
    stats = MigrationStats()
    stats.record_migrated()
    report = stats.format_report()
    assert "skipped by type:" not in report
    assert "errors by type:" not in report


def test_progress_line_is_compact_snapshot():
    stats = MigrationStats()
    stats.start()
    stats.record_migrated()
    line = stats.progress_line()
    assert line.startswith("progress:")
    assert "migrated=1" in line
