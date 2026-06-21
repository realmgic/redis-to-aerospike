"""Resolve Aerospike set names and primary keys from Redis keys using glob routes."""

from __future__ import annotations

import fnmatch
from typing import List, NamedTuple, Optional, Union

from .config import AerospikeSetRoute, HashStrategy


class RouteResolution(NamedTuple):
    """Target Aerospike set and primary key after applying a matched route."""

    set_name: str
    key: Union[str, bytes]
    hash_strategy: Optional[HashStrategy] = None
    value_bin: Optional[str] = None


def _aerospike_key_from_route(redis_key: str, pattern: str) -> str:
    """Strip fixed glob literals around a single ``*``; keep full key if ambiguous.

    Only patterns with **exactly one** ``*`` and no ``?`` or ``[`` are rewritten
    (same class of patterns Redis ``SCAN MATCH`` uses well). Otherwise the full
    ``redis_key`` is preserved.
    """
    if pattern.count("*") != 1:
        return redis_key
    if "?" in pattern or "[" in pattern:
        return redis_key
    left, right = pattern.split("*", 1)
    if not fnmatch.fnmatch(redis_key, pattern):
        return redis_key
    if right == "":
        body = redis_key[len(left) :]
    elif left == "":
        if not redis_key.endswith(right):
            return redis_key
        body = redis_key[: len(redis_key) - len(right)]
    else:
        if not (redis_key.startswith(left) and redis_key.endswith(right)):
            return redis_key
        body = redis_key[len(left) : len(redis_key) - len(right)]
    # Avoid empty Aerospike user keys when the match is exactly the prefix/suffix.
    return body if body != "" else redis_key


class SetRouter:
    """First matching route wins; binary Redis keys skip routing (default set, full key)."""

    def __init__(self, routes: List[AerospikeSetRoute], default_set_name: str):
        self._routes = list(routes)
        self._default = default_set_name

    def resolve(self, key: Union[str, bytes]) -> RouteResolution:
        if not self._routes or isinstance(key, bytes):
            return RouteResolution(self._default, key, None, None)
        for route in self._routes:
            if fnmatch.fnmatch(key, route.pattern):
                out_key = _aerospike_key_from_route(key, route.pattern)
                return RouteResolution(
                    route.destination,
                    out_key,
                    route.hash_strategy,
                    route.value_bin,
                )
        return RouteResolution(self._default, key, None, None)
