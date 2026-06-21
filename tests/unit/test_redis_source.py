"""Unit tests for RedisSource using an in-memory fakeredis backend."""

from typing import cast

import pytest

from redis_to_aerospike.config import RedisConfig
from redis_to_aerospike.redis_source import RedisConnection, RedisSource, redis_client_params


@pytest.fixture
def source(fake_redis):
    return RedisSource(RedisConfig(), client=fake_redis)


def _by_key(records):
    return {r.key: r for r in records}


# --- redis_client_params ---------------------------------------------------

def test_client_params_discrete_defaults():
    cluster, url, kwargs = redis_client_params(RedisConfig())
    assert cluster is False
    assert url is None
    assert kwargs == {"decode_responses": False, "host": "localhost", "port": 6379, "db": 0}


def test_client_params_auth_and_ssl():
    cluster, url, kwargs = redis_client_params(
        RedisConfig(
            username="alice",
            password="secret",
            ssl=True,
            ssl_ca_certs="/certs/ca.pem",
            ssl_certfile="/certs/c.pem",
        )
    )
    assert (cluster, url) == (False, None)
    assert kwargs["username"] == "alice"
    assert kwargs["password"] == "secret"
    assert kwargs["ssl"] is True
    assert kwargs["ssl_ca_certs"] == "/certs/ca.pem"
    assert kwargs["ssl_certfile"] == "/certs/c.pem"


def test_client_params_socket_timeouts():
    _, _, kwargs = redis_client_params(
        RedisConfig(socket_timeout=2.5, socket_connect_timeout=1.0)
    )
    assert kwargs["socket_timeout"] == 2.5
    assert kwargs["socket_connect_timeout"] == 1.0


def test_client_params_url_ignores_discrete_fields():
    cluster, url, kwargs = redis_client_params(
        RedisConfig(url="rediss://h:6379/0", host="ignored", port=1234, socket_timeout=1.0)
    )
    assert cluster is False
    assert url == "rediss://h:6379/0"
    # URL is the source of truth: no host/port/db, but timeouts still apply.
    assert "host" not in kwargs and "port" not in kwargs and "db" not in kwargs
    assert kwargs["socket_timeout"] == 1.0


def test_client_params_cluster_omits_db():
    cluster, url, kwargs = redis_client_params(RedisConfig(cluster=True, db=0))
    assert cluster is True
    assert url is None
    assert "db" not in kwargs
    assert kwargs["host"] == "localhost"


# --- cluster scanning ------------------------------------------------------

class _FakeClusterClient:
    """Minimal cluster-like client exposing scan_iter across all shards."""

    def __init__(self, keys):
        self._keys = keys

    def scan_iter(self, match=None, count=None):
        yield from self._keys


def test_cluster_scan_chunks_into_batches():
    keys = [f"k{i}".encode() for i in range(25)]
    src = RedisSource(RedisConfig(cluster=True), client=cast(RedisConnection, _FakeClusterClient(keys)))
    batches = list(src._iter_key_batches(10))
    assert [len(b) for b in batches] == [10, 10, 5]
    assert [k for b in batches for k in b] == keys


# --- static decision helpers ----------------------------------------------

@pytest.mark.parametrize(
    "key_type,value,vanished",
    [
        ("string", None, True),
        ("string", b"", False),     # empty string is a real value
        ("string", b"x", False),
        ("hash", {}, True),
        ("list", [], True),
        ("set", set(), True),
        ("zset", [], True),
        ("hash", {b"f": b"v"}, False),
        ("stream", 1, False),       # unsupported types are not "vanished"
    ],
)
def test_is_vanished(key_type, value, vanished):
    assert RedisSource._is_vanished(key_type, value) is vanished


def test_decode_key_utf8_becomes_str():
    assert RedisSource._decode_key(b"user:1") == "user:1"


def test_decode_key_binary_stays_bytes():
    raw = b"\xff\x00\x01"
    assert RedisSource._decode_key(raw) == raw


# --- end-to-end iteration over a fake server -------------------------------

def test_materializes_each_type(source, fake_redis):
    fake_redis.set("s", "hello")
    fake_redis.hset("h", mapping={"a": "1"})
    fake_redis.rpush("l", "x", "y")
    fake_redis.sadd("st", "m1", "m2")
    fake_redis.zadd("z", {"m": 1.5})

    records = _by_key(source.iter_records(batch_size=10))

    assert records["s"].type == "string" and records["s"].value == b"hello"
    assert records["h"].type == "hash" and records["h"].value == {b"a": b"1"}
    assert records["l"].type == "list" and records["l"].value == [b"x", b"y"]
    assert records["st"].type == "set" and records["st"].value == {b"m1", b"m2"}
    assert records["z"].type == "zset" and records["z"].value == [(b"m", 1.5)]


def test_scan_paginates_across_batches(source, fake_redis):
    for i in range(250):
        fake_redis.set(f"k{i}", "v")
    records = list(source.iter_records(batch_size=10))
    assert len({r.key for r in records}) == 250


def test_ttl_is_captured_in_ms(source, fake_redis):
    fake_redis.set("with_ttl", "v", px=100_000)
    fake_redis.set("no_ttl", "v")
    records = _by_key(source.iter_records(batch_size=10))
    assert 0 < records["with_ttl"].ttl_ms <= 100_000
    assert records["no_ttl"].ttl_ms is None


def test_binary_key_is_preserved(source, fake_redis):
    raw = b"\xff\x01"
    fake_redis.set(raw, "v")
    records = list(source.iter_records(batch_size=10))
    keys = {r.key for r in records}
    assert raw in keys


def test_binary_string_value_is_preserved(source, fake_redis):
    blob = b"\x00\xff\x10"
    fake_redis.set("blob", blob)
    records = _by_key(source.iter_records(batch_size=10))
    assert records["blob"].value == blob


def test_expiry_race_none_value_is_skipped(source, fake_redis, monkeypatch):
    fake_redis.set("ghost", "v")

    # Simulate the key expiring between the TYPE read and the value read.
    def fake_fetch_values(keys, types):
        return {k: None for k in keys if types[k] != "none"}

    monkeypatch.setattr(source, "_fetch_values", fake_fetch_values)
    assert list(source.iter_records(batch_size=10)) == []


def test_server_info_reports_keys(source, fake_redis):
    fake_redis.set("a", "1")
    fake_redis.set("b", "2", px=100_000)

    info = source.server_info()

    # dbsize is always available; memory/version/keyspace are best-effort and
    # depend on the backend, so we only assert the reliable count here.
    assert info["keys"] == 2


def test_server_info_is_best_effort(monkeypatch):
    class _BrokenClient:
        def dbsize(self):
            raise ConnectionError("down")

        def info(self, section):
            raise ConnectionError("down")

    src = RedisSource(RedisConfig(), client=cast(RedisConnection, _BrokenClient()))
    # Never raises; just returns whatever it could gather (here, nothing).
    assert src.server_info() == {}
