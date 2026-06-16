# Redis to Aerospike Migrator

`redis-to-aerospike` is a command-line tool that copies data from **Redis** into
**Aerospike**, converting each Redis value into a **native Aerospike type** as it
goes. It streams keys out of Redis with `SCAN` and writes them with a pool of
worker threads, so it stays fast and memory-bounded even on large keyspaces.

The data model stays key-value to key-value: a Redis key becomes an Aerospike
record ``(namespace, set, primary_key)``, and its value becomes a native type.
With **set routes**, ``set`` and often ``primary_key`` are derived from the route
pattern (see [Transferring data](docs/04-transferring-data.md)); otherwise
``primary_key`` is the full Redis key and ``set`` comes from ``--aerospike-set``.

> **New here?** The [user guide](docs/README.md) has step-by-step instructions
> for installing, connecting each database, transferring data, tuning, and
> troubleshooting.

> **Example software — not for production as-is.** This repository is provided as
> a **reference example** only. **Do not rely on it in production** without your
> own security review, testing, hardening, and operational ownership. Everything
> here is offered **as-is**, with **no warranty**, and **no promise of support,
> maintenance, or ongoing updates.**

## Type mapping

| Redis type | Aerospike representation |
| --- | --- |
| String | Single bin, coerced to `int` -> `float` -> `str` -> `bytes` (blob). |
| Hash | One Map bin (default), or one bin per field (`--hash-strategy field_bins`). |
| List | Aerospike List (order preserved). |
| Set | Aerospike List written with the `ADD_UNIQUE` flag (ordered), enforcing set semantics. |
| Sorted Set | Aerospike Map of `{member: score}`. |
| TTL | Redis ms TTL -> Aerospike second TTL; no expiry -> never-expire. |

Only these types are migrated; other types (e.g. Streams) are skipped and counted
in the run summary. See [Transferring data](docs/04-transferring-data.md) for
details, including TTL boundary handling, large-record limits, **Redis SCAN
filtering** (`scan_match`), and **per-pattern Aerospike set routing** (`set_routes`).

## Key placement

- **Narrow what Redis returns:** `redis.scan_match` in YAML, or `--redis-match` / `--redis-key-pattern` on the CLI (Redis `SCAN` `MATCH` only).
- **Choose the Aerospike set (and optional key suffix) per pattern:** `aerospike.set_routes` in YAML, or repeatable `--set-route PATTERN=SET` (first match wins; a single `*` in the pattern strips fixed literals from the Aerospike user key—see docs).

See [Transferring data](docs/04-transferring-data.md) for details and limitations.

## Install

Requires **Python 3.10+**.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install redis-to-aerospike
```

Verify it installed:

```bash
redis-to-aerospike --help
```

### Develop from source

From a clone of this repository, install in editable mode with the dev extras
(tests and local tooling):

```bash
pip install -e ".[dev]"
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for running the test suite and opening pull
requests. The [getting started guide](docs/01-getting-started.md) also mentions
this install path.

## Quick start

Start throwaway local Redis and Aerospike services (no auth/TLS):

```bash
docker compose up -d
```

Preview what would happen, without writing anything:

```bash
redis-to-aerospike \
  --redis-host localhost --redis-port 6379 \
  --aerospike-host localhost --aerospike-port 3000 \
  --aerospike-namespace test --aerospike-set redis \
  --dry-run
```

Run the migration:

```bash
redis-to-aerospike \
  --redis-host localhost --redis-port 6379 \
  --aerospike-host localhost --aerospike-port 3000 \
  --aerospike-namespace test --aerospike-set redis \
  --workers 8
```

Every flag has a sensible default; run `redis-to-aerospike --help` for the full
list.

### Sample data for migration tests

The script [`scripts/sample_redis_seed.py`](scripts/sample_redis_seed.py) loads **10,000** keys (by default) across all supported Redis types—string, hash, list, set, and sorted set—with mixed values and some expiring strings. Keys are prefixed with `sample:migrate:`.

