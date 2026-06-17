"""End-to-end migration against real Redis and Aerospike containers."""

from __future__ import annotations

import pytest

from migration_helpers import (
    SET_NAME,
    aerospike_reader,
    build_migration_config,
    run_migration,
)

from redis_to_aerospike.config import HashStrategy, RecordExistsPolicy, TtlOverflowPolicy

pytestmark = pytest.mark.integration


def test_full_migration(redis_client, redis_container, aerospike_container):
    redis_client.set("num", "42")
    redis_client.set("greeting", "hello")
    redis_client.hset("user:1", mapping={"name": "alice", "age": "30"})
    redis_client.rpush("mylist", "a", "b", "c")
    redis_client.sadd("myset", "x", "y", "z", "x")
    redis_client.zadd("myzset", {"alice": 1, "bob": 2})
    redis_client.set("temp", "soon", ex=1000)
    expected_keys = 7  # data-driven below, kept explicit for clarity

    config = build_migration_config(redis_container, aerospike_container)
    stats = run_migration(config)

    assert stats.errors == 0
    assert stats.migrated == expected_keys

    client = aerospike_reader(config)
    try:
        ns = config.aerospike.namespace

        def bins(key):
            _, _, b = client.get((ns, SET_NAME, key))
            return b

        assert bins("num")["value"] == 42 and isinstance(bins("num")["value"], int)
        assert bins("greeting")["value"] == "hello"
        assert bins("user:1")["value"] == {"name": "alice", "age": 30}
        assert bins("mylist")["value"] == ["a", "b", "c"]
        assert sorted(bins("myset")["value"]) == ["x", "y", "z"]
        assert bins("myzset")["value"] == {"alice": 1.0, "bob": 2.0}

        _, meta, _ = client.get((ns, SET_NAME, "temp"))
        assert 0 < meta["ttl"] <= 1000
    finally:
        client.close()


def test_never_expire_key_reads_back_as_no_expiry(redis_client, redis_container, aerospike_container):
    redis_client.set("forever", "v")  # no TTL
    config = build_migration_config(redis_container, aerospike_container)
    run_migration(config)

    client = aerospike_reader(config)
    try:
        _, meta, _ = client.get((config.aerospike.namespace, SET_NAME, "forever"))
        # Never-expire reads back as -1 (signed) or 0xFFFFFFFF depending on client.
        assert meta["ttl"] in (-1, 0xFFFFFFFF)
    finally:
        client.close()


def test_ttl_over_max_is_rejected_by_default(redis_client, redis_container, aerospike_container):
    # Keys are unique per test: Aerospike is session-scoped and not flushed between tests,
    # while Redis is flushed per test — another test may have written the same Aerospike key.
    redis_client.set("ok_ttl_reject", "v", ex=50)
    redis_client.set("bad_ttl_reject", "v", ex=1000)
    config = build_migration_config(redis_container, aerospike_container)
    # Use a small max-ttl so we exercise the boundary without depending on the
    # container's namespace max-ttl.
    config.aerospike.max_ttl = 100

    stats = run_migration(config)

    assert "convert:TtlTooLongError" in stats.errors_by_type
    client = aerospike_reader(config)
    try:
        ns = config.aerospike.namespace
        _, meta, _ = client.get((ns, SET_NAME, "ok_ttl_reject"))
        assert 0 < meta["ttl"] <= 100
        # The over-limit key was rejected before any write.
        _, meta = client.exists((ns, SET_NAME, "bad_ttl_reject"))
        assert meta is None
    finally:
        client.close()


def test_ttl_over_max_is_clamped_when_configured(redis_client, redis_container, aerospike_container):
    redis_client.set("bad_ttl_clamp", "v", ex=1000)
    config = build_migration_config(redis_container, aerospike_container)
    config.aerospike.max_ttl = 100
    config.ttl_overflow_policy = TtlOverflowPolicy.CLAMP

    stats = run_migration(config)

    assert stats.errors == 0
    client = aerospike_reader(config)
    try:
        _, meta, _ = client.get((config.aerospike.namespace, SET_NAME, "bad_ttl_clamp"))
        assert 0 < meta["ttl"] <= 100
    finally:
        client.close()


def test_binary_key_and_value_roundtrip(redis_client, redis_container, aerospike_container):
    bin_key = b"\xff\x01\x02key"
    blob = b"\x00\xff\x10\x00"
    redis_client.set(bin_key, blob)

    config = build_migration_config(redis_container, aerospike_container)
    stats = run_migration(config)
    assert stats.errors == 0

    client = aerospike_reader(config)
    try:
        _, _, b = client.get((config.aerospike.namespace, SET_NAME, bin_key))
        assert bytes(b["value"]) == blob
    finally:
        client.close()


