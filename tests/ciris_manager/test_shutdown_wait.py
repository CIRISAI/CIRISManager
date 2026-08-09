"""Tests for waiting on an agent container to stop during deployment.

`_wait_for_container_stop` shelled out to the LOCAL docker CLI and treated a
failed inspect as success:

    if result.returncode != 0:
        return True          # "not found or error" -> reported as stopped

Every server is `is_local: false` and the manager host runs no agent
containers, so the inspect always failed there and the function returned True
on its first poll. The 60s timeout never applied. Production logs:

    02:28:16  Waiting for container ciris-datum to stop...
    02:28:16  Container ciris-datum stopped, recreating with new image...

The caller then recreated the container, hard-stopping it ~10s later while the
agent was mid-way through an LLM-driven shutdown ritual - stranding its thought
in PROCESSING on every deployment (CIRISAgent#1018).

The invariant: only an OBSERVED terminal state or a genuine NotFound counts as
stopped. "I could not reach the server" must never be reported as "it stopped".
"""

from unittest.mock import MagicMock

import docker.errors
import pytest

from ciris_manager.deployment.orchestrator import (
    CONTAINER_STOP_GRACE_SECONDS,
    SHUTDOWN_WAIT_SECONDS,
    DeploymentOrchestrator,
)


def _orch(container=None, raises=None):
    orch = DeploymentOrchestrator.__new__(DeploymentOrchestrator)
    client = MagicMock()
    if raises is not None:
        client.containers.get.side_effect = raises
    else:
        client.containers.get.return_value = container
    manager = MagicMock()
    manager.docker_client.get_client.return_value = client
    orch.manager = manager
    return orch, manager


def _container(status):
    c = MagicMock()
    c.status = status
    c.reload = MagicMock()
    return c


@pytest.mark.asyncio
async def test_observed_exited_is_stopped():
    orch, _ = _orch(_container("exited"))
    assert await orch._wait_for_container_stop("ciris-datum", timeout=5, server_id="main") is True


@pytest.mark.asyncio
async def test_absent_container_is_stopped():
    orch, _ = _orch(raises=docker.errors.NotFound("gone"))
    assert await orch._wait_for_container_stop("ciris-datum", timeout=5, server_id="main") is True


@pytest.mark.asyncio
async def test_unreachable_server_is_not_reported_as_stopped():
    """The exact old bug: an error must not mean "stopped".

    Returning True here is what let the deployment kill a still-running agent
    one second after asking it to shut down.
    """
    orch, _ = _orch(raises=RuntimeError("TLS handshake failed"))
    assert await orch._wait_for_container_stop("ciris-datum", timeout=3, server_id="main") is False


@pytest.mark.asyncio
async def test_still_running_times_out_rather_than_lying():
    orch, _ = _orch(_container("running"))
    assert await orch._wait_for_container_stop("ciris-datum", timeout=3, server_id="main") is False


@pytest.mark.asyncio
async def test_checks_the_agents_own_server_not_the_local_socket():
    """The container lives on a remote host; we must ask that host."""
    orch, manager = _orch(_container("exited"))
    await orch._wait_for_container_stop("ciris-scout-x-002", timeout=5, server_id="scout2")
    manager.docker_client.get_client.assert_called_once_with("scout2")


@pytest.mark.asyncio
async def test_no_manager_cannot_confirm_stopped():
    orch = DeploymentOrchestrator.__new__(DeploymentOrchestrator)
    orch.manager = None
    assert await orch._wait_for_container_stop("ciris-datum", timeout=2) is False


def test_timeouts_allow_for_an_llm_driven_shutdown():
    """Shutdown is model round-trips, not a process signal.

    A seconds-scale budget guarantees the kill lands mid-thought.
    """
    assert SHUTDOWN_WAIT_SECONDS >= 120
    assert CONTAINER_STOP_GRACE_SECONDS > 10
