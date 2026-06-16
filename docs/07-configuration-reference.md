# 07 - Configuration reference

Every option the tool accepts, grouped by section, with its CLI flag, YAML key,
environment variable, and default. For how these sources combine, see
[How configuration is resolved](05-running-and-tuning.md#how-configuration-is-resolved).
The canonical annotated YAML template is [`config.example.yaml`](../config.example.yaml).

## How to read this reference

- **CLI flag** -- pass on the command line. A dash (`-`) means there is no flag
  for this option; use YAML or an environment variable instead.
- **YAML key** -- the key in a `--config` file. Redis keys go under a `redis:`
  section, Aerospike keys under `aerospike:`, and pipeline keys at the top level.
- **Env var** -- an environment variable read by the tool's defaults path.
- **Default** -- the built-in value used when you set the option nowhere.

## Redis source (YAML section: `redis:`)

> Only host, port, db, password, and match have CLI flags. All other Redis
> options are **YAML- or environment-only**.

| Option | CLI flag | YAML key | Env var | Default |
| --- | --- | --- | --- | --- |
| Host | `--redis-host` | `host` | `REDIS_HOST` | `localhost` |
| Port | `--redis-port` | `port` | `REDIS_PORT` | `6379` |
| Database number | `--redis-db` | `db` | `REDIS_DB` | `0` |
| Password | `--redis-password` | `password` | `REDIS_PASSWORD` | none |
| Key match pattern | `--redis-match` | `scan_match` | `REDIS_SCAN_MATCH` | `*` |
| Username (ACL) | - | `username` | `REDIS_USERNAME` | none |
| Connection URL | - | `url` | `REDIS_URL` | none |
| Cluster mode | - | `cluster` | `REDIS_CLUSTER` | `false` |
| Enable TLS | - | `ssl` | `REDIS_SSL` | `false` |
| TLS CA certs | - | `ssl_ca_certs` | `REDIS_SSL_CA_CERTS` | none |
| TLS client cert | - | `ssl_certfile` | `REDIS_SSL_CERTFILE` | none |
| TLS client key | - | `ssl_keyfile` | `REDIS_SSL_KEYFILE` | none |
| TLS cert requirement | - | `ssl_cert_reqs` | `REDIS_SSL_CERT_REQS` | none (`required`/`optional`/`none`) |
| Socket timeout (s) | - | `socket_timeout` | `REDIS_SOCKET_TIMEOUT` | none |
| Connect timeout (s) | - | `socket_connect_timeout` | `REDIS_SOCKET_CONNECT_TIMEOUT` | none |

Notes:

- When `url` is set it is the **sole source of truth** for the connection target;
  the discrete host/port/db/auth/SSL fields are ignored (timeouts still apply).
  Use `rediss://` for TLS.
- `cluster: true` always uses database `0`.

## Aerospike sink (YAML section: `aerospike:`)

> Every Aerospike option has a CLI flag **and** an environment variable.

| Option | CLI flag | YAML key | Env var | Default |
| --- | --- | --- | --- | --- |
| Host | `--aerospike-host` | `host` | `AEROSPIKE_HOST` | `localhost` |
| Port | `--aerospike-port` | `port` | `AEROSPIKE_PORT` | `3000` |
| Seed node list | - | `hosts` | - | single host/port |
| Namespace | `--aerospike-namespace` | `namespace` | `AEROSPIKE_NAMESPACE` | `test` |
| Set | `--aerospike-set` | `set_name` | `AEROSPIKE_SET` | `redis` |
| Value bin name | `--value-bin` | `value_bin` | `AEROSPIKE_VALUE_BIN` | `value` |
| Max record size (bytes) | - | `max_record_size` | `AEROSPIKE_MAX_RECORD_SIZE` | `8388608` (8 MiB) |
| Max TTL (s) | `--max-ttl` | `max_ttl` | `AEROSPIKE_MAX_TTL` | `315360000` (10y); `0` disables |
| Username | `--aerospike-username` | `username` | `AEROSPIKE_USERNAME` | none |
| Password | `--aerospike-password` | `password` | `AEROSPIKE_PASSWORD` | none |
| Auth mode | `--aerospike-auth-mode` | `auth_mode` | `AEROSPIKE_AUTH_MODE` | `internal` |
| Enable TLS | `--aerospike-tls-enable` | `tls_enable` | `AEROSPIKE_TLS_ENABLE` | `false` |
| TLS name | `--aerospike-tls-name` | `tls_name` | `AEROSPIKE_TLS_NAME` | none |
| TLS CA file | `--aerospike-tls-cafile` | `tls_cafile` | `AEROSPIKE_TLS_CAFILE` | none |
| TLS client cert | `--aerospike-tls-certfile` | `tls_certfile` | `AEROSPIKE_TLS_CERTFILE` | none |
| TLS client key | `--aerospike-tls-keyfile` | `tls_keyfile` | `AEROSPIKE_TLS_KEYFILE` | none |
| TLS client key password | `--aerospike-tls-keyfile-pw` | `tls_keyfile_pw` | `AEROSPIKE_TLS_KEYFILE_PW` | none |
| Socket timeout (ms) | `--aerospike-socket-timeout-ms` | `socket_timeout_ms` | `AEROSPIKE_SOCKET_TIMEOUT_MS` | `0` |
| Total timeout (ms) | `--aerospike-total-timeout-ms` | `total_timeout_ms` | `AEROSPIKE_TOTAL_TIMEOUT_MS` | `0` |
| Connect timeout (ms) | `--aerospike-connect-timeout-ms` | `connect_timeout_ms` | `AEROSPIKE_CONNECT_TIMEOUT_MS` | `1000` |
| Login timeout (ms) | `--aerospike-login-timeout-ms` | `login_timeout_ms` | `AEROSPIKE_LOGIN_TIMEOUT_MS` | `5000` |
| Use alternate services | `--aerospike-use-services-alternate` | `use_services_alternate` | `AEROSPIKE_USE_SERVICES_ALTERNATE` | `false` |
| Send key with record | `--aerospike-send-key` | `send_key` | `AEROSPIKE_SEND_KEY` | `false` |

Notes:

- Use **either** `host`/`port` **or** a `hosts:` list of `[host, port]` pairs in
  YAML; the list takes precedence when present. The CLI only sets a single
  host/port.
- `auth_mode` is one of `internal`, `external`, `external_insecure`, `pki`.
- `tls_name` is applied to every host as the server certificate subject name.

## Pipeline (YAML: top level)

| Option | CLI flag | YAML key | Env var | Default |
| --- | --- | --- | --- | --- |
| Worker threads | `--workers` | `workers` | `MIGRATION_WORKERS` | `8` |
| Scan batch size | `--scan-batch` | `scan_batch` | `MIGRATION_SCAN_BATCH` | `500` |
| Queue size | `--queue-size` | `queue_size` | `MIGRATION_QUEUE_SIZE` | `10000` |
| Scan rate limit (records/s) | `--scan-rate-limit` | `scan_rate_limit` | `MIGRATION_SCAN_RATE_LIMIT` | `0` (unlimited) |
| Write rate limit (records/s) | `--write-rate-limit` | `write_rate_limit` | `MIGRATION_WRITE_RATE_LIMIT` | `0` (unlimited) |
| Write batch size | `--write-batch-size` | `write_batch_size` | `MIGRATION_WRITE_BATCH_SIZE` | `1` (single writes) |
| Hash strategy | `--hash-strategy` | `hash_strategy` | `MIGRATION_HASH_STRATEGY` | `map_bin` (`map_bin`/`field_bins`) |
| TTL overflow policy | `--ttl-overflow-policy` | `ttl_overflow_policy` | `MIGRATION_TTL_OVERFLOW_POLICY` | `reject` (`reject`/`clamp`/`never_expire`) |
| Progress interval (s) | `--progress-interval` | `progress_interval` | `MIGRATION_PROGRESS_INTERVAL` | `10`; `0` disables |

Notes:

- The rate limits are optional throttles in records/second; `0` (the default)
  means no throttling. `scan_rate_limit` caps how fast keys are pulled from
  Redis (slowing `SCAN`), and `write_rate_limit` caps the aggregate insert rate
  into Aerospike across all worker threads. Use them to keep a migration from
  overwhelming a busy source or target. Each allows a short burst of up to one
  second's worth of the configured rate.
- `write_batch_size > 1` inserts records using Aerospike `batch_write` instead of
  one write per record, cutting round-trips on large migrations. Each record in a
  batch keeps its own TTL and is checked individually, so one failing record does
  not fail its batch mates. The write rate limit still counts individual records,
  so `--write-rate-limit` bounds real load even when batched. `1` (the default)
  keeps the one-write-per-record path. Batching is per-worker, so up to
  `workers * write_batch_size` records may be buffered in memory at once; keep
  that product well below `queue_size`.

## Run-control flags (CLI only)

These control a single run and have no YAML key or environment variable:

| Option | CLI flag | Default | Notes |
| --- | --- | --- | --- |
| Config file | `--config` | none | Path to a YAML base config. |
| Dry run | `--dry-run` | off | Connect, preview, exit without writing. |
| Log level | `--log-level` | `INFO` | One of `DEBUG`, `INFO`, `WARNING`, `ERROR`. |

## On/off flag caveat

`--aerospike-tls-enable`, `--aerospike-send-key`,
`--aerospike-use-services-alternate`, and `--dry-run` are on-only switches:
passing them turns the option **on**. To explicitly disable an option that a
YAML file turns on, set it to `false` in the YAML (there is no `--no-...` form).

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Completed with no errors. |
| `1` | Completed, but with one or more errors. |
| `2` | Could not connect to Redis or Aerospike. |
