"""Redis list -> Aerospike list (order preserved)."""

from __future__ import annotations

from ..models import AerospikeRecord, RedisRecord
from .base import Converter, coerce_scalar


class ListConverter(Converter):
    redis_type = "list"

    def convert(self, record: RedisRecord) -> AerospikeRecord:
        items = [coerce_scalar(item) for item in (record.value or [])]
        return self._build(record, {self.value_bin: items})
