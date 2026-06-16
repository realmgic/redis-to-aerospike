"""Converter contract plus shared, side-effect-free helpers.

A converter turns one :class:`RedisRecord` into one :class:`AerospikeRecord`.
Converters are pure functions of their input, which makes them simple to read and
exhaustively unit-test without touching either database.
"""

from __future__ import annotations

import logging
import math
import re
import threading
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from ..config import DEFAULT_MAX_TTL_S, TtlOverflowPolicy
from ..models import TTL_NEVER_EXPIRE, AerospikeRecord, BinWritePolicy, RedisRecord

logger = logging.getLogger(__name__)

# Strict patterns so we only promote values that are unambiguously numeric.
# Leading zeros are rejected for ints ("007" stays a string) to avoid silent
# data changes during migration.
_INT_RE = re.compile(r"^-?(0|[1-9]\d*)$")
_FLOAT_RE = re.compile(r"^-?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?$")

# Aerospike integers are signed 64-bit; anything outside this range must stay a
# string or the write is rejected by the server.
_INT64_MIN = -(2 ** 63)
_INT64_MAX = 2 ** 63 - 1


def coerce_scalar(value: Any) -> Any:
    """Coerce a raw Redis scalar into the most natural Aerospike type.

    Order of preference: ``int`` -> ``float`` -> ``str`` -> ``bytes`` (blob).
    Non-UTF8 bytes are preserved as-is so binary values migrate losslessly.

    Values that look numeric but would be illegal in Aerospike are kept as
    strings rather than silently corrupted: integers outside the signed 64-bit
    range, and floats that parse to a non-finite value (``inf``/``nan``).
    """
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, bytes):
        try:
            text = value.decode("utf-8")
        except UnicodeDecodeError:
            return value  # genuine binary blob -> store as Aerospike bytes
    elif isinstance(value, str):
        text = value
    else:
        return value

    if _INT_RE.match(text):
        number = int(text)
        if _INT64_MIN <= number <= _INT64_MAX:
            return number
        return text  # too big for an Aerospike integer -> keep as string
    if _FLOAT_RE.match(text) and any(c in text for c in ".eE"):
        number = float(text)
        if math.isfinite(number):
            return number
        return text  # inf/nan cannot be represented as an Aerospike double
    return text


# Aerospike reserves the top unsigned 32-bit values (0xFFFFFFFD..0xFFFFFFFF) for
# special TTL semantics (client-default, don't-update, never-expire). Clamp real
# expiries below them so an enormous Redis TTL can never collide with a sentinel.
_MAX_REAL_TTL_S = 0xFFFFFFFC


def decode_member(value: Any) -> Any:
    """Decode a Redis set/zset member for use as a list element or map key.

    Returns ``str`` when UTF-8 decodable, otherwise the raw ``bytes``. Members
    are deliberately NOT numerically coerced: doing so could collapse distinct
    members (``"1"`` and ``"1.0"`` both become numbers that compare equal) or
    produce a ``float``, which Aerospike rejects as a map key.
    """
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value
    return value


def to_aerospike_ttl(ttl_ms: Optional[int]) -> int:
    """Convert a Redis millisecond TTL into an Aerospike second TTL.

    ``None`` (no Redis expiry) maps to "never expire". A positive TTL is rounded
    up so a sub-second remainder never becomes 0 (which Aerospike interprets as
    the namespace default rather than "about to expire"), and clamped below the
    reserved sentinel range. This base helper does not enforce ``max-ttl``;
    :class:`TtlPolicy` layers that boundary on top.
    """
    if ttl_ms is None:
        return TTL_NEVER_EXPIRE
    return min(_MAX_REAL_TTL_S, max(1, math.ceil(ttl_ms / 1000)))


class TtlTooLongError(Exception):
    """Raised when a TTL exceeds ``max-ttl`` under the ``REJECT`` overflow policy."""


class TtlPolicy:
    """Resolves a Redis TTL to an Aerospike TTL, enforcing the max-ttl boundary.

    When a record's TTL exceeds ``max_ttl_s`` the behavior is governed by
    ``mode`` (:class:`~redis_to_aerospike.config.TtlOverflowPolicy`):

    * ``REJECT``       -- raise :class:`TtlTooLongError` (record is not written).
    * ``CLAMP``        -- return exactly ``max_ttl_s``.
    * ``NEVER_EXPIRE`` -- return never-expire.

    For the non-rejecting modes a single warning is emitted per run (thread-safe),
    so a large keyspace does not produce a flood of log lines.
    """

    def __init__(
        self,
        mode: TtlOverflowPolicy = TtlOverflowPolicy.REJECT,
        max_ttl_s: int = DEFAULT_MAX_TTL_S,
    ):
        self.mode = TtlOverflowPolicy(mode)
        self.max_ttl_s = max_ttl_s
        self._warned = False
        self._lock = threading.Lock()

    def to_ttl(self, ttl_ms: Optional[int]) -> int:
        if ttl_ms is None:
            return TTL_NEVER_EXPIRE
        seconds = max(1, math.ceil(ttl_ms / 1000))
        if self.max_ttl_s and seconds > self.max_ttl_s:
            return self._handle_overflow(seconds)
        return min(_MAX_REAL_TTL_S, seconds)

    def _handle_overflow(self, seconds: int) -> int:
        if self.mode is TtlOverflowPolicy.REJECT:
            self._warn_once(
                "One or more records have a TTL above max-ttl (%ss); "
                "rejecting them (they will not be written)",
                self.max_ttl_s,
            )
            raise TtlTooLongError(
                f"TTL {seconds}s exceeds the Aerospike max-ttl of {self.max_ttl_s}s"
            )
        if self.mode is TtlOverflowPolicy.NEVER_EXPIRE:
            self._warn_once(
                "One or more records have a TTL above max-ttl (%ss); "
                "storing them as never-expire",
                self.max_ttl_s,
            )
            return TTL_NEVER_EXPIRE
        # CLAMP
        self._warn_once(
            "One or more records have a TTL above max-ttl (%ss); "
            "clamping them to the maximum",
            self.max_ttl_s,
        )
        return self.max_ttl_s

    def _warn_once(self, msg: str, *args) -> None:
        with self._lock:
            if self._warned:
                return
            self._warned = True
        logger.warning(msg, *args)


class Converter(ABC):
    """Base class for all type converters."""

    #: The Redis type string this converter handles (e.g. ``"string"``).
    redis_type: str = ""

    def __init__(self, value_bin: str = "value", ttl_policy: Optional[TtlPolicy] = None):
        self.value_bin = value_bin
        self.ttl_policy = ttl_policy or TtlPolicy()

    @abstractmethod
    def convert(self, record: RedisRecord) -> AerospikeRecord:  # pragma: no cover
        raise NotImplementedError

    def _build(
        self,
        record: RedisRecord,
        bins: Dict[str, Any],
        bin_policies: Optional[Dict[str, BinWritePolicy]] = None,
    ) -> AerospikeRecord:
        return AerospikeRecord(
            key=record.key,
            bins=bins,
            ttl_s=self.ttl_policy.to_ttl(record.ttl_ms),
            bin_policies=bin_policies or {},
        )
