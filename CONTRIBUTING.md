# Contributing to redis2aerospike

Thanks for your interest in improving `redis2aerospike`! This repository is a
**personal project** by [Zohar Elkayam](https://github.com/realmgic) (`@realmgic`).
Contributions of all kinds are welcome: bug reports, documentation fixes, and code.

This project is **example / reference software** (see the disclaimer in the
[README](README.md)); there is **no obligation** to triage issues or merge pull
requests on any schedule.

By contributing, you agree that your contributions will be licensed under the
project's [Apache License 2.0](LICENSE).

## Getting started

Requires **Python 3.10+**.

1. Fork the repository and clone your fork.
2. Create and activate a virtual environment:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Install the project in editable mode with the development extras:

   ```bash
   pip install -e ".[dev]"
   ```

   This installs the runtime dependencies plus the dev tooling
   (`pytest`, `testcontainers`, `hypothesis`, `fakeredis`).

If you are new to the tool itself, read the [user guide](docs/README.md) first to
understand how migrations work.

## Running tests

Run the full suite:

```bash
pytest
```

Some tests are marked `integration` and require Docker plus **Redis** and **Valkey**
containers (via testcontainers) and a real **Aerospike** instance. To skip them and run only the fast tests:

```bash
pytest -m "not integration"
```

To run the integration tests locally you need Docker; the suite starts its own
Redis, Valkey, and Aerospike containers (no `docker compose` required for pytest):

```bash
pytest tests/integration -m integration
```

You can still use `docker compose up -d` if you want local services for manual runs.

## Submitting changes

1. Create a branch for your change:

   ```bash
   git checkout -b my-change
   ```

2. Make your change, and add or update tests where it makes sense.
3. Make sure the suite passes (`pytest -m "not integration"` at minimum).
4. If you changed behavior or flags, update the relevant docs under [docs/](docs)
   and the [README](README.md).
5. Commit with a clear message and open a pull request against the original
   repository, describing what changed and why.

## Reporting issues

Open an issue with:

- What you expected to happen and what actually happened.
- Steps to reproduce (commands, config, sample data if possible).
- Versions: Python, `redis2aerospike`, Redis or Valkey, and Aerospike.

Please do not include passwords, tokens, or other secrets in issues or pull
requests.
