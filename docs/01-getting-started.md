# 01 - Getting started

This guide takes you from nothing to a completed migration. If you just want to
try the tool out, you can do the whole thing locally with Docker in a few
minutes.

## Prerequisites

- **Python 3.10 or newer.** The bundled Aerospike client ships prebuilt wheels
  for CPython 3.10-3.14 on Linux, macOS, and Windows. (Python 3.9 and earlier
  are not supported.)
  - If no prebuilt wheel exists for your platform, `pip` will try to build the
    Aerospike client from source, which needs a C toolchain. See the
    [Aerospike Python client docs](https://aerospike.com/docs/develop/client/python)
    if you hit a build error.
- **Network access** from the machine running the tool to both your Redis-compatible
  source (Redis, Valkey, or another RESP-compatible server) and your Aerospike cluster.
- **(Optional) Docker**, only if you want to spin up throwaway local Redis and
  Aerospike services to experiment with.

## Install

Install into a virtual environment so the tool and its dependencies stay
isolated:

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install redis2aerospike
```

This installs a command named `redis2aerospike` onto your `PATH`.

> Working from a source checkout instead of the published package? Use
> `pip install -e ".[dev]"` from the repository root. Everything in these docs
> works the same way afterward.

## Verify the install

```bash
redis2aerospike --help
```

You should see the usage text with grouped options (Redis source, Aerospike
sink, Pipeline). If the command is "not found", make sure your virtual
environment is still activated.

## Spin up local services (optional, for a trial run)

The repository ships a `docker-compose.yml` that starts a local **Redis** and
**Valkey** (both on the default port inside the container) plus a local Aerospike
with no authentication or TLS -- perfect for a first run:

```bash
docker compose up -d
```

This gives you:

- **Redis 7** on `localhost:6379`
- **Valkey 8** on `localhost:6380` (same wire protocol; point `--redis-host` /
  `--redis-port` at Valkey if you want to migrate from it instead of Redis)
- **Aerospike** with a namespace named `test`, reachable on `localhost:3000`

Put a couple of keys in Redis so there's something to migrate:

```bash
docker compose exec redis redis-cli SET greeting "hello"
docker compose exec redis redis-cli HSET user:1 name "Ada" role "admin"
docker compose exec redis redis-cli RPUSH colors red green blue
```

## Step 1: Preview with `--dry-run`

Always do a dry run first. It connects to both sides, prints a preview of what
*would* happen, and exits **without writing anything**. It's the quickest way to
confirm your connection settings are right.

```bash
redis2aerospike \
  --redis-host localhost --redis-port 6379 \
  --aerospike-host localhost --aerospike-port 3000 \
  --aerospike-namespace test --aerospike-set redis \
  --dry-run
```

You'll see a `migration preview` block showing the Redis endpoint and key count,
the Aerospike target, and the pipeline settings. If this fails to connect, fix
the connection before continuing -- see [Connecting to Redis](02-connecting-redis.md)
and [Connecting to Aerospike](03-connecting-aerospike.md).

## Step 2: Run the migration

Drop `--dry-run` and (optionally) set the number of worker threads:

```bash
redis2aerospike \
  --redis-host localhost --redis-port 6379 \
  --aerospike-host localhost --aerospike-port 3000 \
  --aerospike-namespace test --aerospike-set redis \
  --workers 8
```

While it runs you'll see a periodic `progress:` line, and at the end a
`migration summary` with how many keys were scanned, migrated, skipped, or
errored.

## Step 3: Confirm the data landed

```bash
docker compose exec aerospike asadm -e "show stat namespace test"
# or inspect a single record with aql, if installed:
# aql -c "SELECT * FROM test.redis WHERE PK = 'greeting'"
```

## What's next

- Understand exactly **what gets copied and how** in
  [Transferring data](04-transferring-data.md).
- Learn to **read the output and tune throughput** in
  [Running and tuning](05-running-and-tuning.md).
- Hit a problem? Jump to [Troubleshooting](06-troubleshooting.md).

When you're done experimenting, tear down the local services with
`docker compose down`.