[`scripts/sample_redis_seed_routing.py`](scripts/sample_redis_seed_routing.py) seeds **`sample:route:`** keys (`user:*`, `session:*`, `cache:*`, `ledger:*`) for **`--set-route`** / `set_routes` demos. **Default is at least 10,000 keys** (`--count`); use `--per-route N` for a smaller fixed layout. With the example routes, Aerospike user keys are the short suffix after each prefix (e.g. ``7`` in set ``users``, not the full Redis key). See the script’s docstring for example CLI and YAML.

```bash
python scripts/sample_redis_seed.py              # default localhost:6379, 10k keys
python scripts/sample_redis_seed.py --flush      # FLUSHDB first, then seed
python scripts/sample_redis_seed.py --count 5000 --host redis.example.com

python scripts/sample_redis_seed_routing.py --flush           # default: ≥10k keys
python scripts/sample_redis_seed_routing.py --count 50000 --flush
python scripts/sample_redis_seed_routing.py --per-route 50   # small fixed layout (262 keys)
```

Then run `redis-to-aerospike` with the same Redis host/port against your Aerospike namespace.

## Configuring the tool

You can configure the tool three ways, and mix them:

- **CLI flags** -- e.g. `--redis-host`, `--workers`. Best for one-off runs.
- **A YAML file** -- pass it with `--config myconfig.yaml`. The YAML is the base;
  any CLI flag you also pass overrides the matching value. See
  [`config.example.yaml`](config.example.yaml) for an annotated template.
- **Environment variables** -- `REDIS_*`, `AEROSPIKE_*`, `MIGRATION_*`. Best for
  secrets and containers.

Some advanced Redis options (ACL username, connection URL, Cluster, TLS) are only
available via YAML or environment variables, not CLI flags. The
[configuration reference](docs/07-configuration-reference.md) lists every option
with its flag, YAML key, env var, and default.

### Connecting securely

The tool supports Redis ACL auth, TLS, connection URLs, and Redis Cluster, and
Aerospike Enterprise security with auth, TLS/mutual TLS, and tuned timeouts.
Passwords are never printed. See:

- [Connecting to Redis](docs/02-connecting-redis.md)
- [Connecting to Aerospike](docs/03-connecting-aerospike.md)

## Reading the output

A run prints, in order:

1. **Preview** -- a summary of both sides and the pipeline settings, before any
   write. `--dry-run` stops here.
2. **Checks** -- warnings based on the Aerospike namespace settings (e.g. TTL
   eviction disabled).
3. **Delimiter** -- the same three-line banner (`redis-to-aerospike: migration`
   between rule lines) is logged **twice**: once right before records are read and
   written, and once right after the write phase finishes (before the summary), so
   you can spot the migration window in a long log file.
4. **Progress** -- a compact heartbeat line every `--progress-interval` seconds.
5. **Summary** -- final counters (scanned, migrated, skipped, errors), timing,
   throughput, and skip/error breakdowns.

Exit codes: `0` success, `1` completed with errors, `2` could not connect. See
[Running and tuning](docs/05-running-and-tuning.md) and
[Troubleshooting](docs/06-troubleshooting.md) for more.

## Documentation

| Guide | What it covers |
| --- | --- |
| [Getting started](docs/01-getting-started.md) | Install, verify, first migration end to end. |
| [Connecting to Redis](docs/02-connecting-redis.md) | Host/port/db, auth, URLs, TLS, Cluster. |
| [Connecting to Aerospike](docs/03-connecting-aerospike.md) | Hosts, namespace/set, auth, TLS, timeouts. |
| [Transferring data](docs/04-transferring-data.md) | Type mapping, TTLs, subsets, re-runs. |
| [Running and tuning](docs/05-running-and-tuning.md) | Config methods, performance, output, exit codes. |
| [Troubleshooting](docs/06-troubleshooting.md) | Common failures and fixes. |
| [Configuration reference](docs/07-configuration-reference.md) | Every flag, YAML key, env var, and default. |

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for how to set
up a development environment, run the tests, and open a pull request.

## Author

Personal project by **[Zohar Elkayam](https://github.com/realmgic)** (@realmgic). It is not an official Aerospike, Inc. product.

## License

Licensed under the Apache License 2.0. See [LICENSE](LICENSE) for the full text.
