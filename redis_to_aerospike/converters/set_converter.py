"""Redis set -> Aerospike list with a uniqueness guarantee.

Aerospike has no native set type. We migrate sets to a list and tag the bin with
``BinWritePolicy.UNIQUE_LIST`` so the sink writes it as an ordered list with the
``ADD_UNIQUE`` write flag, enforcing set semantics server-side. Members are sorted
for deterministic output (handy for tests and idempotent re-runs).

Members are kept as decoded strings (or bytes), never numerically coerced --
otherwise distinct Redis members like ``"1"`` and ``"1.0"`` would collapse into a
single element, silently losing data.
"""

from __future__ import annotations

from ..models import AerospikeRecord, BinWritePolicy, RedisRecord
from .base import Converter, decode_member


def _sort_key(value):
    # Mixed-type sets can't be compared directly in Python 3, so order by a
    # (type-name, string) tuple for a stable, total ordering.
    return (type(value).__name__, str(value))


class SetConverter(Converter):
    redis_type = "set"

    def convert(self, record: RedisRecord) -> AerospikeRecord:
        members = {decode_member(member) for member in (record.value or set())}
        ordered = sorted(members, key=_sort_key)
        return self._build(
            record,
            {self.value_bin: ordered},
            bin_policies={self.value_bin: BinWritePolicy.UNIQUE_LIST},
        )
