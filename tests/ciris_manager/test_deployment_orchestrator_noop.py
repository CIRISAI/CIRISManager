"""
Test no-op deployment handling in deployment orchestrator.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timezone

from ciris_manager.deployment_orchestrator import DeploymentOrchestrator
from ciris_manager.models import UpdateNotification, AgentInfo


class TestNoOpDeployment:
    """Test no-op deployment detection."""

    @pytest.fixture
    def mock_manager(self):
        """Create mock manager with agent registry."""
        manager = Mock()
        manager.agent_registry = Mock()

        # Mock agent with current image digests
        mock_agent = Mock()
        mock_agent.metadata = {"current_images": {"agent": "sha256:abc123", "gui": "sha256:def456"}}
        manager.agent_registry.get_agent = Mock(return_value=mock_agent)

        return manager

    @pytest.fixture
    def mock_registry_client(self):
        """Create mock Docker registry client."""
        with patch("ciris_manager.deployment_orchestrator.DockerRegistryClient") as mock_class:
            client = Mock()
            # Mock resolve_image_digest to return same digests (no change)
            client.resolve_image_digest = AsyncMock(
                side_effect=[
                    "sha256:abc123",  # agent image
                    "sha256:def456",  # gui image
                ]
            )
            mock_class.return_value = client
            yield client

    @pytest.mark.asyncio
    async def test_no_op_deployment_same_digests(self, mock_manager, mock_registry_client):
        """Test deployment is skipped when image digests haven't changed."""
        orchestrator = DeploymentOrchestrator(mock_manager)
        orchestrator.registry_client = mock_registry_client

        # Create test agents
        agents = [
            AgentInfo(
                agent_id="agent-1",
                agent_name="Test Agent",
                container_name="ciris-agent-test",
                api_port=8080,
                status="running",
            )
        ]

        # Create notification
        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:latest",
            gui_image="ghcr.io/cirisai/ciris-gui:latest",
            message="Build #123",
            strategy="canary",
        )

        # Start deployment
        status = await orchestrator.start_deployment(notification, agents)

        # Verify no-op deployment
        assert status.status == "completed"
        assert status.message == "No update needed - images unchanged"
        assert status.agents_total == 1
        assert status.agents_updated == 0
        assert status.completed_at is not None

        # Verify no deployment was actually started
        assert orchestrator.current_deployment is None

    @pytest.mark.asyncio
    async def test_deployment_proceeds_with_new_digests(self, mock_manager, mock_registry_client):
        """Test deployment proceeds when image digests have changed."""
        orchestrator = DeploymentOrchestrator(mock_manager)

        # Mock different digests (images changed)
        mock_registry_client.resolve_image_digest = AsyncMock(
            side_effect=[
                "sha256:xyz789",  # new agent image
                "sha256:uvw456",  # new gui image
            ]
        )
        orchestrator.registry_client = mock_registry_client

        # Create test agents
        agents = [
            AgentInfo(
                agent_id="agent-1",
                agent_name="Test Agent",
                container_name="ciris-agent-test",
                api_port=8080,
                status="running",
            )
        ]

        # Create notification
        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:latest",
            gui_image="ghcr.io/cirisai/ciris-gui:latest",
            message="Security update",
            strategy="canary",
        )

        # Start deployment
        status = await orchestrator.start_deployment(notification, agents)

        # Verify deployment started
        assert status.status == "in_progress"
        assert status.agents_total == 1
        assert status.agents_updated == 0  # Not updated yet
        assert orchestrator.current_deployment == status.deployment_id

    @pytest.mark.asyncio
    async def test_partial_update_gui_only(self, mock_manager, mock_registry_client):
        """Test deployment when only GUI image changed."""
        orchestrator = DeploymentOrchestrator(mock_manager)

        # Mock same agent digest, different GUI digest
        mock_registry_client.resolve_image_digest = AsyncMock(
            side_effect=[
                "sha256:abc123",  # same agent image
                "sha256:new789",  # new gui image
            ]
        )
        orchestrator.registry_client = mock_registry_client

        # Create test agents
        agents = [
            AgentInfo(
                agent_id="agent-1",
                agent_name="Test Agent",
                container_name="ciris-agent-test",
                api_port=8080,
                status="running",
            )
        ]

        # Create notification
        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:latest",
            gui_image="ghcr.io/cirisai/ciris-gui:latest",
            message="GUI update only",
            strategy="immediate",
        )

        # Start deployment
        status = await orchestrator.start_deployment(notification, agents)

        # Verify deployment started (GUI changed)
        assert status.status == "in_progress"
        assert status.agents_total == 1

    @pytest.mark.asyncio
    async def test_no_metadata_triggers_update(self, mock_manager, mock_registry_client):
        """Test agents without metadata are always updated."""
        manager = Mock()
        manager.agent_registry = Mock()

        # Mock agent without metadata
        mock_agent = Mock()
        mock_agent.metadata = {}  # No current_images
        manager.agent_registry.get_agent = Mock(return_value=mock_agent)

        orchestrator = DeploymentOrchestrator(manager)
        orchestrator.registry_client = mock_registry_client

        # Create test agents
        agents = [
            AgentInfo(
                agent_id="agent-1",
                agent_name="New Agent",
                container_name="ciris-agent-new",
                api_port=8080,
                status="running",
            )
        ]

        # Create notification
        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:latest",
            gui_image="ghcr.io/cirisai/ciris-gui:latest",
            message="First deployment",
            strategy="immediate",
        )

        # Start deployment
        status = await orchestrator.start_deployment(notification, agents)

        # Verify deployment started (no previous digests)
        assert status.status == "in_progress"
        assert status.agents_total == 1
