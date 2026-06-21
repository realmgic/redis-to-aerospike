"""Read side of the migration: stream records out of Redis.

``RedisSource`` walks the keyspace with ``SCAN`` (cursor-based, non-blocking) and
materializes each key's value and TTL. Values are returned as their raw Redis
shapes (bytes, dicts, lists, sets, ``(member, score)`` tuples); coercion into
native Aerospike types is the converter layer's job. Reads are pipelined so each
SCAN batch costs only a couple of round-trips.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, Iterator, List, Tuple, cast

import redis
from redis.cluster import RedisCluster

from .config import RedisConfig
from .models import RedisRecord

logger = logging.getLogger(__name__)

# Standalone :class:`redis.Redis` or :class:`redis.cluster.RedisCluster`.
RedisConnection = redis.Redis | RedisCluster


def redis_client_params(config: RedisConfig):
    """Translate a :class:`RedisConfig` into redis-py client arguments.

    Pure (no I/O) and the unit-tested seam for connection wiring. Returns
    ``(cluster, url, kwargs)`` where ``cluster`` selects the cluster client,
    ``url`` (when set) is passed to ``from_url`` and supersedes the discrete
    connection fields, and ``kwargs`` are the constructor keyword arguments.
    """
    # decode_responses stays False so binary-safe string values survive intact;
    # the converter decides how to decode/coerce them.
    kwargs: Dict[str, Any] = {"decode_responses": False}
    if config.socket_timeout is not None:
        kwargs["socket_timeout"] = config.socket_timeout
    if config.socket_connect_timeout is not None:
        kwargs["socket_connect_timeout"] = config.socket_connect_timeout

    if config.url:
        # The URL is the sole source of truth for the connection target;
        # rediss:// already encodes TLS, so the discrete fields are ignored.
        return config.cluster, config.url, kwargs

    kwargs["host"] = config.host
    kwargs["port"] = config.port
    if config.username:
        kwargs["username"] = config.username
    if config.password:
        kwargs["password"] = config.password
    # Redis Cluster forbids a non-zero db and RedisCluster() rejects the kwarg,
    # so only standalone connections carry it.
    if not config.cluster:
        kwargs["db"] = config.db

    if config.ssl:
        kwargs["ssl"] = True
        for key, value in (
            ("ssl_ca_certs", config.ssl_ca_certs),
            ("ssl_certfile", config.ssl_certfile),
            ("ssl_keyfile", config.ssl_keyfile),
            ("ssl_cert_reqs", config.ssl_cert_reqs),
        ):
            if value is not None:
                kwargs[key] = value

    return config.cluster, None, kwargs


class RedisSource:
    """Streams :class:`RedisRecord` objects from a Redis instance."""

    def __init__(self, config: RedisConfig, client: RedisConnection | None = None):
        self._config = config
        self._cluster = config.cluster
        if client is not None:
            self._client = client
            return

        cluster, url, kwargs = redis_client_params(config)
        if cluster:
            self._client = (
                RedisCluster.from_url(url, **kwargs) if url else RedisCluster(**kwargs)
            )
        else:
            self._client = redis.Redis.from_url(url, **kwargs) if url else redis.Redis(**kwargs)

    @property
    def client(self) -> RedisConnection:
        return self._client

    def ping(self) -> bool:
        return bool(self._client.ping())

    def server_info(self) -> Dict[str, Any]:
        """Gather operationally useful facts about the Redis source.

        Returns a dict with the keyspace size of the configured db, memory
        usage, server version, and the number of keys carrying a TTL. Values
        that cannot be read are simply omitted; this is best-effort and never
        raises so it can run unconditionally before a migration.
        """
        info: Dict[str, Any] = {}
        try:
            dbsize = self._client.dbsize()
            # Cluster dbsize may come back as {node: int}; sum it.
            if isinstance(dbsize, dict):
                dbsize = sum(v for v in dbsize.values() if isinstance(v, int))
            info["keys"] = dbsize
        except Exception as exc:
            logger.debug("could not read Redis dbsize: %s", exc)

        try:
            nodes = self._info_nodes("memory")
            used: List[int] = []
            for n in nodes:
                v = n.get("used_memory")
                if isinstance(v, int):
                    used.append(v)
            if used:
                info["used_memory"] = sum(used)
                # In cluster mode the human-readable per-node value is no longer
                # meaningful; fall back to the single node's value otherwise.
                info["used_memory_human"] = (
                    nodes[0].get("used_memory_human") if len(nodes) == 1 else f"{sum(used)}B"
                )
        except Exception as exc:
            logger.debug("could not read Redis memory info: %s", exc)

        try:
            nodes = self._info_nodes("server")
            for node in nodes:
                if node.get("redis_version"):
                    info["redis_version"] = node["redis_version"]
                    break
        except Exception as exc:
            logger.debug("could not read Redis server info: %s", exc)

        try:
            nodes = self._info_nodes("keyspace")
            expires = 0
            found = False
            for node in nodes:
                db_stats = node.get(f"db{self._config.db}")
                if isinstance(db_stats, dict) and db_stats.get("expires") is not None:
                    expires += db_stats["expires"]
                    found = True
            if found:
                info["expires"] = expires
        except Exception as exc:
            logger.debug("could not read Redis keyspace info: %s", exc)

        return info

    def _info_nodes(self, section: str) -> List[Dict[str, Any]]:
        """Return INFO as a list of per-node dicts.

        Standalone returns a single flat dict; the cluster client returns
        ``{node: info_dict}``. Normalizing to a list lets ``server_info``
        aggregate uniformly.
        """
        raw = self._client.info(section)
        # Only the cluster client returns {node: info_dict}. Guarding on the
        # cluster flag avoids misreading a standalone keyspace section (whose
        # db0 value is itself a dict) as a per-node response.
        if (
            self._cluster
            and isinstance(raw, dict)
            and raw
            and all(isinstance(v, dict) for v in raw.values())
        ):
            return list(raw.values())
        return [raw] if isinstance(raw, dict) else []

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass

    def iter_records(self, batch_size: int = 500) -> Iterator[RedisRecord]:
        """Yield every key in the configured keyspace as a :class:`RedisRecord`."""
        for keys in self._iter_key_batches(batch_size):
            if not keys:
                continue
            types, ttls = self._fetch_types_and_ttls(keys)
            values = self._fetch_values(keys, types)
            for key in keys:
                key_type = types[key]
                # The key may have been deleted between SCAN and read.
                if key_type == "none" or key not in values:
                    continue
                value = values[key]
                # Expiry race: the key vanished between the TYPE and value reads,
                # so the value read came back empty/None. Skip it rather than
                # writing a None or empty bin (which Aerospike rejects/deletes).
                if self._is_vanished(key_type, value):
                    continue
                yield RedisRecord(
                    key=self._decode_key(key),
                    type=key_type,
                    value=value,
                    ttl_ms=ttls[key],
                )

    @staticmethod
    def _is_vanished(key_type: str, value) -> bool:
        # Redis never stores empty collections, so an empty read means the key
        # was deleted/expired mid-flight. An empty string (b"") is still a valid
        # string value and must be kept.
        if key_type == "string":
            return value is None
        if key_type in ("hash", "list", "set", "zset"):
            return not value
        return False

    def _iter_key_batches(self, batch_size: int) -> Iterator[List[bytes]]:
        if self._cluster:
            yield from self._iter_cluster_key_batches(batch_size)
            return
        # Non-cluster path uses synchronous ``Redis.scan``; redis-py 7 stubs
        # type ``scan`` as possibly async, so we assert the real sync return shape.
        sync_client = cast(redis.Redis, self._client)
        cursor = 0
        while True:
            page = cast(
                Tuple[int, List[bytes]],
                sync_client.scan(
                    cursor=cursor, match=self._config.scan_match, count=batch_size
                ),
            )
            cursor, keys = page
            if keys:
                yield list(keys)
            if cursor == 0:
                break

    def _iter_cluster_key_batches(self, batch_size: int) -> Iterator[List[bytes]]:
        # A single-node cursor SCAN only walks one shard's slots; scan_iter is
        # routed by redis-py across every primary node. Chunk the flat stream
        # back into batches so the pipelined reads behave exactly as before.
        batch: List[bytes] = []
        for key in self._client.scan_iter(match=self._config.scan_match, count=batch_size):
            batch.append(key)
            if len(batch) >= batch_size:
                yield batch
                batch = []
        if batch:
            yield batch

    def _fetch_types_and_ttls(self, keys: Iterable[bytes]):
        pipe = self._client.pipeline(transaction=False)
        for key in keys:
            rk = cast(Any, key)
            pipe.type(rk)
            pipe.pttl(rk)
        results = pipe.execute()

        types = {}
        ttls = {}
        for i, key in enumerate(keys):
            raw_type = results[i * 2]
            pttl = results[i * 2 + 1]
            types[key] = self._decode(raw_type)
            # PTTL: -1 -> no expiry, -2 -> key missing. Either way: no TTL.
            ttls[key] = pttl if isinstance(pttl, int) and pttl >= 0 else None
        return types, ttls

    def _fetch_values(self, keys: Iterable[bytes], types):
        pipe = self._client.pipeline(transaction=False)
        ordered_keys: List[bytes] = []
        for key in keys:
            key_type = types[key]
            if key_type == "none":
                continue
            ordered_keys.append(key)
            rk = cast(Any, key)
            if key_type == "string":
                pipe.get(rk)
            elif key_type == "hash":
                pipe.hgetall(rk)
            elif key_type == "list":
                pipe.lrange(rk, 0, -1)
            elif key_type == "set":
                pipe.smembers(rk)
            elif key_type == "zset":
                pipe.zrange(rk, 0, -1, withscores=True)
            else:
                # Unknown/unsupported type (e.g. stream): fetch nothing, drop a
                # placeholder so indices stay aligned.
                pipe.exists(rk)
        results = pipe.execute()
        return dict(zip(ordered_keys, results))

    @staticmethod
    def _decode(value):
        if isinstance(value, bytes):
            return value.decode("utf-8", "replace")
        return value

    @staticmethod
    def _decode_key(key: bytes):
        # Preserve fidelity: UTF-8 keys become str, binary keys stay bytes (a
        # valid Aerospike key type). Lossy "replace" decoding could collapse two
        # distinct binary keys into one and overwrite data.
        if not isinstance(key, bytes):
            return key
        try:
            return key.decode("utf-8")
        except UnicodeDecodeError:
            return key
