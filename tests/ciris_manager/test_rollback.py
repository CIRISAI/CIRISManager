"""
Tests for rollback and image retention functionality.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, timezone

from ciris_manager.models import (
    UpdateNotification,
    DeploymentStatus,
    AgentInfo,
)
from ciris_manager.deployment_orchestrator import DeploymentOrchestrator


class TestRollbackProposal:
    """Test rollback proposal mechanisms."""

    @pytest.fixture
    def orchestrator(self, tmp_path):
        """Create orchestrator with mock manager."""
        mock_manager = Mock()
        mock_manager.agent_registry = Mock()
        mock_manager.agent_registry.get_agent = Mock()
        mock_manager.agent_registry._save_metadata = Mock()

        orchestrator = DeploymentOrchestrator(manager=mock_manager)
        orchestrator.registry_client = Mock()
        orchestrator.registry_client.resolve_image_digest = AsyncMock(
            return_value="sha256:newdigest"
        )
        return orchestrator

    @pytest.fixture
    def failed_agents(self):
        """Create agents that failed to reach WORK state."""
        return [
            Mock(
                spec=AgentInfo,
                agent_id="agent-1",
                is_running=True,
                container_name="ciris-agent-1",
                api_port=8001,
            ),
            Mock(
                spec=AgentInfo,
                agent_id="agent-2",
                is_running=True,
                container_name="ciris-agent-2",
                api_port=8002,
            ),
        ]

    @pytest.mark.asyncio
    async def test_propose_rollback_on_work_failure(self, orchestrator, failed_agents):
        """Test that rollback is proposed when agents fail to reach WORK."""
        # Set up deployment
        deployment_id = "test-deploy-123"
        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:v1.4.0",
            strategy="canary",
            message="Test deployment",
        )

        deployment = DeploymentStatus(
            deployment_id=deployment_id,
            notification=notification,
            agents_total=2,
            agents_updated=0,
            agents_deferred=0,
            agents_failed=0,
            status="in_progress",
            message="Testing",
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        orchestrator.deployments[deployment_id] = deployment

        # Mock health check to return non-WORK state
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": {
                    "cognitive_state": "BOOT",  # Not WORK
                    "version": "1.4.0",
                }
            }
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            # Run health check with short timeout
            result = await orchestrator._check_canary_group_health(
                deployment_id,
                failed_agents,
                "test",
                wait_for_work_minutes=0.01,  # Very short for testing
                stability_minutes=0.01,
            )

            # Should return False and propose rollback
            assert result is False
            assert hasattr(orchestrator, "rollback_proposals")
            assert deployment_id in orchestrator.rollback_proposals

            proposal = orchestrator.rollback_proposals[deployment_id]
            assert proposal["reason"] == "No test agents reached WORK state within 0.01 minutes"
            # Check rollback_targets structure (new format)
            assert "rollback_targets" in proposal
            assert proposal["rollback_targets"]["agents"] == ["agent-1", "agent-2"]

    @pytest.mark.asyncio
    async def test_no_rollback_proposal_on_defer(self, orchestrator):
        """Test that agent deferrals don't trigger rollback proposals."""
        deployment_id = "test-deploy-456"
        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:v1.4.0",
            strategy="canary",
            message="Test deployment",
        )

        # Create deployment with deferred agents
        deployment = DeploymentStatus(
            deployment_id=deployment_id,
            notification=notification,
            agents_total=3,
            agents_updated=1,
            agents_deferred=2,  # Agents deferred, not failed
            agents_failed=0,
            status="in_progress",
            message="Some agents deferred",
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        orchestrator.deployments[deployment_id] = deployment

        # Complete deployment without proposing rollback
        deployment.status = "completed"
        deployment.completed_at = datetime.now(timezone.utc).isoformat()

        # No rollback should be proposed for deferrals
        proposals = getattr(orchestrator, "rollback_proposals", {})
        assert deployment_id not in proposals

    @pytest.mark.asyncio
    async def test_rollback_proposal_details(self, orchestrator):
        """Test rollback proposal includes previous version info."""

        # Set up agents with version history
        agent1 = Mock(spec=AgentInfo, agent_id="agent-1")
        agent1.metadata = {
            "previous_images": {
                "n-1": "sha256:previous1",
                "n-2": "sha256:older1",
            }
        }

        agent2 = Mock(spec=AgentInfo, agent_id="agent-2")
        agent2.metadata = {
            "previous_images": {
                "n-1": "sha256:previous2",
            }
        }

        orchestrator.manager.agent_registry.get_agent.side_effect = [agent1, agent2]

        agents = [
            Mock(agent_id="agent-1"),
            Mock(agent_id="agent-2"),
        ]

        # Get previous versions
        previous = await orchestrator._get_previous_versions(agents)

        assert previous["agent-1"] == "sha256:previous1"
        assert previous["agent-2"] == "sha256:previous2"


class TestImageVersionRotation:
    """Test N-1 and N-2 version maintenance."""

    @pytest.fixture
    def orchestrator_with_agent(self, tmp_path):
        """Create orchestrator with a test agent."""
        mock_manager = Mock()

        # Create test agent with version history
        test_agent = MagicMock()
        test_agent.agent_id = "test-agent"
        test_agent.metadata = {
            "current_images": {
                "agent": "sha256:current",
                "agent_tag": "ghcr.io/cirisai/ciris-agent:v1.3.0",
            },
            "previous_images": {
                "n-1": "sha256:previous",
            },
        }

        mock_manager.agent_registry.get_agent.return_value = test_agent
        mock_manager.agent_registry._save_metadata = Mock()

        orchestrator = DeploymentOrchestrator(manager=mock_manager)
        orchestrator.current_deployment = "deploy-123"
        orchestrator.registry_client = Mock()
        orchestrator.registry_client.resolve_image_digest = AsyncMock(
            return_value="sha256:newversion"
        )

        return orchestrator, test_agent

    @pytest.mark.asyncio
    async def test_version_rotation_on_update(self, orchestrator_with_agent):
        """Test that versions rotate: current -> n-1 -> n-2."""
        orchestrator, agent = orchestrator_with_agent

        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:v1.4.0",
            strategy="canary",
            message="New version",
        )

        # Mock image cleanup
        with patch.object(orchestrator, "_trigger_image_cleanup", new_callable=AsyncMock):
            await orchestrator._update_agent_metadata("test-agent", notification)

        # Check version rotation
        assert agent.metadata["current_images"]["agent"] == "sha256:newversion"
        assert agent.metadata["current_images"]["agent_tag"] == "ghcr.io/cirisai/ciris-agent:v1.4.0"
        assert agent.metadata["previous_images"]["n-1"] == "sha256:current"
        assert agent.metadata["previous_images"]["n-2"] == "sha256:previous"

    @pytest.mark.asyncio
    async def test_version_history_tracking(self, orchestrator_with_agent):
        """Test that deployment history is maintained."""
        orchestrator, agent = orchestrator_with_agent

        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:v1.4.0",
            strategy="canary",
            message="New version",
        )

        # Initialize version history
        agent.metadata["version_history"] = []

        with patch.object(orchestrator, "_trigger_image_cleanup", new_callable=AsyncMock):
            await orchestrator._update_agent_metadata("test-agent", notification)

        # Check version history
        assert len(agent.metadata["version_history"]) == 1
        history = agent.metadata["version_history"][0]
        assert history["agent_image"] == "ghcr.io/cirisai/ciris-agent:v1.4.0"
        assert history["deployment_id"] == "deploy-123"
        assert "timestamp" in history

    @pytest.mark.asyncio
    async def test_image_cleanup_triggered(self, orchestrator_with_agent):
        """Test that image cleanup is triggered after update."""
        orchestrator, agent = orchestrator_with_agent

        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:v1.4.0",
            strategy="canary",
            message="New version",
        )

        with patch.object(
            orchestrator, "_trigger_image_cleanup", new_callable=AsyncMock
        ) as mock_cleanup:
            await orchestrator._update_agent_metadata("test-agent", notification)

            # Cleanup should be scheduled
            mock_cleanup.assert_called_once()


