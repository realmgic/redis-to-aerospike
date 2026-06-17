"""Shared helpers for Redis- and Valkey-backed integration migration tests."""

from __future__ import annotations

import aerospike

from redis_to_aerospike.aerospike_sink import AerospikeSink
from redis_to_aerospike.config import (
    AerospikeConfig,
    HashStrategy,
    MigrationConfig,
    RedisConfig,
)
from redis_to_aerospike.converters.registry import ConverterRegistry
from redis_to_aerospike.migrator import Migrator
from redis_to_aerospike.redis_source import RedisSource

SET_NAME = "redis"
VALKEY_SET_NAME = "valkey"


def build_migration_config(
    kv_container: dict,
    aerospike_container: dict,
    strategy=HashStrategy.MAP_BIN,
    *,
    set_name: str = SET_NAME,
) -> MigrationConfig:
    """Build a :class:`MigrationConfig` targeting a Redis-protocol host and Aerospike."""
    return MigrationConfig(
        redis=RedisConfig(host=kv_container["host"], port=kv_container["port"]),
        aerospike=AerospikeConfig(
            hosts=[(aerospike_container["host"], aerospike_container["port"])],
            namespace=aerospike_container["namespace"],
            set_name=set_name,
        ),
        workers=4,
        scan_batch=10,
        queue_size=64,
        hash_strategy=strategy,
    )


def run_migration(config: MigrationConfig):
    source = RedisSource(config.redis)
    registry = ConverterRegistry.from_config(config)
    sink = AerospikeSink(config.aerospike).connect()
    try:
        return Migrator(config, source, registry, sink).run()
    finally:
        source.close()
        sink.close()


def aerospike_reader(config: MigrationConfig):
    return aerospike.client({"hosts": config.aerospike.hosts}).connect()
