"""
Tests for version adoption API endpoint.
"""

import pytest
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient
from fastapi import FastAPI

from ciris_manager.api.routes import create_routes
from ciris_manager.models import AgentInfo, DeploymentStatus


class TestVersionsAPI:
    """Test version adoption API endpoint."""

    @pytest.fixture
    def mock_manager(self):
        """Create mock manager with agent registry."""
        manager = Mock()
        manager.agent_registry = Mock()

        # Mock agent with version metadata
        mock_agent = Mock()
        mock_agent.metadata = {
            "current_images": {"agent": "sha256:abc123", "gui": "sha256:def456"},
            "last_updated": "2025-08-02T10:30:00Z",
        }
        manager.agent_registry.get_agent = Mock(return_value=mock_agent)

        return manager

    @pytest.fixture
    def mock_discovery(self):
        """Mock Docker agent discovery."""
        with patch("ciris_manager.docker_discovery.DockerAgentDiscovery") as mock_class:
            discovery = Mock()
            discovery.discover_agents = Mock(
                return_value=[
                    AgentInfo(
                        agent_id="agent-1",
                        agent_name="Test Agent 1",
                        container_name="ciris-agent-test1",
                        api_port=8080,
                        status="running",
                    ),
                    AgentInfo(
                        agent_id="agent-2",
                        agent_name="Test Agent 2",
                        container_name="ciris-agent-test2",
                        api_port=8081,
                        status="running",
                    ),
                ]
            )
            mock_class.return_value = discovery
            yield discovery

    @pytest.fixture
    def mock_orchestrator(self):
        """Create mock deployment orchestrator."""
        with patch("ciris_manager.api.routes_v1.DeploymentOrchestrator") as mock_class:
            orchestrator = Mock()

            # Make async methods return coroutines
            async def mock_get_current():
                return None

            orchestrator.get_current_deployment = Mock(side_effect=mock_get_current)
            orchestrator.deployments = {
                "deploy-1": Mock(
                    deployment_id="deploy-1",
                    started_at="2025-08-01T10:00:00Z",
                    completed_at="2025-08-01T10:30:00Z",
                    agents_updated=5,
                    agents_total=10,
                    message="Security update",
                    status="completed",
                ),
                "deploy-2": Mock(
                    deployment_id="deploy-2",
                    started_at="2025-08-02T09:00:00Z",
                    completed_at="2025-08-02T09:15:00Z",
                    agents_updated=10,
                    agents_total=10,
                    message="Feature release",
                    status="completed",
                ),
            }
            mock_class.return_value = orchestrator
            yield orchestrator

    @pytest.fixture
    def test_client(self, mock_manager, mock_discovery, mock_orchestrator):
        """Create test client with mocked dependencies."""
        # Mock auth dependency to bypass authentication
        from ciris_manager.api.auth import get_current_user_dependency
        from unittest.mock import Mock

        def mock_get_current_user():
            return {"user_id": "test_user", "email": "test@ciris.ai"}

        app = FastAPI()

        # Set up app.state for modular route dependencies
        app.state.manager = mock_manager
        app.state.deployment_orchestrator = mock_orchestrator
        mock_token_manager = Mock()
        mock_token_manager.get_all_tokens = Mock(
            return_value={"agent": "test-token", "gui": "", "legacy": "test-token"}
        )
        app.state.token_manager = mock_token_manager

        router = create_routes(mock_manager)

        # Override auth dependency
        router.dependency_overrides_provider = app
        app.dependency_overrides[get_current_user_dependency] = mock_get_current_user

        app.include_router(router, prefix="/manager/v1")

        return TestClient(app)

    def test_get_version_adoption(self, test_client):
        """Test getting version adoption data."""
        response = test_client.get("/manager/v1/versions/adoption")

        assert response.status_code == 200
        data = response.json()

        # Check latest versions
        assert "latest_versions" in data
        assert "agent_image" in data["latest_versions"]
        assert "gui_image" in data["latest_versions"]

        # Check agent versions
        assert "agent_versions" in data
        assert len(data["agent_versions"]) == 2

        agent1 = data["agent_versions"][0]
        assert agent1["agent_id"] == "agent-1"
        assert agent1["agent_name"] == "Test Agent 1"
        assert agent1["status"] == "running"
        assert agent1["current_agent_image"] == "sha256:abc123"
        assert agent1["current_gui_image"] == "sha256:def456"
        assert agent1["last_updated"] == "2025-08-02T10:30:00Z"

        # Check deployment info
        assert "current_deployment" in data
        assert data["current_deployment"] is None

        assert "recent_deployments" in data
        assert len(data["recent_deployments"]) == 2

        # Check deployments are sorted by completed_at descending
        deploy1 = data["recent_deployments"][0]
        assert deploy1["deployment_id"] == "deploy-2"
        assert deploy1["message"] == "Feature release"

    def test_version_adoption_with_active_deployment(self, test_client, mock_orchestrator):
        """Test version adoption with active deployment."""
        # Mock active deployment
        active_deployment = DeploymentStatus(
            deployment_id="deploy-active",
            agents_total=10,
            agents_updated=3,
            agents_deferred=0,
            agents_failed=0,
            started_at="2025-08-02T11:00:00Z",
            completed_at=None,
            status="in_progress",
            message="Emergency patch",
            canary_phase="explorers",
        )

        # Update the mock to return the active deployment
        async def mock_get_active():
            return active_deployment

        mock_orchestrator.get_current_deployment.side_effect = mock_get_active

        response = test_client.get("/manager/v1/versions/adoption")

        assert response.status_code == 200
        data = response.json()

        assert data["current_deployment"] is not None
        assert data["current_deployment"]["deployment_id"] == "deploy-active"
        assert data["current_deployment"]["status"] == "in_progress"
        assert data["current_deployment"]["agents_updated"] == 3

    def test_version_adoption_no_metadata(self, test_client, mock_manager):
        """Test version adoption when agent has no metadata."""
        # Mock agent without metadata
        mock_manager.agent_registry.get_agent.return_value = None

        response = test_client.get("/manager/v1/versions/adoption")

        assert response.status_code == 200
        data = response.json()

        # Check agent versions show unknown
        agent1 = data["agent_versions"][0]
        assert agent1["current_agent_image"] == "unknown"
        assert agent1["current_gui_image"] == "unknown"
        assert agent1["last_updated"] == "never"
