"""
Tests for deployment orchestrator.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
import asyncio

from ciris_manager.deployment_orchestrator import DeploymentOrchestrator
from ciris_manager.models import (
    UpdateNotification,
    AgentInfo,
)


class TestDeploymentOrchestrator:
    """Test deployment orchestration."""

    @pytest.fixture
    def orchestrator(self):
        """Create deployment orchestrator."""
        orchestrator = DeploymentOrchestrator()
        # Mock the registry client to avoid real network calls
        orchestrator.registry_client = Mock()
        orchestrator.registry_client.resolve_image_digest = AsyncMock(return_value="sha256:test123")
        return orchestrator

    @pytest.fixture
    def update_notification(self):
        """Create sample update notification."""
        return UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:v2.0",
            gui_image="ghcr.io/cirisai/ciris-gui:v2.0",
            message="Security update",
            strategy="canary",
            metadata={"version": "2.0"},
        )

    @pytest.fixture
    def sample_agents(self):
        """Create sample agents."""
        agents = []
        for i in range(10):
            agents.append(
                AgentInfo(
                    agent_id=f"agent-{i}",
                    agent_name=f"Agent {i}",
                    container_name=f"ciris-agent-{i}",
                    api_port=8080 + i,
                    status="running",
                )
            )
        return agents

    @pytest.mark.asyncio
    async def test_start_deployment(self, orchestrator, update_notification, sample_agents):
        """Test starting a deployment."""
        # Mock registry client to return different digests (indicating images changed)
        orchestrator.registry_client.resolve_image_digest = AsyncMock(
            side_effect=[
                "sha256:newagent123",  # New agent image
                "sha256:newgui456",  # New GUI image
            ]
        )

        status = await orchestrator.start_deployment(update_notification, sample_agents)

        assert status.deployment_id is not None
        assert status.agents_total == 10
        assert status.status == "in_progress"
        assert status.message == "Security update"
        assert status.canary_phase == "explorers"
        assert orchestrator.current_deployment == status.deployment_id

    @pytest.mark.asyncio
    async def test_concurrent_deployment_rejected(
        self, orchestrator, update_notification, sample_agents
    ):
        """Test that concurrent deployments are rejected."""
        # Start first deployment
        await orchestrator.start_deployment(update_notification, sample_agents)

        # Try to start second deployment
        with pytest.raises(ValueError, match="already in progress"):
            await orchestrator.start_deployment(update_notification, sample_agents)

    @pytest.mark.asyncio
    async def test_get_deployment_status(self, orchestrator, update_notification, sample_agents):
        """Test getting deployment status."""
        status = await orchestrator.start_deployment(update_notification, sample_agents)
        deployment_id = status.deployment_id

        # Get by ID
        retrieved = await orchestrator.get_deployment_status(deployment_id)
        assert retrieved is not None
        assert retrieved.deployment_id == deployment_id

        # Get current
        current = await orchestrator.get_current_deployment()
        assert current is not None
        assert current.deployment_id == deployment_id

    @pytest.mark.asyncio
    async def test_canary_deployment_phases(self, orchestrator, update_notification, sample_agents):
        """Test canary deployment phases."""
        with patch.object(
            orchestrator, "_update_agent_group", new_callable=AsyncMock
        ) as mock_update:
            # Mock the update method to complete immediately
            mock_update.return_value = None

            await orchestrator.start_deployment(update_notification, sample_agents)

            # Wait a bit for background task to start
            await asyncio.sleep(0.1)

            # Should have called update_agent_group for each phase
            # Note: This is a simplified test - in reality we'd need to wait for phases
            assert mock_update.call_count >= 1  # At least explorers phase

    @pytest.mark.asyncio
    async def test_immediate_deployment(self, orchestrator, sample_agents):
        """Test immediate deployment strategy."""
        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:v2.0",
            message="Emergency update",
            strategy="immediate",
        )

        with patch.object(
            orchestrator, "_update_agent_group", new_callable=AsyncMock
        ) as mock_update:
            mock_update.return_value = None

            status = await orchestrator.start_deployment(notification, sample_agents)

            # Wait for background task
            await asyncio.sleep(0.1)

            # Should update all agents at once
            assert status.canary_phase is None  # No phases for immediate
            assert mock_update.call_count == 1

    @pytest.mark.asyncio
    async def test_agent_update_success(self, orchestrator):
        """Test successful agent update."""
        agent = AgentInfo(
            agent_id="test-agent",
            agent_name="Test",
            container_name="ciris-test",
            api_port=8080,
            status="running",
        )

        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:v2.0",
            message="Update",
        )

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"decision": "accept"}
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            response = await orchestrator._update_single_agent(
                "deployment-123", notification, agent
            )

            assert response.agent_id == "test-agent"
            assert response.decision == "accept"

    @pytest.mark.asyncio
    async def test_agent_update_defer(self, orchestrator):
        """Test agent rejecting update via non-200 response."""
        agent = AgentInfo(
            agent_id="busy-agent",
            agent_name="Busy",
            container_name="ciris-busy",
            api_port=8081,
            status="running",
        )

        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:v2.0",
            message="Update",
        )

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = Mock()
            # Non-200 response means agent rejects shutdown
            mock_response.status_code = 503
            mock_response.text = "Service busy, cannot shutdown now"
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            response = await orchestrator._update_single_agent(
                "deployment-123", notification, agent
            )

            assert response.agent_id == "busy-agent"
            assert response.decision == "reject"
            assert response.reason == "HTTP 503"
            assert response.ready_at is None

    @pytest.mark.asyncio
    async def test_agent_unreachable(self, orchestrator):
        """Test handling unreachable agent."""
        agent = AgentInfo(
            agent_id="offline-agent",
            agent_name="Offline",
            container_name="ciris-offline",
            api_port=8082,
            status="running",
        )

        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:v2.0",
            message="Update",
        )

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.side_effect = Exception("Connection refused")
            mock_client_class.return_value.__aenter__.return_value = mock_client

            response = await orchestrator._update_single_agent(
                "deployment-123", notification, agent
            )

            assert response.agent_id == "offline-agent"
            assert response.decision == "reject"
            assert "Connection refused" in response.reason

    @pytest.mark.asyncio
    async def test_no_running_agents(self, orchestrator):
        """Test deployment with no running agents."""
        stopped_agents = [
            AgentInfo(
                agent_id="stopped-1",
                agent_name="Stopped 1",
                container_name="ciris-stopped-1",
                api_port=8080,
                status="stopped",
            )
        ]

        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:v2.0",
            message="Update",
            strategy="canary",
        )

        status = await orchestrator.start_deployment(notification, stopped_agents)

        # Wait for deployment to complete
        await asyncio.sleep(0.1)

        # Get final status
        final_status = await orchestrator.get_deployment_status(status.deployment_id)
        assert final_status.message == "No running agents to update"
