"""Redis string -> single Aerospike bin (int/float/str/bytes)."""

from __future__ import annotations

from ..models import AerospikeRecord, RedisRecord
from .base import Converter, coerce_scalar


class StringConverter(Converter):
    redis_type = "string"

    def convert(self, record: RedisRecord) -> AerospikeRecord:
        return self._build(record, {self.value_bin: coerce_scalar(record.value)})
