"""Cancelling a deployment must stop it acting on agents.

Regression test for CIRISManager#24. `cancel_stuck_deployment` set
`status = "cancelled"` and cleared the lock, but never touched the running
task. The task kept walking its canary phases: a canary cancelled at 22:34
went on to request shutdown of two production agents at 22:55. Both accepted,
tore down their adapters and API, and - because they could not self-exit -
sat in `running` containers with nothing listening, for twenty minutes,
while the manager reported them healthy.

Two layers are tested, because `Task.cancel()` alone is not sufficient: it
only takes effect at the next await point, and a group update gathers across
every agent in the phase.
"""

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from unittest.mock import AsyncMock

from ciris_manager.models import UpdateNotification, AgentInfo, DeploymentStatus


def _deployment(orchestrator, status="in_progress"):
    deployment_id = str(uuid4())
    orchestrator.deployments[deployment_id] = DeploymentStatus(
        deployment_id=deployment_id,
        agents_total=2,
        agents_updated=0,
        agents_deferred=0,
        agents_failed=0,
        started_at=datetime.now(timezone.utc).isoformat(),
        staged_at=None,
        completed_at=None,
        status=status,
        message="test",
        canary_phase=None,
    )
    return deployment_id


def _agent(agent_id="echo-core-jm2jy2"):
    return AgentInfo(
        agent_id=agent_id,
        agent_name=agent_id,
        container_name=f"ciris-{agent_id}",
        api_port=8080,
        status="running",
        image="ghcr.io/cirisai/ciris-agent:2.9.26-stable",
        server_id="main",
    )


class TestActiveCheck:
    @pytest.mark.parametrize("status", ["cancelled", "failed", "completed"])
    def test_terminal_deployments_are_not_active(self, orchestrator, status):
        did = _deployment(orchestrator, status=status)
        assert orchestrator._deployment_is_active(did) is False

    def test_running_deployment_is_active(self, orchestrator):
        assert orchestrator._deployment_is_active(_deployment(orchestrator)) is True

    def test_unknown_deployment_is_not_treated_as_cancelled(self, orchestrator):
        """Entries are never removed, so a cancelled deployment is always still
        present. An unknown id is a caller error, not a stopped deployment, and
        must not be silently swallowed as one."""
        assert orchestrator._deployment_is_active("no-such-deployment") is True


class TestCancelledGroupIsSkipped:
    @pytest.mark.asyncio
    async def test_cancelled_deployment_updates_no_agents(self, orchestrator):
        """The outage: later canary phases kept updating agents after cancel."""
        did = _deployment(orchestrator, status="cancelled")
        orchestrator._update_single_agent = AsyncMock()

        await orchestrator._update_agent_group(
            did,
            UpdateNotification(agent_image="img:2.9.26-stable", message="m", strategy="canary"),
            [_agent("echo-core-jm2jy2"), _agent("echo-speculative-4fc6ru")],
            None,
        )

        orchestrator._update_single_agent.assert_not_called()

    @pytest.mark.asyncio
    async def test_active_deployment_still_updates_agents(self, orchestrator):
        """The guard must not break the normal path."""
        did = _deployment(orchestrator)
        orchestrator._update_single_agent = AsyncMock(return_value=None)

        await orchestrator._update_agent_group(
            did,
            UpdateNotification(agent_image="img:2.9.26-stable", message="m", strategy="canary"),
            [_agent("echo-core-jm2jy2")],
            None,
        )

        assert orchestrator._update_single_agent.await_count == 1


class TestCancelStopsTheTask:
    @pytest.mark.asyncio
    async def test_cancel_cancels_the_running_task(self, orchestrator):
        did = _deployment(orchestrator)
        started = asyncio.Event()

        async def long_running():
            started.set()
            await asyncio.sleep(3600)

        task = asyncio.create_task(long_running())
        orchestrator._register_deployment_task(did, task)
        await started.wait()

        await orchestrator.cancel_stuck_deployment(did, reason="operator stopped it")

        # give the loop a tick to deliver the cancellation
        await asyncio.sleep(0)
        assert task.cancelled() or task.done()
        assert orchestrator.deployments[did].status == "cancelled"

    @pytest.mark.asyncio
    async def test_status_is_cancelled_before_the_task_is_stopped(self, orchestrator):
        """Order matters: anything already past a check re-reads the status,
        and cancel() only lands at the next await."""
        did = _deployment(orchestrator)
        observed = {}

        async def watcher():
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                observed["status_at_cancel"] = orchestrator.deployments[did].status
                raise

        task = asyncio.create_task(watcher())
        await asyncio.sleep(0)
        orchestrator._register_deployment_task(did, task)

        await orchestrator.cancel_stuck_deployment(did, reason="stopped")
        await asyncio.sleep(0)

        assert observed.get("status_at_cancel") == "cancelled", (
            "the task saw a non-cancelled status while being torn down; "
            "work already in flight could still act on agents"
        )

    @pytest.mark.asyncio
    async def test_task_registry_does_not_leak(self, orchestrator):
        did = _deployment(orchestrator)

        async def quick():
            return None

        task = asyncio.create_task(quick())
        orchestrator._register_deployment_task(did, task)
        await task
        await asyncio.sleep(0)
        assert did not in orchestrator._deployment_tasks