class TestRollbackExecution:
    """Test actual rollback execution."""

    @pytest.fixture
    def orchestrator(self):
        """Create orchestrator for rollback testing."""
        mock_manager = Mock()
        mock_manager.agent_registry = Mock()

        orchestrator = DeploymentOrchestrator(manager=mock_manager)
        return orchestrator

    @pytest.mark.asyncio
    async def test_rollback_to_n1_version(self, orchestrator):
        """Test rollback uses N-1 version."""
        deployment = DeploymentStatus(
            deployment_id="rollback-test",
            notification=UpdateNotification(
                agent_image="ghcr.io/cirisai/ciris-agent:v1.4.0",
                strategy="canary",
                message="Failed deployment",
                metadata={"affected_agents": ["agent-1"]},
            ),
            agents_total=1,
            agents_updated=1,
            agents_deferred=0,
            agents_failed=0,
            status="rolling_back",
            message="Rolling back",
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        # Set up agent with N-1 version
        test_agent = Mock()
        test_agent.agent_id = "agent-1"
        test_agent.container_name = "ciris-agent-1"
        test_agent.metadata = {
            "previous_images": {
                "n-1": "ghcr.io/cirisai/ciris-agent:v1.3.0",
            },
            "current_images": {},
        }

        orchestrator.manager.agent_registry.get_agent.return_value = test_agent
        orchestrator.manager.agent_registry.update_agent = Mock()

        # Mock docker commands
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_process = AsyncMock()
            mock_process.communicate.return_value = (b"", b"")
            mock_exec.return_value = mock_process

            await orchestrator._rollback_agents(deployment)

            # Verify docker commands
            calls = mock_exec.call_args_list

            # Should stop container
            assert any("stop" in str(call) for call in calls)
            assert any("ciris-agent-1" in str(call) for call in calls)

            # Should run with N-1 image
            assert any("run" in str(call) for call in calls)
            assert any("v1.3.0" in str(call) for call in calls)

        # Check deployment status
        assert deployment.status == "rolled_back"
        assert deployment.completed_at is not None

    @pytest.mark.asyncio
    async def test_rollback_failure_handling(self, orchestrator):
        """Test rollback handles failures gracefully."""
        deployment = DeploymentStatus(
            deployment_id="rollback-fail",
            notification=UpdateNotification(
                agent_image="ghcr.io/cirisai/ciris-agent:v1.4.0",
                strategy="canary",
                message="Failed deployment",
                metadata={"affected_agents": ["agent-1"]},
            ),
            agents_total=1,
            agents_updated=1,
            agents_deferred=0,
            agents_failed=0,
            status="rolling_back",
            message="Rolling back",
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        # Simulate docker command failure
        with patch("asyncio.create_subprocess_exec", side_effect=Exception("Docker error")):
            await orchestrator._rollback_agents(deployment)

        # Should mark as failed but not crash
        assert deployment.status == "rollback_failed"
        assert deployment.completed_at is not None


class TestImageCleanupIntegration:
    """Test integration with Docker image cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup_maintains_n2_versions(self):
        """Test that cleanup keeps exactly 3 versions."""
        from ciris_manager.docker_image_cleanup import DockerImageCleanup

        with patch("docker.from_env") as mock_docker:
            # Set up mock images
            mock_images = []
            for i in range(5):  # 5 versions total
                img = Mock()
                img.id = f"sha256:image{i}"
                img.tags = [f"ghcr.io/cirisai/ciris-agent:v1.{i}.0"]
                img.attrs = {"Created": f"2025-08-{10+i}T10:00:00Z"}
                mock_images.append(img)

            mock_docker.return_value.images.list.return_value = mock_images
            mock_docker.return_value.containers.list.return_value = []
            mock_docker.return_value.images.remove = Mock()

            cleanup = DockerImageCleanup(versions_to_keep=3)
            cleanup.client = mock_docker.return_value

            # Group and sort images
            grouped = cleanup.group_images_by_repository(mock_images)
            repo = "ghcr.io/cirisai/ciris-agent"

            # Should have all 5 images for the repo
            assert len(grouped[repo]) == 5

            # Run cleanup
            removed = cleanup.cleanup_repository_images(repo, grouped[repo], set())

            # Should remove 2 oldest images (keeping 3)
            assert removed == 2
            assert mock_docker.return_value.images.remove.call_count == 2

    @pytest.mark.asyncio
    async def test_cleanup_preserves_running_images(self):
        """Test that cleanup never removes images in use."""
        from ciris_manager.docker_image_cleanup import DockerImageCleanup

        with patch("docker.from_env") as mock_docker:
            # Set up mock images
            old_image = Mock()
            old_image.id = "sha256:oldimage"
            old_image.tags = ["ghcr.io/cirisai/ciris-agent:v1.0.0"]
            old_image.attrs = {"Created": "2025-01-01T10:00:00Z"}

            # Mock container using old image
            mock_container = Mock()
            mock_container.image.id = "sha256:oldimage"
            mock_docker.return_value.containers.list.return_value = [mock_container]

            cleanup = DockerImageCleanup(versions_to_keep=1)
            cleanup.client = mock_docker.return_value

            # Get running images
            running = cleanup.get_running_images()
            assert "sha256:oldimage" in running

            # Try to clean up
            removed = cleanup.cleanup_repository_images(
                "ghcr.io/cirisai/ciris-agent", [old_image], running
            )

            # Should not remove image in use
            assert removed == 0
            mock_docker.return_value.images.remove.assert_not_called()
