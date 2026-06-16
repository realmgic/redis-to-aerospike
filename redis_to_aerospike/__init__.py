"""Migrate Redis data into Aerospike using native Aerospike types.

The package is intentionally small and layered so the migration is easy to read
and extend:

* ``redis_source``   -- streams records out of Redis (the producer side).
* ``converters``     -- maps each Redis type to native Aerospike bins (pure, testable).
* ``transforms``     -- optional post-conversion hooks (the data-modeling seam).
* ``aerospike_sink`` -- writes records into Aerospike (the consumer side).
* ``migrator``       -- a multi-threaded producer/consumer pipeline tying it together.
"""

from .config import AerospikeConfig, AerospikeSetRoute, HashStrategy, MigrationConfig, RedisConfig
from .models import AerospikeRecord, BinWritePolicy, RedisRecord
from .migrator import Migrator
from .stats import MigrationStats

__all__ = [
    "AerospikeConfig",
    "AerospikeRecord",
    "AerospikeSetRoute",
    "BinWritePolicy",
    "HashStrategy",
    "MigrationConfig",
    "MigrationStats",
    "Migrator",
    "RedisConfig",
    "RedisRecord",
]
