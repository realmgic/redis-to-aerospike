"""Integration fixtures: spin up Redis (or Valkey) and Aerospike via testcontainers.

These tests need Docker. When Docker (or the optional client libraries) are
unavailable, the whole module is skipped so the unit suite stays runnable
everywhere.

Redis and Valkey each get a session-scoped container; tests import the client
fixture they need (``redis_client`` vs ``valkey_client``).
"""

from __future__ import annotations

import time

import pytest

# Optional dependencies / runtime: skip the entire integration suite if missing.
redis = pytest.importorskip("redis")
aerospike = pytest.importorskip("aerospike")
pytest.importorskip("testcontainers")

from testcontainers.core.container import DockerContainer  # noqa: E402
from testcontainers.core.wait_strategies import LogMessageWaitStrategy  # noqa: E402

# Enterprise image ships an embedded single-node feature key, so it runs without
# an external feature-key file. It is used for the whole integration suite; the
# default fixture leaves security OFF, while the dedicated security test enables
# it (see test_secure_connection.py).
AEROSPIKE_IMAGE = "aerospike/aerospike-server-enterprise:latest"
REDIS_IMAGE = "redis:7"
# Valkey is wire-compatible with the commands this migrator uses; integration
# tests exercise the same scenarios against a Valkey container.
VALKEY_IMAGE = "valkey/valkey:8"
AEROSPIKE_NAMESPACE = "test"


def _docker_available() -> bool:
    try:
        # pyrefly: ignore [untyped-import]
        import docker  # noqa: F401

        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


if not _docker_available():  # pragma: no cover - environment dependent
    pytest.skip("Docker is not available; skipping integration tests", allow_module_level=True)


@pytest.fixture(scope="session")
def redis_container():
    container = (
        DockerContainer(REDIS_IMAGE)
        .with_exposed_ports(6379)
        .waiting_for(
            LogMessageWaitStrategy("Ready to accept connections").with_startup_timeout(60)
        )
    )
    container.start()
    try:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(6379)
        yield {"host": host, "port": port}
    finally:
        container.stop()


@pytest.fixture(scope="session")
def aerospike_container():
    container = DockerContainer(AEROSPIKE_IMAGE).with_exposed_ports(3000, 3001, 3002)
    container.start()
    try:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(3000)
        _wait_for_aerospike(host, port)
        yield {"host": host, "port": port, "namespace": AEROSPIKE_NAMESPACE}
    finally:
        container.stop()


def _wait_for_aerospike(host: str, port: int, timeout: int = 90) -> None:
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            client = aerospike.client({"hosts": [(host, port)]}).connect()
            client.close()
            return
        except Exception as exc:  # not ready yet
            last_err = exc
            time.sleep(1)
    raise RuntimeError(f"Aerospike did not become ready in {timeout}s: {last_err}")


@pytest.fixture()
def redis_client(redis_container):
    client = redis.Redis(
        host=redis_container["host"],
        port=redis_container["port"],
        db=0,
        decode_responses=False,
    )
    client.flushall()
    yield client
    client.flushall()
    client.close()


@pytest.fixture(scope="session")
def valkey_container():
    container = (
        DockerContainer(VALKEY_IMAGE)
        .with_exposed_ports(6379)
        .waiting_for(
            LogMessageWaitStrategy("Ready to accept connections").with_startup_timeout(60)
        )
    )
    container.start()
    try:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(6379)
        yield {"host": host, "port": port}
    finally:
        container.stop()


@pytest.fixture()
def valkey_client(valkey_container):
    client = redis.Redis(
        host=valkey_container["host"],
        port=valkey_container["port"],
        db=0,
        decode_responses=False,
    )
    client.flushall()
    yield client
    client.flushall()
    client.close()
