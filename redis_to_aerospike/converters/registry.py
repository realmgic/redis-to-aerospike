"""Maps a Redis type to the converter that handles it.

This is the single place to register or override conversion behavior. To change
how a type migrates -- or to add support for a new type -- register a different
:class:`Converter`; nothing else in the pipeline needs to change.
"""

from __future__ import annotations

from typing import Dict, Optional

from ..config import HashStrategy, MigrationConfig
from ..models import AerospikeRecord, RedisRecord
from .base import Converter, TtlPolicy
from .hash_converter import HashConverter
from .list_converter import ListConverter
from .set_converter import SetConverter
from .string_converter import StringConverter
from .zset_converter import ZSetConverter


class UnsupportedTypeError(Exception):
    """Raised when no converter is registered for a Redis type."""


class ConverterRegistry:
    def __init__(
        self,
        value_bin: str = "value",
        hash_strategy: HashStrategy = HashStrategy.MAP_BIN,
        ttl_policy: Optional[TtlPolicy] = None,
    ):
        # A single shared policy so the "TTL too long" warning fires once per run
        # across every converter rather than once per type.
        ttl_policy = ttl_policy or TtlPolicy()
        self._converters: Dict[str, Converter] = {}
        self.register(StringConverter(value_bin, ttl_policy))
        self.register(HashConverter(value_bin, hash_strategy, ttl_policy))
        self.register(ListConverter(value_bin, ttl_policy))
        self.register(SetConverter(value_bin, ttl_policy))
        self.register(ZSetConverter(value_bin, ttl_policy))

    @classmethod
    def from_config(cls, config: MigrationConfig) -> "ConverterRegistry":
        return cls(
            value_bin=config.aerospike.value_bin,
            hash_strategy=config.hash_strategy,
            ttl_policy=TtlPolicy(
                mode=config.ttl_overflow_policy,
                max_ttl_s=config.aerospike.max_ttl,
            ),
        )

    def register(self, converter: Converter) -> None:
        """Register (or override) the converter for ``converter.redis_type``."""
        if not converter.redis_type:
            raise ValueError("converter must declare a non-empty redis_type")
        self._converters[converter.redis_type] = converter

    def get(self, redis_type: str) -> Converter:
        try:
            return self._converters[redis_type]
        except KeyError:
            raise UnsupportedTypeError(redis_type)

    def supports(self, redis_type: str) -> bool:
        return redis_type in self._converters

    def convert(self, record: RedisRecord) -> AerospikeRecord:
        return self.get(record.type).convert(record)