def test_numeric_set_members_preserved_distinctly(redis_client, redis_container, aerospike_container):
    redis_client.sadd("nums", "1", "1.0", "2")
    config = build_migration_config(redis_container, aerospike_container)
    assert run_migration(config).errors == 0

    client = aerospike_reader(config)
    try:
        _, _, b = client.get((config.aerospike.namespace, SET_NAME, "nums"))
        assert sorted(b["value"]) == ["1", "1.0", "2"]
    finally:
        client.close()


def test_zset_float_member_and_inf_score(redis_client, redis_container, aerospike_container):
    redis_client.zadd("zedge", {"1.5": 2.0, "big": float("inf")})
    config = build_migration_config(redis_container, aerospike_container)
    assert run_migration(config).errors == 0

    client = aerospike_reader(config)
    try:
        _, _, b = client.get((config.aerospike.namespace, SET_NAME, "zedge"))
        assert b["value"] == {"1.5": 2.0, "big": "inf"}
    finally:
        client.close()


def test_unsupported_type_is_skipped(redis_client, redis_container, aerospike_container):
    redis_client.xadd("events", {"f": "v"})
    config = build_migration_config(redis_container, aerospike_container)
    stats = run_migration(config)

    assert stats.skipped == 1
    assert stats.skipped_by_type == {"stream": 1}
    assert stats.migrated == 0


def test_oversized_value_is_rejected_gracefully(redis_client, redis_container, aerospike_container):
    redis_client.set("small", "ok")
    redis_client.set("huge", "x" * (9 * 1024 * 1024))  # 9 MB, over the 8 MiB limit
    config = build_migration_config(redis_container, aerospike_container)

    stats = run_migration(config)

    assert stats.scanned == 2
    assert stats.migrated == 1  # only the small key
    assert stats.errors == 1
    assert "write:RecordTooLargeError" in stats.errors_by_type

    client = aerospike_reader(config)
    try:
        assert client.get((config.aerospike.namespace, SET_NAME, "small"))[2]["value"] == "ok"
        # The oversized record was never written.
        _, meta = client.exists((config.aerospike.namespace, SET_NAME, "huge"))
        assert meta is None
    finally:
        client.close()


def test_field_bins_strategy_and_long_name_failure(redis_client, redis_container, aerospike_container):
    redis_client.hset("acct", mapping={"name": "bob", "age": "42"})
    redis_client.hset("bad", mapping={"this_field_name_is_way_too_long": "1"})

    config = build_migration_config(redis_container, aerospike_container, strategy=HashStrategy.FIELD_BINS)
    stats = run_migration(config)

    # The valid hash migrates to per-field bins; the long-field hash errors.
    assert stats.migrated == 1
    assert stats.errors == 1

    client = aerospike_reader(config)
    try:
        _, _, b = client.get((config.aerospike.namespace, SET_NAME, "acct"))
        assert b == {"name": "bob", "age": 42}
    finally:
        client.close()


def test_set_uniqueness_is_idempotent(redis_client, redis_container, aerospike_container):
    redis_client.sadd("dups", "a", "b", "c")
    config = build_migration_config(redis_container, aerospike_container)

    run_migration(config)
    run_migration(config)  # second pass must not duplicate members

    client = aerospike_reader(config)
    try:
        _, _, b = client.get((config.aerospike.namespace, SET_NAME, "dups"))
        assert sorted(b["value"]) == ["a", "b", "c"]
    finally:
        client.close()


def test_create_only_skips_existing_record(redis_client, redis_container, aerospike_container):
    """CREATE_ONLY skips when the key exists; Aerospike returns AEROSPIKE_ERR_RECORD_EXISTS — expected."""
    import aerospike

    key = "e2e_create_only_hold"
    redis_client.set(key, "from_redis")

    config = build_migration_config(redis_container, aerospike_container)
    config.redis.scan_match = key
    config.aerospike.record_exists_policy = RecordExistsPolicy.CREATE_ONLY

    aclient = aerospike_reader(config)
    ns, st = config.aerospike.namespace, config.aerospike.set_name
    try:
        aclient.put(
            (ns, st, key),
            {"value": "preseed"},
            policy={"ttl": aerospike.TTL_NEVER_EXPIRE},
        )
    finally:
        aclient.close()

    stats = run_migration(config)
    assert stats.skipped == 1
    assert stats.skipped_by_type.get("exists") == 1
    assert stats.migrated == 0
    assert stats.errors == 0

    aclient = aerospike_reader(config)
    try:
        _, _, bins = aclient.get((ns, st, key))
        assert bins["value"] == "preseed"
    finally:
        aclient.close()
