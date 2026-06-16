"""Tests for the token-bucket rate limiter."""

import threading
import time

from redis_to_aerospike.ratelimit import TokenBucket


def test_disabled_bucket_is_passthrough():
    bucket = TokenBucket(0)
    assert bucket.enabled is False
    start = time.monotonic()
    for _ in range(1000):
        bucket.acquire()
    # No throttling at all, so this is effectively instant.
    assert time.monotonic() - start < 0.1


def test_negative_rate_is_disabled():
    assert TokenBucket(-5).enabled is False


def test_initial_burst_is_not_throttled():
    # capacity defaults to the rate (one second's worth), so the first
    # `capacity` tokens are served without waiting.
    bucket = TokenBucket(rate=100, capacity=10)
    start = time.monotonic()
    for _ in range(10):
        bucket.acquire()
    assert time.monotonic() - start < 0.05


def test_enforces_rate_after_burst():
    # Drain the burst, then 5 more tokens at 100/s must take ~>= 0.05s.
    rate = 100.0
    capacity = 5.0
    bucket = TokenBucket(rate=rate, capacity=capacity)
    total_tokens = 10
    start = time.monotonic()
    for _ in range(total_tokens):
        bucket.acquire()
    elapsed = time.monotonic() - start
    expected_min = (total_tokens - capacity) / rate
    # Generous lower bound to avoid flakiness while still proving throttling.
    assert elapsed >= expected_min * 0.8


def test_concurrent_acquires_respect_aggregate_rate():
    rate = 50.0
    capacity = 5.0
    bucket = TokenBucket(rate=rate, capacity=capacity)
    per_thread = 10
    threads = 4
    total = per_thread * threads

    def worker():
        for _ in range(per_thread):
            bucket.acquire()

    start = time.monotonic()
    workers = [threading.Thread(target=worker) for _ in range(threads)]
    for t in workers:
        t.start()
    for t in workers:
        t.join()
    elapsed = time.monotonic() - start

    expected_min = (total - capacity) / rate
    assert elapsed >= expected_min * 0.8
