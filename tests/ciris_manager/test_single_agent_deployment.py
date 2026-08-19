"""
Unit tests for single-agent targeted deployments.

Tests the ability to deploy specific versions to individual agents for testing.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from datetime import datetime, timezone
from uuid import uuid4

from ciris_manager.models import (
    UpdateNotification,
    AgentInfo,
    DeploymentStatus,
    AgentUpdateResponse,
)


class TestSingleAgentDeployment:
    """Test single-agent deployment functionality."""

    # Use centralized fixtures from conftest.py for mock_manager and orchestrator

    @pytest.fixture
    def test_agent(self):
        """Create a test agent."""
        return AgentInfo(
            agent_id="test-agent",
            agent_name="Test Agent",
            container_name="ciris-test-agent",
            api_port=8080,
            status="running",
            image="ghcr.io/cirisai/ciris-agent:v1.4.2",
            server_id="main",
        )

    @pytest.fixture
    def update_notification(self):
        """Create an update notification for single agent."""
        return UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:v1.4.5",
            message="Testing new feature X",
            strategy="immediate",
            metadata={
                "single_agent_deployment": True,
                "target_agent": "test-agent",
                "initiated_by": "test@example.com",
            },
        )

    @pytest.mark.asyncio
    async def test_single_agent_deployment_success(
        self, orchestrator, test_agent, update_notification, mock_manager
    ):
        """Test successful single-agent deployment."""
        # Mock agent needs update check
        with patch.object(
            orchestrator, "_agent_needs_update", new_callable=AsyncMock
        ) as mock_needs:
            mock_needs.return_value = True

            # Mock save state
            with patch.object(orchestrator, "_save_state", new_callable=AsyncMock):
                # Mock background task execution
                with patch("asyncio.create_task") as mock_create_task:
                    mock_task = MagicMock()
                    mock_create_task.return_value = mock_task

                    # Start deployment
                    status = await orchestrator.start_single_agent_deployment(
                        update_notification, test_agent
                    )

                    # Verify deployment was created
                    assert status.deployment_id is not None
                    assert status.agents_total == 1
                    assert status.status == "in_progress"
                    assert "test-agent" in status.message
                    assert status.canary_phase is None  # No canary for single agent

                    # Verify image was pulled on correct server
                    docker_client = mock_manager.docker_client._clients["main"]
                    docker_client.images.pull.assert_called_once_with(
                        "ghcr.io/cirisai/ciris-agent:v1.4.5"
                    )

                    # Verify update check
                    mock_needs.assert_called_once_with(
                        test_agent, "ghcr.io/cirisai/ciris-agent:v1.4.5"
                    )

                    # Verify background task was created
                    mock_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_single_agent_deployment_already_updated(
        self, orchestrator, test_agent, update_notification
    ):
        """Test deployment when agent already has target version."""
        # Mock agent doesn't need update
        with patch.object(
            orchestrator, "_agent_needs_update", new_callable=AsyncMock
        ) as mock_needs:
            mock_needs.return_value = False

            # Start deployment
            status = await orchestrator.start_single_agent_deployment(
                update_notification, test_agent
            )

            # Verify deployment completed immediately
            assert status.status == "completed"
            assert "already running target version" in status.message
            assert status.agents_updated == 0
            assert status.completed_at is not None

    @pytest.mark.asyncio
    async def test_single_agent_deployment_image_pull_failure(
        self, orchestrator, test_agent, update_notification, mock_manager
    ):
        """Test deployment failure when image pull fails."""
        # Mock image pull to raise an exception
        docker_client = mock_manager.docker_client._clients["main"]
        docker_client.images.pull.side_effect = Exception("Registry unreachable")

        # Start deployment
        status = await orchestrator.start_single_agent_deployment(update_notification, test_agent)

        # Verify deployment failed
        assert status.status == "failed"
        assert "Failed to pull image" in status.message
        assert status.agents_failed == 1
        assert status.completed_at is not None

    @pytest.mark.asyncio
    async def test_single_agent_deployment_concurrent_prevention(
        self, orchestrator, test_agent, update_notification
    ):
        """Test that concurrent single-agent deployments are prevented."""
        # Set a current deployment
        orchestrator.current_deployment = "existing-deployment"

        # Try to start another deployment
        with pytest.raises(ValueError, match="already in progress"):
            await orchestrator.start_single_agent_deployment(update_notification, test_agent)

    @pytest.mark.asyncio
    async def test_execute_single_agent_deployment_accept(
        self, orchestrator, test_agent, update_notification
    ):
        """Test execution of single-agent deployment when agent accepts."""
        deployment_id = str(uuid4())

        # Create deployment status
        status = DeploymentStatus(
            deployment_id=deployment_id,
            notification=update_notification,
            agents_total=1,
            agents_updated=0,
            agents_deferred=0,
            agents_failed=0,
            started_at=datetime.now(timezone.utc).isoformat(),
            status="in_progress",
            message="Test deployment",
        )
        orchestrator.deployments[deployment_id] = status

        # Mock update response
        update_response = AgentUpdateResponse(
            agent_id="test-agent",
            decision="accept",
            reason="Ready to update",
            estimated_downtime_seconds=30,
        )

        with patch.object(
            orchestrator, "_update_single_agent", new_callable=AsyncMock
        ) as mock_update:
            mock_update.return_value = update_response

            # Mock health check
            with patch.object(
                orchestrator, "_check_canary_group_health", new_callable=AsyncMock
            ) as mock_health:
                mock_health.return_value = (True, {"successful_agent": "test-agent"})

                # Mock save state (no version tracker needed - DeploymentOrchestrator handles this internally)
                with patch.object(orchestrator, "_save_state", new_callable=AsyncMock):
                    # Execute deployment
                    await orchestrator._execute_single_agent_deployment(
                        deployment_id, update_notification, test_agent
                    )

                    # Verify success
                    assert status.status == "completed"
                    assert status.agents_updated == 1
                    assert "Successfully deployed" in status.message
                    assert orchestrator.current_deployment is None

    @pytest.mark.asyncio
    async def test_execute_single_agent_deployment_defer(
        self, orchestrator, test_agent, update_notification
    ):
        """Test execution when agent defers update."""
        deployment_id = str(uuid4())

        # Create deployment status
        status = DeploymentStatus(
            deployment_id=deployment_id,
            notification=update_notification,
            agents_total=1,
            agents_updated=0,
            agents_deferred=0,
            agents_failed=0,
            started_at=datetime.now(timezone.utc).isoformat(),
            status="in_progress",
            message="Test deployment",
        )
        orchestrator.deployments[deployment_id] = status

        # Mock update response - deferred
        update_response = AgentUpdateResponse(
            agent_id="test-agent",
            decision="defer",
            reason="In the middle of critical task",
            estimated_downtime_seconds=None,
        )

        with patch.object(
            orchestrator, "_update_single_agent", new_callable=AsyncMock
        ) as mock_update:
            mock_update.return_value = update_response

            # Mock save state
            with patch.object(orchestrator, "_save_state", new_callable=AsyncMock):
                # Execute deployment
                await orchestrator._execute_single_agent_deployment(
                    deployment_id, update_notification, test_agent
                )

                # Verify deferred
                assert status.status == "completed"
                assert status.agents_deferred == 1
                assert "deferred the update" in status.message

    @pytest.mark.asyncio
    async def test_execute_single_agent_deployment_reject(
        self, orchestrator, test_agent, update_notification
    ):
        """Test execution when agent rejects update."""
        deployment_id = str(uuid4())

        # Create deployment status
        status = DeploymentStatus(
            deployment_id=deployment_id,
            notification=update_notification,
            agents_total=1,
            agents_updated=0,
            agents_deferred=0,
            agents_failed=0,
            started_at=datetime.now(timezone.utc).isoformat(),
            status="in_progress",
            message="Test deployment",
        )
        orchestrator.deployments[deployment_id] = status

        # Mock update response - rejected
        update_response = AgentUpdateResponse(
            agent_id="test-agent",
            decision="reject",
            reason="Version incompatible with current workload",
            estimated_downtime_seconds=None,
        )

        with patch.object(
            orchestrator, "_update_single_agent", new_callable=AsyncMock
        ) as mock_update:
            mock_update.return_value = update_response

            # Mock save state
            with patch.object(orchestrator, "_save_state", new_callable=AsyncMock):
                # Execute deployment
                await orchestrator._execute_single_agent_deployment(
                    deployment_id, update_notification, test_agent
                )

                # Verify rejected
                assert status.status == "failed"
                assert status.agents_failed == 1
                assert "rejected the update" in status.message
                assert "Version incompatible" in status.message

    @pytest.mark.asyncio
    async def test_agent_needs_update_check(self, orchestrator, mock_manager):
        """Test checking if agent needs update."""
        agent = AgentInfo(
            agent_id="test",
            agent_name="Test",
            container_name="test-container",
            api_port=8080,
            status="running",
            image="ghcr.io/cirisai/ciris-agent:v1.4.2",
            server_id="main",
        )

        # Get the main server's Docker client from centralized fixture
        main_client = mock_manager.docker_client._clients["main"]

        # Mock container with v1.4.2 image
        # Note: Need to override the side_effect, not just return_value
        mock_container = MagicMock()
        mock_container.image.tags = ["ghcr.io/cirisai/ciris-agent:v1.4.2"]
        mock_container.status = "running"
        mock_container.reload = Mock()  # Mock the reload() method
        main_client.containers.get = Mock(return_value=mock_container)

        # Test same version
        needs_update = await orchestrator._agent_needs_update(
            agent, "ghcr.io/cirisai/ciris-agent:v1.4.2"
        )
        assert not needs_update

        # Test different version
        needs_update = await orchestrator._agent_needs_update(
            agent, "ghcr.io/cirisai/ciris-agent:v1.4.5"
        )
        assert needs_update

    @pytest.mark.asyncio
    async def test_agent_needs_update_docker_error(self, orchestrator):
        """Test update check when Docker is unavailable."""
        agent = AgentInfo(
            agent_id="test",
            agent_name="Test",
            container_name="test-container",
            api_port=8080,
            status="running",
            image="ghcr.io/cirisai/ciris-agent:v1.4.2",
            server_id="main",
        )

        # Mock Docker error when getting client
        orchestrator.manager.docker_client.get_client.side_effect = Exception("Docker unavailable")

        needs_update = await orchestrator._agent_needs_update(
            agent, "ghcr.io/cirisai/ciris-agent:v1.4.5"
        )
        # Should assume update needed when can't check
        assert needs_update


class TestDeploymentMutexHeldOnlyForTheSwap:
    """The global deployment mutex must not be held across WORK-state verification.

    Regression test for CIRISManager#19. `_execute_single_agent_deployment`
    always cleared `current_deployment` in a `finally`, so the mutex was
    released eventually - but only after waiting up to
    DEFAULT_WAIT_FOR_WORK_MINUTES (15) for the agent to reach WORK. That wait
    is verification: the container swap has already happened and nothing
    shared is mutated.

    In production every agent was stuck short of WORK, so the wait ran to its
    full timeout on each deployment. Agents were healthy on the new image
    within ~2 minutes and then blocked every other deployment for 13 more,
    which forced operators to cancel already-successful deployments purely to
    reclaim the mutex - recording five successful rollouts as operator
    cancellations in the audit trail.
    """

    @pytest.fixture
    def test_agent(self):
        return AgentInfo(
            agent_id="lock-test-agent",
            agent_name="Lock Test Agent",
            container_name="ciris-lock-test-agent",
            api_port=8080,
            status="running",
            image="ghcr.io/cirisai/ciris-agent:2.9.25-stable",
            server_id="main",
        )

    @pytest.mark.asyncio
    async def test_mutex_is_free_while_waiting_for_work_state(self, orchestrator, test_agent):
        """The mutex is released before the WORK wait, not after it."""
        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:2.9.26-stable",
            message="mutex scope test",
            strategy="docker",
        )

        deployment_id = str(uuid4())
        orchestrator.deployments[deployment_id] = DeploymentStatus(
            deployment_id=deployment_id,
            agents_total=1,
            agents_updated=0,
            agents_deferred=0,
            agents_failed=0,
            started_at=datetime.now(timezone.utc).isoformat(),
            staged_at=None,
            completed_at=None,
            status="in_progress",
            message="mutex scope test",
            canary_phase=None,
        )
        orchestrator.current_deployment = deployment_id

        observed = {}

        async def capture_then_succeed(*args, **kwargs):
            # Sampled at the moment verification begins - this is the window
            # that used to stay locked for up to 15 minutes.
            observed["locked_during_wait"] = orchestrator.current_deployment
            return True, {}

        orchestrator._update_single_agent = AsyncMock(
            return_value=AgentUpdateResponse(
                agent_id=test_agent.agent_id,
                decision="accept",
                reason="Container recreated with new image",
                ready_at=None,
            )
        )
        orchestrator._check_canary_group_health = AsyncMock(side_effect=capture_then_succeed)

        await orchestrator._execute_single_agent_deployment(deployment_id, notification, test_agent)

        assert observed["locked_during_wait"] is None, (
            "deployment mutex was still held while waiting for WORK state; "
            "a concurrent deployment would be rejected for up to 15 minutes "
            "after this agent was already healthy on the new image"
        )
        assert orchestrator.current_deployment is None
        assert orchestrator.deployments[deployment_id].status == "completed"

    @pytest.mark.asyncio
    async def test_mutex_released_even_when_verification_fails(self, orchestrator, test_agent):
        """A failed verification must not strand the mutex either."""
        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:2.9.26-stable",
            message="mutex scope test - failure path",
            strategy="docker",
        )

        deployment_id = str(uuid4())
        orchestrator.deployments[deployment_id] = DeploymentStatus(
            deployment_id=deployment_id,
            agents_total=1,
            agents_updated=0,
            agents_deferred=0,
            agents_failed=0,
            started_at=datetime.now(timezone.utc).isoformat(),
            staged_at=None,
            completed_at=None,
            status="in_progress",
            message="mutex scope test - failure path",
            canary_phase=None,
        )
        orchestrator.current_deployment = deployment_id

        orchestrator._update_single_agent = AsyncMock(
            return_value=AgentUpdateResponse(
                agent_id=test_agent.agent_id,
                decision="accept",
                reason="Container recreated with new image",
                ready_at=None,
            )
        )
        orchestrator._check_canary_group_health = AsyncMock(return_value=(False, {}))

        await orchestrator._execute_single_agent_deployment(deployment_id, notification, test_agent)

        assert orchestrator.current_deployment is None
        assert orchestrator.deployments[deployment_id].status == "failed"
