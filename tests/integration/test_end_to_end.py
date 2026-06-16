"""End-to-end migration against real Redis and Aerospike containers."""

from __future__ import annotations

import aerospike

from redis_to_aerospike.aerospike_sink import AerospikeSink
from redis_to_aerospike.config import (
    AerospikeConfig,
    HashStrategy,
    MigrationConfig,
    RedisConfig,
    TtlOverflowPolicy,
)
from redis_to_aerospike.converters.registry import ConverterRegistry
from redis_to_aerospike.migrator import Migrator
from redis_to_aerospike.redis_source import RedisSource

SET_NAME = "redis"


def _build_config(redis_container, aerospike_container, strategy=HashStrategy.MAP_BIN) -> MigrationConfig:
    return MigrationConfig(
        redis=RedisConfig(host=redis_container["host"], port=redis_container["port"]),
        aerospike=AerospikeConfig(
            hosts=[(aerospike_container["host"], aerospike_container["port"])],
            namespace=aerospike_container["namespace"],
            set_name=SET_NAME,
        ),
        workers=4,
        scan_batch=10,
        queue_size=64,
        hash_strategy=strategy,
    )


def _run(config):
    source = RedisSource(config.redis)
    registry = ConverterRegistry.from_config(config)
    sink = AerospikeSink(config.aerospike).connect()
    try:
        return Migrator(config, source, registry, sink).run()
    finally:
        source.close()
        sink.close()


def _reader(config):
    return aerospike.client({"hosts": config.aerospike.hosts}).connect()


def test_full_migration(redis_client, redis_container, aerospike_container):
    redis_client.set("num", "42")
    redis_client.set("greeting", "hello")
    redis_client.hset("user:1", mapping={"name": "alice", "age": "30"})
    redis_client.rpush("mylist", "a", "b", "c")
    redis_client.sadd("myset", "x", "y", "z", "x")
    redis_client.zadd("myzset", {"alice": 1, "bob": 2})
    redis_client.set("temp", "soon", ex=1000)
    expected_keys = 7  # data-driven below, kept explicit for clarity

    config = _build_config(redis_container, aerospike_container)
    stats = _run(config)

    assert stats.errors == 0
    assert stats.migrated == expected_keys

    client = _reader(config)
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
    config = _build_config(redis_container, aerospike_container)
    _run(config)

    client = _reader(config)
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
    config = _build_config(redis_container, aerospike_container)
    # Use a small max-ttl so we exercise the boundary without depending on the
    # container's namespace max-ttl.
    config.aerospike.max_ttl = 100

    stats = _run(config)

    assert "convert:TtlTooLongError" in stats.errors_by_type
    client = _reader(config)
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
    config = _build_config(redis_container, aerospike_container)
    config.aerospike.max_ttl = 100
    config.ttl_overflow_policy = TtlOverflowPolicy.CLAMP

    stats = _run(config)

    assert stats.errors == 0
    client = _reader(config)
    try:
        _, meta, _ = client.get((config.aerospike.namespace, SET_NAME, "bad_ttl_clamp"))
        assert 0 < meta["ttl"] <= 100
    finally:
        client.close()


def test_binary_key_and_value_roundtrip(redis_client, redis_container, aerospike_container):
    bin_key = b"\xff\x01\x02key"
    blob = b"\x00\xff\x10\x00"
    redis_client.set(bin_key, blob)

    config = _build_config(redis_container, aerospike_container)
    stats = _run(config)
    assert stats.errors == 0

    client = _reader(config)
    try:
        _, _, b = client.get((config.aerospike.namespace, SET_NAME, bin_key))
        assert bytes(b["value"]) == blob
    finally:
        client.close()


def test_numeric_set_members_preserved_distinctly(redis_client, redis_container, aerospike_container):
    redis_client.sadd("nums", "1", "1.0", "2")
    config = _build_config(redis_container, aerospike_container)
    assert _run(config).errors == 0

    client = _reader(config)
    try:
        _, _, b = client.get((config.aerospike.namespace, SET_NAME, "nums"))
        assert sorted(b["value"]) == ["1", "1.0", "2"]
    finally:
        client.close()


def test_zset_float_member_and_inf_score(redis_client, redis_container, aerospike_container):
    redis_client.zadd("zedge", {"1.5": 2.0, "big": float("inf")})
    config = _build_config(redis_container, aerospike_container)
    assert _run(config).errors == 0

    client = _reader(config)
    try:
        _, _, b = client.get((config.aerospike.namespace, SET_NAME, "zedge"))
        assert b["value"] == {"1.5": 2.0, "big": "inf"}
    finally:
        client.close()


def test_unsupported_type_is_skipped(redis_client, redis_container, aerospike_container):
    redis_client.xadd("events", {"f": "v"})
    config = _build_config(redis_container, aerospike_container)
    stats = _run(config)

    assert stats.skipped == 1
    assert stats.skipped_by_type == {"stream": 1}
    assert stats.migrated == 0


def test_oversized_value_is_rejected_gracefully(redis_client, redis_container, aerospike_container):
    redis_client.set("small", "ok")
    redis_client.set("huge", "x" * (9 * 1024 * 1024))  # 9 MB, over the 8 MiB limit
    config = _build_config(redis_container, aerospike_container)

    stats = _run(config)

    assert stats.scanned == 2
    assert stats.migrated == 1  # only the small key
    assert stats.errors == 1
    assert "write:RecordTooLargeError" in stats.errors_by_type

    client = _reader(config)
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

    config = _build_config(redis_container, aerospike_container, strategy=HashStrategy.FIELD_BINS)
    stats = _run(config)

    # The valid hash migrates to per-field bins; the long-field hash errors.
    assert stats.migrated == 1
    assert stats.errors == 1

    client = _reader(config)
    try:
        _, _, b = client.get((config.aerospike.namespace, SET_NAME, "acct"))
        assert b == {"name": "bob", "age": 42}
    finally:
        client.close()


def test_set_uniqueness_is_idempotent(redis_client, redis_container, aerospike_container):
    redis_client.sadd("dups", "a", "b", "c")
    config = _build_config(redis_container, aerospike_container)

    _run(config)
    _run(config)  # second pass must not duplicate members

    client = _reader(config)
    try:
        _, _, b = client.get((config.aerospike.namespace, SET_NAME, "dups"))
        assert sorted(b["value"]) == ["a", "b", "c"]
    finally:
        client.close()
