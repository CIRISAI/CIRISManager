"""
Unit tests for single-agent targeted deployments.

Tests the ability to deploy specific versions to individual agents for testing.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from uuid import uuid4

from ciris_manager.deployment_orchestrator import DeploymentOrchestrator
from ciris_manager.models import (
    UpdateNotification,
    AgentInfo,
    DeploymentStatus,
    AgentUpdateResponse,
)


class TestSingleAgentDeployment:
    """Test single-agent deployment functionality."""

    @pytest.fixture
    def mock_manager(self):
        """Create mock manager with required components."""
        manager = MagicMock()
        manager.config = MagicMock()
        manager.config.deployment = MagicMock()
        manager.config.deployment.canary_wait_minutes = 5
        manager.config.deployment.work_stability_minutes = 1

        # Mock agent registry
        manager.agent_registry = MagicMock()
        manager.agent_registry.list_agents = MagicMock(return_value=[])
        manager.agent_registry.save_metadata = MagicMock()

        return manager

    @pytest.fixture
    def orchestrator(self, mock_manager):
        """Create deployment orchestrator instance."""
        orchestrator = DeploymentOrchestrator(mock_manager)
        orchestrator._deployments = {}
        return orchestrator

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
        self, orchestrator, test_agent, update_notification
    ):
        """Test successful single-agent deployment."""
        # Mock image pull
        with patch.object(orchestrator, "_pull_images", new_callable=AsyncMock) as mock_pull:
            mock_pull.return_value = {"success": True}

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

                        # Verify image was pulled
                        mock_pull.assert_called_once()

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
        # Mock image pull
        with patch.object(orchestrator, "_pull_images", new_callable=AsyncMock) as mock_pull:
            mock_pull.return_value = {"success": True}

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
        self, orchestrator, test_agent, update_notification
    ):
        """Test deployment failure when image pull fails."""
        # Mock image pull failure
        with patch.object(orchestrator, "_pull_images", new_callable=AsyncMock) as mock_pull:
            mock_pull.return_value = {"success": False, "error": "Registry unreachable"}

            # Start deployment
            status = await orchestrator.start_single_agent_deployment(
                update_notification, test_agent
            )

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

                # Mock version tracker
                with patch(
                    "ciris_manager.deployment_orchestrator.get_version_tracker"
                ) as mock_tracker:
                    mock_tracker.return_value.promote_staged_version = AsyncMock()

                    # Mock save state
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
    async def test_agent_needs_update_check(self, orchestrator):
        """Test checking if agent needs update."""
        agent = AgentInfo(
            agent_id="test",
            agent_name="Test",
            container_name="test-container",
            api_port=8080,
            status="running",
            image="ghcr.io/cirisai/ciris-agent:v1.4.2",
        )

        # Mock Docker client
        with patch("docker.from_env") as mock_docker:
            mock_client = MagicMock()
            mock_docker.return_value = mock_client

            # Mock container
            mock_container = MagicMock()
            mock_container.image.tags = ["ghcr.io/cirisai/ciris-agent:v1.4.2"]
            mock_client.containers.get.return_value = mock_container

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
        )

        # Mock Docker error
        with patch("docker.from_env", side_effect=Exception("Docker unavailable")):
            needs_update = await orchestrator._agent_needs_update(
                agent, "ghcr.io/cirisai/ciris-agent:v1.4.5"
            )
            # Should assume update needed when can't check
            assert needs_update
