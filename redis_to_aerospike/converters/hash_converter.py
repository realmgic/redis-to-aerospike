"""Redis hash -> Aerospike, with a configurable representation.

Two strategies are supported (see :class:`~redis_to_aerospike.config.HashStrategy`):

* ``MAP_BIN``    -- the whole hash becomes one Aerospike map in ``value_bin``.
* ``FIELD_BINS`` -- each hash field becomes its own Aerospike bin. This is more
  "native" but is subject to Aerospike's bin-name length limit (15 bytes by
  default), so field names are validated.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..config import HashStrategy
from ..models import AerospikeRecord, RedisRecord
from .base import Converter, TtlPolicy, coerce_scalar

# Default Aerospike bin-name length limit (bytes).
_MAX_BIN_NAME_BYTES = 15


def _decode_field(field: Any) -> str:
    if isinstance(field, bytes):
        return field.decode("utf-8", "replace")
    return str(field)


class HashConverter(Converter):
    redis_type = "hash"

    def __init__(
        self,
        value_bin: str = "value",
        strategy: HashStrategy = HashStrategy.MAP_BIN,
        ttl_policy: Optional[TtlPolicy] = None,
    ):
        super().__init__(value_bin, ttl_policy)
        self.strategy = strategy

    def convert(self, record: RedisRecord) -> AerospikeRecord:
        raw: Dict[Any, Any] = record.value or {}
        if self.strategy is HashStrategy.FIELD_BINS:
            return self._build(record, self._to_field_bins(raw))
        return self._build(record, {self.value_bin: self._to_map(raw)})

    def _to_map(self, raw: Dict[Any, Any]) -> Dict[str, Any]:
        return {_decode_field(field): coerce_scalar(value) for field, value in raw.items()}

    def _to_field_bins(self, raw: Dict[Any, Any]) -> Dict[str, Any]:
        bins: Dict[str, Any] = {}
        for field, value in raw.items():
            name = _decode_field(field)
            if len(name.encode("utf-8")) > _MAX_BIN_NAME_BYTES:
                raise ValueError(
                    f"hash field '{name}' exceeds the Aerospike bin-name limit of "
                    f"{_MAX_BIN_NAME_BYTES} bytes; use the {HashStrategy.MAP_BIN.value} "
                    f"strategy for this data"
                )
            bins[name] = coerce_scalar(value)
        return bins
