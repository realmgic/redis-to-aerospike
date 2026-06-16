import pytest

from redis_to_aerospike.config import (
    DEFAULT_MAX_TTL_S,
    HashStrategy,
    MigrationConfig,
    TtlOverflowPolicy,
)
from redis_to_aerospike.converters.base import Converter, TtlTooLongError
from redis_to_aerospike.converters.registry import ConverterRegistry, UnsupportedTypeError
from redis_to_aerospike.models import TTL_NEVER_EXPIRE, AerospikeRecord, RedisRecord


def test_resolves_each_known_type():
    reg = ConverterRegistry()
    for t in ("string", "hash", "list", "set", "zset"):
        assert reg.supports(t)
        assert reg.get(t).redis_type == t


def test_unsupported_type_raises():
    reg = ConverterRegistry()
    assert not reg.supports("stream")
    with pytest.raises(UnsupportedTypeError):
        reg.get("stream")


def test_from_config_passes_value_bin_and_strategy():
    config = MigrationConfig()
    config.aerospike.value_bin = "v"
    config.hash_strategy = HashStrategy.FIELD_BINS
    reg = ConverterRegistry.from_config(config)
    out = reg.convert(RedisRecord(key="k", type="hash", value={b"age": b"5"}))
    assert out.bins == {"age": 5}


def test_from_config_default_rejects_oversized_ttl():
    config = MigrationConfig()
    reg = ConverterRegistry.from_config(config)
    over = RedisRecord(key="k", type="string", value=b"v", ttl_ms=(DEFAULT_MAX_TTL_S + 1) * 1000)
    with pytest.raises(TtlTooLongError):
        reg.convert(over)


def test_from_config_wires_never_expire_policy():
    config = MigrationConfig(ttl_overflow_policy=TtlOverflowPolicy.NEVER_EXPIRE)
    reg = ConverterRegistry.from_config(config)
    over = RedisRecord(key="k", type="string", value=b"v", ttl_ms=(DEFAULT_MAX_TTL_S + 1) * 1000)
    assert reg.convert(over).ttl_s == TTL_NEVER_EXPIRE


def test_override_registration_wins():
    class ShoutingString(Converter):
        redis_type = "string"

        def convert(self, record):
            return AerospikeRecord(key=record.key, bins={"value": "OVERRIDDEN"})

    reg = ConverterRegistry()
    reg.register(ShoutingString())
    out = reg.convert(RedisRecord(key="k", type="string", value=b"whatever"))
    assert out.bins == {"value": "OVERRIDDEN"}


def test_register_requires_redis_type():
    class Bad(Converter):
        def convert(self, record):
            return AerospikeRecord(key=record.key, bins={})

    with pytest.raises(ValueError):
        ConverterRegistry().register(Bad())
