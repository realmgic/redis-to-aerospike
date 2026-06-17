"""Security-enabled connection test.

This is the only integration test that runs against a security-enabled Aerospike
instance. It uses the same enterprise image as the rest of the suite (which ships
an embedded single-node feature key) but supplies a custom config that enables
security, then verifies the new username/password connection path end to end.

The config is mounted read-only under ``/opt/aerospike/etc/`` and passed with
``--config-file`` (see Aerospike Docker docs). Mounting directly over
``/etc/aerospike/aerospike.conf`` without that flag fails because the image
entrypoint rewrites that path in place.
"""

from __future__ import annotations

import os
import time

import aerospike
import pytest

from redis_to_aerospike.aerospike_sink import AerospikeSink
from redis_to_aerospike.config import AerospikeConfig
from redis_to_aerospike.models import AerospikeRecord

from testcontainers.core.container import DockerContainer  # noqa: E402

pytestmark = pytest.mark.integration

ENTERPRISE_IMAGE = "aerospike/aerospike-server-enterprise:latest"
NAMESPACE = "test"
SET_NAME = "redis"
ADMIN_USER = "admin"
ADMIN_PASSWORD = "admin"

_SECURE_CONF_HOST = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "resources", "aerospike-secure.conf")
)
# In-container path must match ``docker run ... --config-file <path>``.
_SECURE_CONF_CONTAINER = "/opt/aerospike/etc/aerospike.conf"


def _wait_for_secure_aerospike(host: str, port: int, timeout: int = 120) -> None:
    """Wait until the server accepts an authenticated admin connection."""
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            client = aerospike.client(
                {"hosts": [(host, port)], "user": ADMIN_USER, "password": ADMIN_PASSWORD}
            ).connect()
            client.close()
            return
        except Exception as exc:  # not ready yet
            last_err = exc
            time.sleep(1)
    raise RuntimeError(f"secure Aerospike did not become ready in {timeout}s: {last_err}")


def _grant_admin_read_write(host: str, port: int) -> None:
    """Ensure built-in ``admin`` can read/write data (RBAC).

    With security enabled, the default ``admin`` user only has ``user-admin``.
    The Python client's ``admin_grant_roles`` needs ``sys-admin`` on that user
    before ``read-write`` can be attached; then data operations succeed.
    """
    client = aerospike.client(
        {"hosts": [(host, port)], "user": ADMIN_USER, "password": ADMIN_PASSWORD}
    ).connect()
    try:
        info = client.admin_query_user_info(ADMIN_USER)
        roles = set(info.get("roles") or [])
        if "read-write" in roles:
            return
        if "sys-admin" not in roles:
            client.admin_grant_roles(ADMIN_USER, ["sys-admin"])
            info = client.admin_query_user_info(ADMIN_USER)
            roles = set(info.get("roles") or [])
        if "read-write" not in roles:
            client.admin_grant_roles(ADMIN_USER, ["read-write"])
    finally:
        client.close()


@pytest.fixture(scope="module")
def secure_aerospike_container():
    container = (
        DockerContainer(ENTERPRISE_IMAGE)
        .with_exposed_ports(3000, 3001, 3002)
        .with_volume_mapping(_SECURE_CONF_HOST, _SECURE_CONF_CONTAINER, "ro")
        .with_command(["--config-file", _SECURE_CONF_CONTAINER])
    )
    container.start()
    try:
        host = container.get_container_host_ip()
        port = int(container.get_exposed_port(3000))
        _wait_for_secure_aerospike(host, port)
        _grant_admin_read_write(host, port)
        yield {"host": host, "port": port, "namespace": NAMESPACE}
    finally:
        container.stop()


def _config(secure_aerospike_container, **overrides) -> AerospikeConfig:
    return AerospikeConfig(
        hosts=[(secure_aerospike_container["host"], secure_aerospike_container["port"])],
        namespace=secure_aerospike_container["namespace"],
        set_name=SET_NAME,
        **overrides,
    )


def test_connects_and_writes_with_username_password(secure_aerospike_container):
    config = _config(secure_aerospike_container, username=ADMIN_USER, password=ADMIN_PASSWORD)

    sink = AerospikeSink(config).connect()
    try:
        sink.write(AerospikeRecord(key="secure-key", bins={"value": "hi"}))
    finally:
        sink.close()

    reader = aerospike.client(
        {
            "hosts": config.hosts,
            "user": ADMIN_USER,
            "password": ADMIN_PASSWORD,
        }
    ).connect()
    try:
        _, _, bins = reader.get((NAMESPACE, SET_NAME, "secure-key"))
        assert bins["value"] == "hi"
    finally:
        reader.close()


# @pytest.mark.skip(
#     reason=(
#         "Aerospike EE 8.x with only an empty `security {}` block still accepts the Python "
#         "client without credentials for connect/data ops in this image; enforcing anonymous "
#         "rejection needs extra RBAC/session policy beyond this smoke fixture."
#     )
# )
def test_connect_without_credentials_is_rejected(secure_aerospike_container):
    # Same secured instance, but no username/password -> auth must be enforced.
    config = _config(secure_aerospike_container)
    with pytest.raises(Exception):
        AerospikeSink(config).connect()
