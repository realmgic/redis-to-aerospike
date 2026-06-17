"""End-to-end migration with Valkey as the Redis-protocol source.

Mirrors ``test_end_to_end.py`` against a Valkey container. Aerospike writes use
set ``valkey`` so runs do not collide with Redis-backed tests on the shared
session Aerospike instance.
"""

from __future__ import annotations

import pytest

from migration_helpers import (
    VALKEY_SET_NAME,
    aerospike_reader,
    build_migration_config,
    run_migration,
)

from redis_to_aerospike.config import HashStrategy, TtlOverflowPolicy

pytestmark = pytest.mark.integration


def _cfg(kv_container, aerospike_container, strategy=HashStrategy.MAP_BIN):
    return build_migration_config(
        kv_container, aerospike_container, strategy, set_name=VALKEY_SET_NAME
    )


def test_full_migration(valkey_client, valkey_container, aerospike_container):
    valkey_client.set("num", "42")
    valkey_client.set("greeting", "hello")
    valkey_client.hset("user:1", mapping={"name": "alice", "age": "30"})
    valkey_client.rpush("mylist", "a", "b", "c")
    valkey_client.sadd("myset", "x", "y", "z", "x")
    valkey_client.zadd("myzset", {"alice": 1, "bob": 2})
    valkey_client.set("temp", "soon", ex=1000)
    expected_keys = 7

    config = _cfg(valkey_container, aerospike_container)
    stats = run_migration(config)

    assert stats.errors == 0
    assert stats.migrated == expected_keys

    client = aerospike_reader(config)
    try:
        ns = config.aerospike.namespace
        s = VALKEY_SET_NAME

        def bins(key):
            _, _, b = client.get((ns, s, key))
            return b

        assert bins("num")["value"] == 42 and isinstance(bins("num")["value"], int)
        assert bins("greeting")["value"] == "hello"
        assert bins("user:1")["value"] == {"name": "alice", "age": 30}
        assert bins("mylist")["value"] == ["a", "b", "c"]
        assert sorted(bins("myset")["value"]) == ["x", "y", "z"]
        assert bins("myzset")["value"] == {"alice": 1.0, "bob": 2.0}

        _, meta, _ = client.get((ns, s, "temp"))
        assert 0 < meta["ttl"] <= 1000
    finally:
        client.close()


def test_never_expire_key_reads_back_as_no_expiry(valkey_client, valkey_container, aerospike_container):
    valkey_client.set("forever_vk", "v")
    config = _cfg(valkey_container, aerospike_container)
    run_migration(config)

    client = aerospike_reader(config)
    try:
        _, meta, _ = client.get((config.aerospike.namespace, VALKEY_SET_NAME, "forever_vk"))
        assert meta["ttl"] in (-1, 0xFFFFFFFF)
    finally:
        client.close()


def test_ttl_over_max_is_rejected_by_default(valkey_client, valkey_container, aerospike_container):
    valkey_client.set("ok_ttl_reject_vk", "v", ex=50)
    valkey_client.set("bad_ttl_reject_vk", "v", ex=1000)
    config = _cfg(valkey_container, aerospike_container)
    config.aerospike.max_ttl = 100

    stats = run_migration(config)

    assert "convert:TtlTooLongError" in stats.errors_by_type
    client = aerospike_reader(config)
    try:
        ns = config.aerospike.namespace
        s = VALKEY_SET_NAME
        _, meta, _ = client.get((ns, s, "ok_ttl_reject_vk"))
        assert 0 < meta["ttl"] <= 100
        _, meta = client.exists((ns, s, "bad_ttl_reject_vk"))
        assert meta is None
    finally:
        client.close()


def test_ttl_over_max_is_clamped_when_configured(valkey_client, valkey_container, aerospike_container):
    valkey_client.set("bad_ttl_clamp_vk", "v", ex=1000)
    config = _cfg(valkey_container, aerospike_container)
    config.aerospike.max_ttl = 100
    config.ttl_overflow_policy = TtlOverflowPolicy.CLAMP

    stats = run_migration(config)

    assert stats.errors == 0
    client = aerospike_reader(config)
    try:
        _, meta, _ = client.get((config.aerospike.namespace, VALKEY_SET_NAME, "bad_ttl_clamp_vk"))
        assert 0 < meta["ttl"] <= 100
    finally:
        client.close()


