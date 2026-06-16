# 03 - Connecting to Aerospike

Aerospike is the **target** of the migration. This guide covers where to point
the tool, how records are placed, and how to connect securely to an Enterprise
cluster. Unlike the Redis options, **every Aerospike option has both a CLI flag
and an environment variable** (and a YAML key).

## Hosts and ports

For a single node, use the host/port flags. The default port is `3000`.

| Setting | CLI flag | YAML key | Env var | Default |
| --- | --- | --- | --- | --- |
| Host | `--aerospike-host` | `host` | `AEROSPIKE_HOST` | `localhost` |
| Port | `--aerospike-port` | `port` | `AEROSPIKE_PORT` | `3000` |

```bash
redis-to-aerospike --redis-host localhost \
  --aerospike-host aerospike.internal --aerospike-port 3000 \
  --aerospike-namespace prod --aerospike-set redis
```

### Multiple seed nodes (YAML)

To seed from several nodes, use a `hosts:` list in YAML instead of a single
host/port. Each entry is a `[host, port]` pair:

```yaml
aerospike:
  hosts:
    - [node1.internal, 3000]
    - [node2.internal, 3000]
    - [node3.internal, 3000]
  namespace: prod
  set_name: redis
```

> The CLI only sets a single host/port. For a multi-node seed list, use YAML.

## Where records are placed

Every migrated record is written with the Aerospike key
`(namespace, set, redis_key)`. You control the namespace and set, and the bin
name used for single-value records.

| Setting | CLI flag | YAML key | Env var | Default |
| --- | --- | --- | --- | --- |
| Namespace | `--aerospike-namespace` | `namespace` | `AEROSPIKE_NAMESPACE` | `test` |
| Set | `--aerospike-set` | `set_name` | `AEROSPIKE_SET` | `redis` |
| Value bin name | `--value-bin` | `value_bin` | `AEROSPIKE_VALUE_BIN` | `value` |

The **namespace must already exist** on the server (namespaces are defined in
the Aerospike server configuration, not created by clients). The set is created
on demand.

## Authentication (Enterprise security)

For security-enabled Enterprise clusters:

| Setting | CLI flag | YAML key | Env var |
| --- | --- | --- | --- |
| Username | `--aerospike-username` | `username` | `AEROSPIKE_USERNAME` |
| Password | `--aerospike-password` | `password` | `AEROSPIKE_PASSWORD` |
| Auth mode | `--aerospike-auth-mode` | `auth_mode` | `AEROSPIKE_AUTH_MODE` |

`auth_mode` is one of `internal` (default), `external`, `external_insecure`, or
`pki`. The password is **never printed** -- the pre-run preview masks it as
`***`.

```bash
export ASD_PASSWORD='your-aerospike-password'
redis-to-aerospike --redis-host localhost \
  --aerospike-host secure.example.com --aerospike-port 4333 \
  --aerospike-username admin --aerospike-password "$ASD_PASSWORD" \
  --aerospike-namespace prod --aerospike-set redis
```

## TLS

| Setting | CLI flag | YAML key | Env var |
| --- | --- | --- | --- |
| Enable TLS | `--aerospike-tls-enable` | `tls_enable` | `AEROSPIKE_TLS_ENABLE` |
| TLS name | `--aerospike-tls-name` | `tls_name` | `AEROSPIKE_TLS_NAME` |
| CA file | `--aerospike-tls-cafile` | `tls_cafile` | `AEROSPIKE_TLS_CAFILE` |
| Client cert (mutual TLS) | `--aerospike-tls-certfile` | `tls_certfile` | `AEROSPIKE_TLS_CERTFILE` |
| Client key (mutual TLS) | `--aerospike-tls-keyfile` | `tls_keyfile` | `AEROSPIKE_TLS_KEYFILE` |
| Client key password | `--aerospike-tls-keyfile-pw` | `tls_keyfile_pw` | `AEROSPIKE_TLS_KEYFILE_PW` |

Key points:

- `--aerospike-tls-name` is the **server certificate's subject name** and is
  applied to every host. It must match what the server presents, or the
  handshake fails.
- **Mutual TLS** additionally requires the client `certfile` and `keyfile` (and
  `keyfile_pw` if the key is encrypted).

```bash
# TLS + authentication
redis-to-aerospike --redis-host localhost \
  --aerospike-host secure.example.com --aerospike-port 4333 \
  --aerospike-username admin --aerospike-password "$ASD_PASSWORD" \
  --aerospike-tls-enable --aerospike-tls-name secure.example.com \
  --aerospike-tls-cafile /certs/ca.pem \
  --aerospike-namespace prod --aerospike-set redis
```

## Timeouts

All Aerospike timeouts are in **milliseconds**; `0` means "client default / no
timeout".

| Setting | CLI flag | YAML key | Env var | Default |
| --- | --- | --- | --- | --- |
| Socket timeout | `--aerospike-socket-timeout-ms` | `socket_timeout_ms` | `AEROSPIKE_SOCKET_TIMEOUT_MS` | `0` |
| Total timeout | `--aerospike-total-timeout-ms` | `total_timeout_ms` | `AEROSPIKE_TOTAL_TIMEOUT_MS` | `0` |
| Connect timeout | `--aerospike-connect-timeout-ms` | `connect_timeout_ms` | `AEROSPIKE_CONNECT_TIMEOUT_MS` | `1000` |
| Login timeout | `--aerospike-login-timeout-ms` | `login_timeout_ms` | `AEROSPIKE_LOGIN_TIMEOUT_MS` | `5000` |

## Cloud / NAT / Docker connectivity

When the cluster advertises internal addresses you can't reach directly (common
behind NAT, in cloud VPCs, or from outside Docker), tell the client to use the
server's **alternate-access** address:

| Setting | CLI flag | YAML key | Env var | Default |
| --- | --- | --- | --- | --- |
| Use alternate services | `--aerospike-use-services-alternate` | `use_services_alternate` | `AEROSPIKE_USE_SERVICES_ALTERNATE` | `false` |

```bash
redis-to-aerospike --redis-host localhost \
  --aerospike-host public.example.com --aerospike-port 3000 \
  --aerospike-use-services-alternate \
  --aerospike-namespace prod --aerospike-set redis
```

## Storing the primary key with each record

By default Aerospike stores only the *digest* of the key, not the original key
value. To store the original Redis key alongside each record (so you can read it
back), enable `send-key`:

| Setting | CLI flag | YAML key | Env var | Default |
| --- | --- | --- | --- | --- |
| Send key | `--aerospike-send-key` | `send_key` | `AEROSPIKE_SEND_KEY` | `false` |

## A note on on/off flags

`--aerospike-tls-enable`, `--aerospike-use-services-alternate`, and
`--aerospike-send-key` are **on-only** switches: passing them on the command
line turns the option **on**. There is no `--no-...` form. To explicitly turn one
**off** when a YAML file enables it, edit the YAML (`tls_enable: false`).

## Recipes at a glance

**Local, no auth (the Docker compose instance):**

```bash
redis-to-aerospike --redis-host localhost \
  --aerospike-host localhost --aerospike-port 3000 \
  --aerospike-namespace test --aerospike-set redis
```

**Enterprise, TLS + auth:** see the [TLS](#tls) example above.

**Multi-node cluster (YAML):** see the [`hosts:` list](#multiple-seed-nodes-yaml)
above.

Next: [Transferring data](04-transferring-data.md).
