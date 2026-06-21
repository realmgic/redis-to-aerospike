"""Redis sorted set -> Aerospike map of ``{member: score}``.

Storing scores in a map keeps them queryable natively and preserves the
member -> score relationship. The source yields members already sorted ascending
by score, which insertion order retains.

Members are kept as decoded strings (or bytes), never numerically coerced: a
float member would be an illegal Aerospike map key, and numeric coercion could
collapse distinct members. Scores are stored as floats, except non-finite scores
(``inf``/``-inf``/``nan``, which Redis allows) which are stored as their string
form since Aerospike doubles cannot represent them.
"""

from __future__ import annotations

import math
from typing import Any, Dict

from ..models import AerospikeRecord, RedisRecord
from .base import Converter, decode_member


def _encode_score(score: float):
    value = score
    return value if isinstance(value, float) and math.isfinite(value) else str(value)


class ZSetConverter(Converter):
    redis_type = "zset"

    def convert(self, record: RedisRecord) -> AerospikeRecord:
        scores: Dict[Any, Any] = {}
        for member, score in (record.value or []):
            scores[decode_member(member)] = _encode_score(score)
        return self._build(record, {self.value_bin: scores})
