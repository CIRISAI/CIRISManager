"""
Test agent restart functionality.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from fastapi.testclient import TestClient

from ciris_manager.api.routes import create_routes


class TestRestartAgent:
    """Test suite for agent restart functionality."""

    @pytest.fixture
    def mock_manager(self):
        """Create a mock manager instance."""
        from ciris_manager.agent_registry import RegisteredAgent

        manager = Mock()

        # Create mock agent for registry lookups
        mock_agent = RegisteredAgent(
            agent_id="test-agent",
            name="Test Agent",
            port=8001,
            template="test",
            compose_file="/path/to/compose.yml",
            server_id="main",
        )

        manager.agent_registry = Mock()
        manager.agent_registry.get_agent = Mock(return_value=mock_agent)
        manager.agent_registry.get_agents_by_agent_id = Mock(return_value=[mock_agent])

        manager.config = Mock()
        manager.docker_client = Mock()

        # Mock get_server_config for multi-server support
        mock_server_config = Mock()
        mock_server_config.vpc_ip = "localhost"
        mock_server_config.hostname = "agents.ciris.ai"
        manager.docker_client.get_server_config = Mock(return_value=mock_server_config)

        return manager

    @pytest.fixture
    def app(self, mock_manager):
        """Create a FastAPI app with routes."""
        from fastapi import FastAPI
        import os

        app = FastAPI()
        os.environ["CIRIS_AUTH_MODE"] = "development"

        router = create_routes(mock_manager)
        app.include_router(router, prefix="/manager/v1")
        return app

    @pytest.fixture
    def client(self, app):
        """Create a test client."""
        return TestClient(app)

    def test_restart_existing_agent(self, client, mock_manager):
        """Test restarting an existing agent."""
        with patch("ciris_manager.api.routes.DockerAgentDiscovery") as MockDiscovery:
            # Setup discovered agent with container_name
            mock_agent = Mock()
            mock_agent.agent_id = "test-agent"
            mock_agent.server_id = "main"
            mock_agent.container_name = "ciris-agent-test-agent"
            mock_agent.occurrence_id = None

            mock_discovery = MockDiscovery.return_value
            mock_discovery.discover_agents.return_value = [mock_agent]

            # Mock Docker client and container
            mock_client = MagicMock()
            mock_container = MagicMock()
            mock_manager.docker_client.get_client.return_value = mock_client
            mock_client.containers.get.return_value = mock_container

            # Make the restart request
            response = client.post("/manager/v1/agents/test-agent/restart")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert data["agent_id"] == "test-agent"
            assert "restarting" in data["message"].lower()

            # Verify Docker restart was called
            mock_container.restart.assert_called_once_with(timeout=30)

    def test_restart_nonexistent_agent(self, client, mock_manager):
        """Test restarting a non-existent agent."""
        # Agent not in registry
        mock_manager.agent_registry.get_agent.return_value = None
        mock_manager.agent_registry.get_agents_by_agent_id.return_value = []

        with patch("ciris_manager.api.routes.DockerAgentDiscovery") as MockDiscovery:
            # No discovered agents either
            mock_discovery = MockDiscovery.return_value
            mock_discovery.discover_agents.return_value = []

            response = client.post("/manager/v1/agents/nonexistent/restart")

            assert response.status_code == 404
            assert "not found" in response.json()["detail"].lower()

    def test_restart_container_not_found(self, client, mock_manager):
        """Test restarting when container doesn't exist."""
        import docker.errors

        with patch("ciris_manager.api.routes.DockerAgentDiscovery") as MockDiscovery:
            # Setup discovered agent with container_name
            mock_agent = Mock()
            mock_agent.agent_id = "test-agent"
            mock_agent.server_id = "main"
            mock_agent.container_name = "ciris-agent-test-agent"
            mock_agent.occurrence_id = None

            mock_discovery = MockDiscovery.return_value
            mock_discovery.discover_agents.return_value = [mock_agent]

            # Mock Docker client that raises NotFound for all container names
            mock_client = MagicMock()
            mock_manager.docker_client.get_client.return_value = mock_client
            mock_client.containers.get.side_effect = docker.errors.NotFound("Container not found")

            response = client.post("/manager/v1/agents/test-agent/restart")

            assert response.status_code == 404
            assert "Container" in response.json()["detail"]

    def test_restart_docker_api_error(self, client, mock_manager):
        """Test handling Docker API errors during restart."""
        import docker.errors

        with patch("ciris_manager.api.routes.DockerAgentDiscovery") as MockDiscovery:
            # Setup discovered agent with container_name
            mock_agent = Mock()
            mock_agent.agent_id = "test-agent"
            mock_agent.server_id = "main"
            mock_agent.container_name = "ciris-agent-test-agent"
            mock_agent.occurrence_id = None

            mock_discovery = MockDiscovery.return_value
            mock_discovery.discover_agents.return_value = [mock_agent]

            # Mock Docker client and container that raises APIError
            mock_client = MagicMock()
            mock_container = MagicMock()
            mock_manager.docker_client.get_client.return_value = mock_client
            mock_client.containers.get.return_value = mock_container
            mock_container.restart.side_effect = docker.errors.APIError("Docker daemon error")

            response = client.post("/manager/v1/agents/test-agent/restart")

            assert response.status_code == 500
            assert "Failed to restart" in response.json()["detail"]

    def test_restart_with_alternate_container_name(self, client, mock_manager):
        """Test restarting with alternate container naming scheme (e.g., ciris-datum)."""
        with patch("ciris_manager.api.routes.DockerAgentDiscovery") as MockDiscovery:
            # Setup discovered agent with alternate container_name (ciris-test-agent instead of ciris-agent-test-agent)
            mock_agent = Mock()
            mock_agent.agent_id = "test-agent"
            mock_agent.server_id = "main"
            mock_agent.container_name = "ciris-test-agent"  # Alternate naming
            mock_agent.occurrence_id = None

            mock_discovery = MockDiscovery.return_value
            mock_discovery.discover_agents.return_value = [mock_agent]

            # Mock Docker client
            mock_client = MagicMock()
            mock_container = MagicMock()
            mock_manager.docker_client.get_client.return_value = mock_client
            mock_client.containers.get.return_value = mock_container

            response = client.post("/manager/v1/agents/test-agent/restart")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert data["container"] == "ciris-test-agent"

            # Verify restart was called
            mock_container.restart.assert_called_once_with(timeout=30)

    def test_restart_discovered_agent(self, client, mock_manager):
        """Test restarting a discovered agent (not in registry)."""
        # Agent not in registry
        mock_manager.agent_registry.get_agent.return_value = None
        mock_manager.agent_registry.get_agents_by_agent_id.return_value = []

        with patch("ciris_manager.api.routes.DockerAgentDiscovery") as MockDiscovery:
            # But found via discovery with proper container_name
            mock_discovery = MockDiscovery.return_value
            mock_agent = Mock()
            mock_agent.agent_id = "discovered-agent"
            mock_agent.server_id = "main"
            mock_agent.container_name = "ciris-agent-discovered-agent"
            mock_agent.occurrence_id = None
            mock_discovery.discover_agents.return_value = [mock_agent]

            # Mock Docker client and container
            mock_client = MagicMock()
            mock_container = MagicMock()
            mock_manager.docker_client.get_client.return_value = mock_client
            mock_client.containers.get.return_value = mock_container

            response = client.post("/manager/v1/agents/discovered-agent/restart")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert data["agent_id"] == "discovered-agent"

            # Verify restart was called
            mock_container.restart.assert_called_once_with(timeout=30)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
