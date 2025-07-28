"""
Unit tests for CIRISManager API routes.
"""

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from unittest.mock import Mock, MagicMock, AsyncMock, patch
from pathlib import Path
from ciris_manager.api.routes import create_routes
from ciris_manager.agent_registry import AgentInfo


class TestAPIRoutes:
    """Test cases for API routes."""
    
    @pytest.fixture
    def mock_manager(self):
        """Create mock CIRISManager instance."""
        manager = Mock()
        
        # Mock config
        manager.config = Mock()
        manager.config.running = True
        manager.config.manager = Mock()
        manager.config.manager.templates_directory = "/tmp/test-templates"
        
        # Mock agent registry
        manager.agent_registry = Mock()
        manager.agent_registry.list_agents = Mock(return_value=[])
        manager.agent_registry.get_agent_by_name = Mock(return_value=None)
        manager.agent_registry.get_agent = Mock(return_value=None)
        manager.agent_registry.unregister_agent = AsyncMock()
        
        # Mock port manager
        manager.port_manager = Mock()
        manager.port_manager.allocated_ports = {"agent-test": 8080}
        manager.port_manager.reserved_ports = {8888, 3000}
        manager.port_manager.start_port = 8080
        manager.port_manager.end_port = 8200
        
        # Mock template verifier
        manager.template_verifier = Mock()
        manager.template_verifier.list_pre_approved_templates = Mock(return_value={
            "scout": "Scout template",
            "sage": "Sage template"
        })
        
        # Mock status
        manager.get_status = Mock(return_value={
            'running': True,
            'components': {
                'watchdog': 'running',
                'container_manager': 'running'
            }
        })
        
        # Mock create_agent as async
        manager.create_agent = AsyncMock()
        
        # Mock delete_agent as async
        manager.delete_agent = AsyncMock(return_value=True)
        
        return manager
    
    @pytest.fixture
    def mock_auth(self):
        """Mock authentication dependency."""
        def override_get_current_user():
            return {
                "id": "test-user-id",
                "email": "test@example.com",
                "name": "Test User"
            }
        return override_get_current_user
    
    @pytest.fixture
    def client(self, mock_manager, mock_auth):
        """Create test client with auth mocked."""
        app = FastAPI()
        
        # Import the dependency we need to override
        from ciris_manager.api.auth import get_current_user_dependency as get_current_user
        
        # Override the authentication dependency
        app.dependency_overrides[get_current_user] = mock_auth
        
        router = create_routes(mock_manager)
        app.include_router(router, prefix="/manager/v1")
        return TestClient(app)
    
    def test_health_check(self, client):
        """Test health check endpoint."""
        response = client.get("/manager/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "ciris-manager"
    
    def test_get_status(self, client, mock_manager):
        """Test status endpoint."""
        response = client.get("/manager/v1/status")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
        assert data["version"] == "1.0.0"
        assert "components" in data
        assert data["components"]["watchdog"] == "running"
    
    @patch('ciris_manager.docker_discovery.DockerAgentDiscovery')
    def test_list_agents_empty(self, mock_discovery_class, client):
        """Test listing agents when none exist."""
        # Mock the discovery instance
        mock_discovery = Mock()
        mock_discovery.discover_agents.return_value = []
        mock_discovery_class.return_value = mock_discovery
        
        response = client.get("/manager/v1/agents")
        assert response.status_code == 200
        data = response.json()
        assert data["agents"] == []
    
    @patch('ciris_manager.docker_discovery.DockerAgentDiscovery')
    def test_list_agents_with_data(self, mock_discovery_class, client, mock_manager):
        """Test listing agents with data."""
        # Mock the discovery instance with Docker-style agent data
        mock_discovery = Mock()
        mock_agents = [
            {
                "agent_id": "agent-scout",
                "agent_name": "Agent Scout",
                "container_name": "ciris-agent-scout",
                "container_id": "abc123def456",
                "status": "running",
                "health": "healthy",
                "api_endpoint": "http://localhost:8081",
                "api_port": "8081",
                "created_at": "2025-01-01T00:00:00Z",
                "started_at": "2025-01-01T00:01:00Z",
                "exit_code": 0,
                "environment": {
                    "CIRIS_ADAPTER": "api",
                    "CIRIS_MOCK_LLM": "true",
                    "CIRIS_PORT": "8080"
                },
                "labels": {},
                "image": "ghcr.io/cirisai/ciris-agent:latest",
                "restart_policy": "unless-stopped"
            },
            {
                "agent_id": "agent-sage",
                "agent_name": "Agent Sage",
                "container_name": "ciris-agent-sage",
                "container_id": "def456ghi789",
                "status": "running",
                "health": "healthy",
                "api_endpoint": "http://localhost:8082",
                "api_port": "8082",
                "created_at": "2025-01-01T00:02:00Z",
                "started_at": "2025-01-01T00:03:00Z",
                "exit_code": 0,
                "environment": {
                    "CIRIS_ADAPTER": "api",
                    "CIRIS_MOCK_LLM": "true",
                    "CIRIS_PORT": "8080"
                },
                "labels": {},
                "image": "ghcr.io/cirisai/ciris-agent:latest",
                "restart_policy": "unless-stopped"
            }
        ]
        mock_discovery.discover_agents.return_value = mock_agents
        mock_discovery_class.return_value = mock_discovery
        
        response = client.get("/manager/v1/agents")
        assert response.status_code == 200
        data = response.json()
        assert len(data["agents"]) == 2
        
        # Check first agent
        assert data["agents"][0]["agent_id"] == "agent-scout"
        assert data["agents"][0]["agent_name"] == "Agent Scout"
        assert data["agents"][0]["api_endpoint"] == "http://localhost:8081"
    
    def test_get_agent_exists(self, client, mock_manager):
        """Test getting specific agent that exists."""
        agent = AgentInfo(
            agent_id="agent-scout",
            name="Scout",
            port=8081,
            template="scout",
            compose_file="/path/to/scout/docker-compose.yml"
        )
        
        mock_manager.agent_registry.get_agent_by_name.return_value = agent
        
        response = client.get("/manager/v1/agents/scout")
        assert response.status_code == 200
        data = response.json()
        assert data["agent_id"] == "agent-scout"
        assert data["name"] == "Scout"
        assert data["port"] == 8081
    
    def test_get_agent_not_found(self, client, mock_manager):
        """Test getting agent that doesn't exist."""
        mock_manager.agent_registry.get_agent_by_name.return_value = None
        
        response = client.get("/manager/v1/agents/nonexistent")
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"]
    
    def test_create_agent_success(self, client, mock_manager):
        """Test successful agent creation."""
        mock_manager.create_agent.return_value = {
            "agent_id": "agent-scout",
            "container": "ciris-agent-scout",
            "port": 8081,
            "api_endpoint": "http://localhost:8081",
            "compose_file": "/path/to/compose.yml",
            "status": "starting"
        }
        
        response = client.post("/manager/v1/agents", json={
            "template": "scout",
            "name": "Scout",
            "environment": {"CUSTOM": "value"}
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["agent_id"] == "agent-scout"
        assert data["name"] == "Scout"
        assert data["container"] == "ciris-agent-scout"
        assert data["port"] == 8081
        assert data["status"] == "starting"
        
        # Verify create_agent was called correctly
        mock_manager.create_agent.assert_called_once_with(
            template="scout",
            name="Scout",
            environment={"CUSTOM": "value"},
            wa_signature=None
        )
    
    def test_create_agent_with_wa_signature(self, client, mock_manager):
        """Test agent creation with WA signature."""
        mock_manager.create_agent.return_value = {
            "agent_id": "agent-custom",
            "container": "ciris-agent-custom",
            "port": 8083,
            "api_endpoint": "http://localhost:8083",
            "compose_file": "/path/to/compose.yml",
            "status": "starting"
        }
        
        response = client.post("/manager/v1/agents", json={
            "template": "custom",
            "name": "Custom",
            "wa_signature": "test_signature"
        })
        
        assert response.status_code == 200
        mock_manager.create_agent.assert_called_once_with(
            template="custom",
            name="Custom",
            environment=None,
            wa_signature="test_signature"
        )
    
    def test_create_agent_invalid_template(self, client, mock_manager):
        """Test agent creation with invalid template."""
        mock_manager.create_agent.side_effect = ValueError("Template not found")
        
        response = client.post("/manager/v1/agents", json={
            "template": "nonexistent",
            "name": "Test"
        })
        
        assert response.status_code == 400
        data = response.json()
        assert "Template not found" in data["detail"]
    
    def test_create_agent_permission_denied(self, client, mock_manager):
        """Test agent creation without permission."""
        mock_manager.create_agent.side_effect = PermissionError("WA signature required")
        
        response = client.post("/manager/v1/agents", json={
            "template": "custom",
            "name": "Custom"
        })
        
        assert response.status_code == 403
        data = response.json()
        assert "WA signature required" in data["detail"]
    
    def test_create_agent_internal_error(self, client, mock_manager):
        """Test agent creation with internal error."""
        mock_manager.create_agent.side_effect = Exception("Internal error")
        
        response = client.post("/manager/v1/agents", json={
            "template": "scout",
            "name": "Scout"
        })
        
        assert response.status_code == 500
        data = response.json()
        assert "Failed to create agent" in data["detail"]
    
    def test_delete_agent_exists(self, client, mock_manager):
        """Test deleting existing agent."""
        agent = AgentInfo(
            agent_id="agent-scout",
            name="Scout",
            port=8081,
            template="scout",
            compose_file="/path/to/scout/docker-compose.yml"
        )
        
        mock_manager.agent_registry.get_agent.return_value = agent
        
        response = client.delete("/manager/v1/agents/scout")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "deleted"
        assert data["agent_id"] == "scout"
        
        # Verify delete_agent was called
        mock_manager.delete_agent.assert_called_once_with("scout")
    
    def test_delete_agent_operation_failed(self, client, mock_manager):
        """Test deleting agent when operation fails."""
        agent = AgentInfo(
            agent_id="agent-scout",
            name="Scout",
            port=8081,
            template="scout",
            compose_file="/path/to/scout/docker-compose.yml"
        )
        
        mock_manager.agent_registry.get_agent.return_value = agent
        mock_manager.delete_agent.return_value = False  # Deletion failed
        
        response = client.delete("/manager/v1/agents/scout")
        assert response.status_code == 500
        data = response.json()
        assert "Failed to delete agent" in data["detail"]
    
    def test_delete_agent_not_found(self, client, mock_manager):
        """Test deleting non-existent agent."""
        mock_manager.agent_registry.get_agent.return_value = None
        
        response = client.delete("/manager/v1/agents/nonexistent")
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"]
    
    @patch('ciris_manager.docker_discovery.DockerAgentDiscovery')
    def test_delete_discovered_agent_not_managed(self, mock_discovery_class, client, mock_manager):
        """Test deleting a discovered agent that wasn't created by CIRISManager."""
        # Agent not in registry
        mock_manager.agent_registry.get_agent.return_value = None
        
        # But agent exists in Docker discovery
        mock_discovery = Mock()
        mock_discovery.discover_agents.return_value = [
            {
                "agent_id": "external-agent",
                "agent_name": "External Agent",
                "container_name": "ciris-external-agent"
            }
        ]
        mock_discovery_class.return_value = mock_discovery
        
        response = client.delete("/manager/v1/agents/external-agent")
        assert response.status_code == 400
        data = response.json()
        assert "was not created by CIRISManager" in data["detail"]
        assert "docker-compose" in data["detail"]
    
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.glob')
    def test_list_templates(self, mock_glob, mock_exists, client, mock_manager):
        """Test listing templates."""
        # Mock template directory exists
        mock_exists.return_value = True
        
        # Mock template files
        mock_template_files = [
            Mock(stem="scout"),
            Mock(stem="sage")
        ]
        mock_glob.return_value = mock_template_files
        
        response = client.get("/manager/v1/templates")
        assert response.status_code == 200
        data = response.json()
        assert "scout" in data["templates"]
        assert "sage" in data["templates"]
        assert data["templates"]["scout"] == "Scout agent template"
        assert "scout" in data["pre_approved"]
        assert "sage" in data["pre_approved"]
    
    def test_get_allocated_ports(self, client, mock_manager):
        """Test getting allocated ports."""
        response = client.get("/manager/v1/ports/allocated")
        assert response.status_code == 200
        data = response.json()
        assert data["allocated"] == {"agent-test": 8080}
        assert 8888 in data["reserved"]
        assert 3000 in data["reserved"]
        assert data["range"]["start"] == 8080
        assert data["range"]["end"] == 8200
    
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.read_text')
    def test_get_default_env_exists(self, mock_read_text, mock_exists, client):
        """Test getting default env when file exists."""
        mock_exists.return_value = True
        mock_read_text.return_value = "CIRIS_MOCK_LLM=true\nCIRIS_LOG_LEVEL=DEBUG"
        
        response = client.get("/manager/v1/env/default")
        assert response.status_code == 200
        data = response.json()
        assert data["content"] == "CIRIS_MOCK_LLM=true\nCIRIS_LOG_LEVEL=DEBUG"
    
    @patch('pathlib.Path.exists')
    def test_get_default_env_not_exists(self, mock_exists, client):
        """Test getting default env when file doesn't exist."""
        mock_exists.return_value = False
        
        response = client.get("/manager/v1/env/default")
        assert response.status_code == 200
        data = response.json()
        assert data["content"] == ""
    
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.read_text')
    def test_get_default_env_read_error(self, mock_read_text, mock_exists, client):
        """Test getting default env when read fails."""
        mock_exists.return_value = True
        mock_read_text.side_effect = Exception("Permission denied")
        
        response = client.get("/manager/v1/env/default")
        assert response.status_code == 200
        data = response.json()
        assert data["content"] == ""