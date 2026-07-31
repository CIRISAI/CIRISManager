"""Tests for compose-file write durability.

Found 2026-07-31 while trying to move agents onto a new LLM provider.

`regenerate_agent_compose` wrote the compose file for a remote server ONLY via
`docker exec` into ciris-nginx, on the documented assumption that the container
bind-mounts /opt/ciris. It does not - it mounts /etc/letsencrypt, nginx.conf and
the static dir. So the write landed in the container's ephemeral layer, the exec
returned 0, the manager logged "Synced compose file", and the host file never
changed. Meanwhile the manager's own local copy - the one the deployment
orchestrator reads to build the environment for a recreated container - was
skipped entirely.

Net effect: no LLM or adapter configuration change ever reached an agent on a
remote server, and every attempt reported success.

Two invariants protect against that recurring:
  1. The manager's local copy is always written; it is authoritative.
  2. The remote mirror is verified by reading back, so an unmounted write is
     reported as a failed mirror rather than a success.
"""

import hashlib
from unittest.mock import MagicMock

import pytest
import yaml


class _Exec:
    """Stand-in for docker exec_run results."""

    def __init__(self, exit_code, output=b""):
        self.exit_code = exit_code
        self.output = output


class _NginxNoMount:
    """nginx container whose writes do NOT reach the host (no bind mount).

    Accepts the write (exit 0) but a read-back returns nothing, exactly like a
    write into a layer the host cannot see.
    """

    def __init__(self):
        self.writes = 0

    def exec_run(self, cmd, user=None):
        joined = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        if "base64 -d" in joined:
            self.writes += 1
            return _Exec(0)
        if "md5sum" in joined:
            return _Exec(0, b"\n")  # file not visible
        return _Exec(1)


class _NginxWithMount:
    """nginx container whose writes DO reach the host."""

    def __init__(self, content: str):
        self.content = content

    def exec_run(self, cmd, user=None):
        joined = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        if "base64 -d" in joined:
            return _Exec(0)
        if "md5sum" in joined:
            digest = hashlib.md5(self.content.encode()).hexdigest()
            return _Exec(0, digest.encode() + b"\n")
        return _Exec(1)


def _manager_with(container):
    from ciris_manager.manager import CIRISManager

    mgr = CIRISManager.__new__(CIRISManager)  # bypass heavy __init__
    client = MagicMock()
    client.containers.get.return_value = container
    docker_client = MagicMock()
    docker_client.get_client.return_value = client
    mgr.docker_client = docker_client
    return mgr


@pytest.mark.asyncio
async def test_unverifiable_remote_write_is_reported_as_failure():
    """A write into a non-bind-mounted path must NOT report success.

    This is the exact production condition: exec succeeds, host unchanged.
    """
    container = _NginxNoMount()
    mgr = _manager_with(container)

    ok = await mgr._sync_compose_to_remote_server(
        "main", "/opt/ciris/agents/datum/docker-compose.yml", {"services": {"datum": {}}}
    )

    assert container.writes == 1, "it should still attempt the write"
    assert ok is False, "an unverifiable write must not be reported as synced"


@pytest.mark.asyncio
async def test_verified_remote_write_reports_success():
    config = {"services": {"datum": {"image": "x"}}}
    content = yaml.dump(config, default_flow_style=False, sort_keys=False, width=120)
    mgr = _manager_with(_NginxWithMount(content))

    ok = await mgr._sync_compose_to_remote_server(
        "main", "/opt/ciris/agents/datum/docker-compose.yml", config
    )
    assert ok is True


@pytest.mark.asyncio
async def test_failed_exec_reports_failure():
    class _Broken:
        def exec_run(self, cmd, user=None):
            return _Exec(1, b"permission denied")

    mgr = _manager_with(_Broken())
    ok = await mgr._sync_compose_to_remote_server("main", "/tmp/x.yml", {"services": {}})
    assert ok is False


# -----------------------------------------------------------------------------
# Port allocation must not depend on the host's network state
# -----------------------------------------------------------------------------


def test_port_allocation_is_independent_of_host_sockets():
    """Allocation must be deterministic regardless of what the host is running.

    `PortManager.allocate_port` calls `_is_port_in_use`, which opens a real
    socket against the test machine. When something held :8080 locally, tests
    asserting `port == 8080` failed; when it was released they passed. On a CI
    runner that is a coin flip, and it presented as an ordering bug rather than
    an environmental one.

    The autouse `_no_host_port_probing` fixture in tests/conftest.py neutralises
    the probe. This test fails if that fixture is removed while something holds
    the first port in the range.
    """
    import socket
    import tempfile
    from pathlib import Path

    from ciris_manager.port_manager import PortManager

    holder = socket.socket()
    holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        holder.bind(("127.0.0.1", 8080))
        holder.listen(1)
    except OSError:
        holder.close()
        pytest.skip("could not bind :8080 to simulate an occupied host port")

    try:
        with tempfile.TemporaryDirectory() as d:
            pm = PortManager(
                start_port=8080, end_port=8090, metadata_path=Path(d) / "metadata.json"
            )
            assert pm.allocate_port("agent-a") == 8080, (
                "allocation consulted the host's real sockets; the "
                "_no_host_port_probing fixture is not in effect"
            )
    finally:
        holder.close()
