# 02 - Connecting to Redis

Redis is the **source** of the migration. The tool reads from it only; it never
writes to or deletes from the source server.

**Valkey** and other **Redis-compatible** (RESP) servers that implement the same
commands (`SCAN`, string/hash/list/set/zset reads, TTLs, and optional Cluster/TLS/ACL
patterns) work the same way: use the same `redis:` settings and point `host` /
`port` (or `url`) at Valkey. The CLI still uses the `--redis-*` names because the
client library speaks the Redis protocol. Integration tests in this repository also
run the end-to-end suite against Valkey in Docker.

## Important: not every option has a CLI flag

Only the most common Redis settings are exposed as command-line flags:

- `--redis-host`, `--redis-port`, `--redis-db`, `--redis-username`, `--redis-password`, `--redis-match`

**Everything else** -- connection URLs, Redis Cluster, and TLS -- must be supplied
through a **YAML config file** (`--config`) or **`REDIS_*` environment variables**.
Each option below notes how it can be set.

## Basic connection

| Setting | CLI flag | YAML key (under `redis:`) | Env var | Default |
| --- | --- | --- | --- | --- |
| Host | `--redis-host` | `host` | `REDIS_HOST` | `localhost` |
| Port | `--redis-port` | `port` | `REDIS_PORT` | `6379` |
| Database number | `--redis-db` | `db` | `REDIS_DB` | `0` |

```bash
redis2aerospike \
  --redis-host redis.internal --redis-port 6379 --redis-db 0 \
  --aerospike-host localhost --aerospike-namespace test --aerospike-set redis
```

## Authentication

| Setting | CLI flag | YAML key | Env var | Notes |
| --- | --- | --- | --- | --- |
| Password | `--redis-password` | `password` | `REDIS_PASSWORD` | Legacy `AUTH` or ACL password. |
| Username | `--redis-username` | `username` | `REDIS_USERNAME` | Redis 6+ ACL user. |

Password-only (legacy `requirepass`):

```bash
export REDIS_PASSWORD='your-redis-password'
redis2aerospike --redis-host redis.internal \
  --aerospike-host localhost --aerospike-namespace test --aerospike-set redis
```

Username + password (Redis 6+ ACLs) via YAML:

```yaml
# redis-acl.yaml
redis:
  host: redis.internal
  port: 6379
  username: migrator
  password: your-redis-password
```

```bash
redis2aerospike --config redis-acl.yaml \
  --aerospike-host localhost --aerospike-namespace test --aerospike-set redis
```

> Tip: keep secrets out of YAML files in source control. You can leave
> `password` out of the file and set `REDIS_PASSWORD` in the environment
> instead -- but note that env vars and `--config` are *separate* paths (see
> [How configuration is resolved](05-running-and-tuning.md#how-configuration-is-resolved)).

## Connection URL (`redis://` / `rediss://`)

Instead of discrete fields you can provide a single URL. When set, the **URL is
the sole source of truth** for the connection target -- the discrete
host/port/db/auth/SSL fields are ignored (socket timeouts still apply). Use
`rediss://` to enable TLS.

- YAML key: `url` &nbsp;|&nbsp; Env var: `REDIS_URL` &nbsp;|&nbsp; *(no CLI flag)*

```yaml
redis:
  url: rediss://migrator:your-password@redis.internal:6380/0
```

## TLS (without a URL)

If you prefer discrete TLS settings over a `rediss://` URL:

| Setting | YAML key | Env var | Notes |
| --- | --- | --- | --- |
| Enable TLS | `ssl` | `REDIS_SSL` | `true`/`false`. |
| CA certificate | `ssl_ca_certs` | `REDIS_SSL_CA_CERTS` | Path to CA bundle. |
| Client certificate | `ssl_certfile` | `REDIS_SSL_CERTFILE` | For mutual TLS. |
| Client key | `ssl_keyfile` | `REDIS_SSL_KEYFILE` | For mutual TLS. |
| Cert requirement | `ssl_cert_reqs` | `REDIS_SSL_CERT_REQS` | One of `required`, `optional`, `none`. |

```yaml
redis:
  host: redis.internal
  port: 6380
  ssl: true
  ssl_ca_certs: /certs/ca.pem
  ssl_cert_reqs: required
```

## Redis Cluster (sharded)

Set `cluster: true` to use the cluster-aware client and cluster-aware scanning.
A single seed host/port (or `url`) is enough for topology discovery. Cluster
mode always uses database `0` (Redis Cluster does not support multiple
databases).

- YAML key: `cluster` &nbsp;|&nbsp; Env var: `REDIS_CLUSTER` &nbsp;|&nbsp; *(no CLI flag)*

```yaml
redis:
  host: redis-cluster-seed.internal
  port: 6379
  cluster: true
```

## Selecting which keys to migrate

By default the tool migrates **every** key (`SCAN MATCH *`). To migrate only a
subset, use a glob pattern:

| Setting | CLI flag | YAML key | Env var | Default |
| --- | --- | --- | --- | --- |
| Key match pattern | `--redis-match` | `scan_match` | `REDIS_SCAN_MATCH` | `*` |

```bash
# Only migrate keys that start with "user:"
redis2aerospike --redis-host redis.internal --redis-match 'user:*' \
  --aerospike-host localhost --aerospike-namespace test --aerospike-set redis
```

See [Transferring data](04-transferring-data.md#choosing-which-keys-to-migrate)
for how the match pattern affects the pre-run key estimate.

## Timeouts

Connection/read timeouts in **seconds** (redis-py convention). YAML/env only:

| Setting | YAML key | Env var |
| --- | --- | --- |
| Socket (read/write) timeout | `socket_timeout` | `REDIS_SOCKET_TIMEOUT` |
| Connect timeout | `socket_connect_timeout` | `REDIS_SOCKET_CONNECT_TIMEOUT` |

## Recipes at a glance

**Standalone, no auth (local/dev):**

```bash
redis2aerospike --redis-host localhost --redis-port 6379 \
  --aerospike-host localhost --aerospike-namespace test --aerospike-set redis
```

**Standalone with ACL + TLS (YAML):**

```yaml
redis:
  url: rediss://migrator:your-password@redis.internal:6380/0
```

**Redis Cluster (YAML):**

```yaml
redis:
  host: redis-cluster-seed.internal
  port: 6379
  cluster: true
```

Next: [Connecting to Aerospike](03-connecting-aerospike.md).