def test_binary_key_and_value_roundtrip(valkey_client, valkey_container, aerospike_container):
    bin_key = b"\xff\x01\x02key"
    blob = b"\x00\xff\x10\x00"
    valkey_client.set(bin_key, blob)

    config = _cfg(valkey_container, aerospike_container)
    stats = run_migration(config)
    assert stats.errors == 0

    client = aerospike_reader(config)
    try:
        _, _, b = client.get((config.aerospike.namespace, VALKEY_SET_NAME, bin_key))
        assert bytes(b["value"]) == blob
    finally:
        client.close()


def test_numeric_set_members_preserved_distinctly(valkey_client, valkey_container, aerospike_container):
    valkey_client.sadd("nums_vk", "1", "1.0", "2")
    config = _cfg(valkey_container, aerospike_container)
    assert run_migration(config).errors == 0

    client = aerospike_reader(config)
    try:
        _, _, b = client.get((config.aerospike.namespace, VALKEY_SET_NAME, "nums_vk"))
        assert sorted(b["value"]) == ["1", "1.0", "2"]
    finally:
        client.close()


def test_zset_float_member_and_inf_score(valkey_client, valkey_container, aerospike_container):
    valkey_client.zadd("zedge_vk", {"1.5": 2.0, "big": float("inf")})
    config = _cfg(valkey_container, aerospike_container)
    assert run_migration(config).errors == 0

    client = aerospike_reader(config)
    try:
        _, _, b = client.get((config.aerospike.namespace, VALKEY_SET_NAME, "zedge_vk"))
        assert b["value"] == {"1.5": 2.0, "big": "inf"}
    finally:
        client.close()


def test_unsupported_type_is_skipped(valkey_client, valkey_container, aerospike_container):
    valkey_client.xadd("events_vk", {"f": "v"})
    config = _cfg(valkey_container, aerospike_container)
    stats = run_migration(config)

    assert stats.skipped == 1
    assert stats.skipped_by_type == {"stream": 1}
    assert stats.migrated == 0


def test_oversized_value_is_rejected_gracefully(valkey_client, valkey_container, aerospike_container):
    valkey_client.set("small_vk", "ok")
    valkey_client.set("huge_vk", "x" * (9 * 1024 * 1024))
    config = _cfg(valkey_container, aerospike_container)

    stats = run_migration(config)

    assert stats.scanned == 2
    assert stats.migrated == 1
    assert stats.errors == 1
    assert "write:RecordTooLargeError" in stats.errors_by_type

    client = aerospike_reader(config)
    try:
        assert client.get((config.aerospike.namespace, VALKEY_SET_NAME, "small_vk"))[2]["value"] == "ok"
        _, meta = client.exists((config.aerospike.namespace, VALKEY_SET_NAME, "huge_vk"))
        assert meta is None
    finally:
        client.close()


def test_field_bins_strategy_and_long_name_failure(valkey_client, valkey_container, aerospike_container):
    valkey_client.hset("acct_vk", mapping={"name": "bob", "age": "42"})
    valkey_client.hset("bad_vk", mapping={"this_field_name_is_way_too_long": "1"})

    config = _cfg(valkey_container, aerospike_container, strategy=HashStrategy.FIELD_BINS)
    stats = run_migration(config)

    assert stats.migrated == 1
    assert stats.errors == 1

    client = aerospike_reader(config)
    try:
        _, _, b = client.get((config.aerospike.namespace, VALKEY_SET_NAME, "acct_vk"))
        assert b == {"name": "bob", "age": 42}
    finally:
        client.close()


def test_set_uniqueness_is_idempotent(valkey_client, valkey_container, aerospike_container):
    valkey_client.sadd("dups_vk", "a", "b", "c")
    config = _cfg(valkey_container, aerospike_container)

    run_migration(config)
    run_migration(config)

    client = aerospike_reader(config)
    try:
        _, _, b = client.get((config.aerospike.namespace, VALKEY_SET_NAME, "dups_vk"))
        assert sorted(b["value"]) == ["a", "b", "c"]
    finally:
        client.close()
