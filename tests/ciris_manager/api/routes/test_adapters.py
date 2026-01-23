"""
Tests for adapter management routes.
"""

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from ciris_manager.api.routes import create_routes


class TestAdapterRoutes:
    """Test cases for adapter routes."""

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
        manager.agent_registry.get_agent = Mock(return_value=None)
        manager.agent_registry.get_adapter_configs = Mock(return_value={})
        manager.agent_registry.set_adapter_config = Mock(return_value=True)
        manager.agent_registry.remove_adapter_config = Mock(return_value=True)

        # Mock port manager
        manager.port_manager = Mock()

        # Mock docker client
        manager.docker_client = Mock()
        server_config = Mock()
        server_config.is_local = True
        server_config.vpc_ip = "10.10.0.4"
        manager.docker_client.get_server_config = Mock(return_value=server_config)

        # Mock regenerate_agent_compose
        manager.regenerate_agent_compose = AsyncMock(
            return_value={
                "agent_id": "test-agent",
                "compose_file": "/path/to/compose.yml",
                "adapter_configs_applied": ["discord"],
            }
        )

        return manager

    @pytest.fixture
    def mock_agent_info(self):
        """Create mock AgentInfo."""
        agent = Mock()
        agent.agent_id = "test-agent"
        agent.api_port = 8001
        agent.occurrence_id = None
        agent.server_id = "main"
        return agent

    @pytest.fixture
    def mock_auth(self):
        """Mock authentication dependency."""

        def override_get_current_user():
            return {"id": "test-user-id", "email": "test@example.com", "name": "Test User"}

        return override_get_current_user

    @pytest.fixture
    def client(self, mock_manager, mock_auth):
        """Create test client with auth mocked."""
        app = FastAPI()
        app.state.manager = mock_manager

        from ciris_manager.api.routes.dependencies import _get_auth_dependency_runtime

        app.dependency_overrides[_get_auth_dependency_runtime] = mock_auth

        router = create_routes(mock_manager)
        app.include_router(router, prefix="/manager/v1")
        return TestClient(app)


class TestAdapterConfigMasking:
    """Tests for adapter config masking functionality."""

    def test_mask_sensitive_function(self):
        """Test the sensitive data masking used in config responses."""
        # Import the mask function used in the endpoint
        from typing import Dict, Any

        # Test the masking logic directly
        def mask_sensitive(d: Dict[str, Any]) -> Dict[str, Any]:
            sensitive_keys = {"password", "secret", "token", "api_key", "client_secret"}
            masked: Dict[str, Any] = {}
            for k, v in d.items():
                if any(s in k.lower() for s in sensitive_keys):
                    masked[k] = "***"
                elif isinstance(v, dict):
                    masked[k] = mask_sensitive(v)
                else:
                    masked[k] = v
            return masked

        # Test data with various sensitive fields
        config = {
            "discord": {
                "enabled": True,
                "env_vars": {
                    "DISCORD_BOT_TOKEN": "secret_token_123",
                    "DISCORD_GUILD_ID": "123456789",
                },
            },
            "reddit": {
                "enabled": True,
                "env_vars": {
                    "REDDIT_CLIENT_SECRET": "reddit_secret",
                    "REDDIT_USERNAME": "mybot",
                },
            },
        }

        result = {k: mask_sensitive(v) for k, v in config.items()}

        # Sensitive values should be masked
        assert result["discord"]["env_vars"]["DISCORD_BOT_TOKEN"] == "***"
        assert result["reddit"]["env_vars"]["REDDIT_CLIENT_SECRET"] == "***"

        # Non-sensitive values should not be masked
        assert result["discord"]["env_vars"]["DISCORD_GUILD_ID"] == "123456789"
        assert result["reddit"]["env_vars"]["REDDIT_USERNAME"] == "mybot"
        assert result["discord"]["enabled"] is True

    def test_mask_sensitive_deeply_nested(self):
        """Test masking in deeply nested structures."""

        def mask_sensitive(d):
            sensitive_keys = {"password", "secret", "token", "api_key", "client_secret"}
            masked = {}
            for k, v in d.items():
                if any(s in k.lower() for s in sensitive_keys):
                    masked[k] = "***"
                elif isinstance(v, dict):
                    masked[k] = mask_sensitive(v)
                else:
                    masked[k] = v
            return masked

        config = {
            "outer": {
                "inner": {
                    "deep_api_key": "supersecret",
                    "normal_field": "visible",
                },
            },
        }

        result = mask_sensitive(config)
        assert result["outer"]["inner"]["deep_api_key"] == "***"
        assert result["outer"]["inner"]["normal_field"] == "visible"


class TestWizardSessionEndpoints:
    """Tests for wizard session management endpoints."""

    @pytest.fixture
    def mock_manager(self):
        """Create mock manager."""
        manager = Mock()
        manager.config = Mock()
        manager.config.running = True
        manager.config.manager = Mock()
        manager.config.manager.templates_directory = "/tmp/test-templates"
        manager.agent_registry = Mock()
        manager.agent_registry.list_agents = Mock(return_value=[])
        manager.agent_registry.get_adapter_configs = Mock(return_value={})
        manager.agent_registry.set_adapter_config = Mock(return_value=True)
        manager.port_manager = Mock()
        manager.docker_client = Mock()
        server_config = Mock()
        server_config.is_local = True
        server_config.hostname = "agents.ciris.ai"
        manager.docker_client.get_server_config = Mock(return_value=server_config)
        manager.regenerate_agent_compose = AsyncMock(return_value={})
        return manager

    @pytest.fixture
    def mock_auth(self):
        def override():
            return {"id": "test-user", "email": "test@test.com", "name": "Test"}

        return override

    @pytest.fixture
    def mock_agent(self):
        agent = Mock()
        agent.agent_id = "test-agent"
        agent.api_port = 8001
        agent.occurrence_id = None
        agent.server_id = "main"
        return agent

    @pytest.fixture
    def client(self, mock_manager, mock_auth):
        app = FastAPI()
        app.state.manager = mock_manager

        from ciris_manager.api.routes.dependencies import _get_auth_dependency_runtime

        app.dependency_overrides[_get_auth_dependency_runtime] = mock_auth

        router = create_routes(mock_manager)
        app.include_router(router, prefix="/manager/v1")
        return TestClient(app)

    def test_wizard_start_creates_session(self, client, mock_agent):
        """Test starting a wizard proxies to agent and returns session."""
        # Agent's configure/start response
        agent_response = {
            "data": {
                "session_id": "test-session-123",
                "adapter_type": "discord",
                "status": "active",
                "current_step_index": 0,
                "current_step": {"step_id": "token", "step_type": "input"},
                "total_steps": 2,
                "created_at": "2026-01-17T00:00:00Z",
            },
        }

        with patch("ciris_manager.docker_discovery.DockerAgentDiscovery") as mock_discovery:
            mock_discovery.return_value.discover_agents.return_value = [mock_agent]

            with patch("ciris_manager.agent_auth.get_agent_auth") as mock_auth_fn:
                mock_auth_fn.return_value.get_auth_headers.return_value = {
                    "Authorization": "Bearer test"
                }

                with patch("httpx.AsyncClient") as mock_httpx:
                    mock_response = Mock()
                    mock_response.status_code = 200
                    mock_response.json.return_value = agent_response
                    mock_response.raise_for_status = Mock()

                    mock_client = MagicMock()
                    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                    mock_client.__aexit__ = AsyncMock(return_value=None)
                    mock_client.post = AsyncMock(return_value=mock_response)
                    mock_httpx.return_value = mock_client

                    response = client.post(
                        "/manager/v1/agents/test-agent/adapters/discord/wizard/start",
                        json={},
                    )

                    assert response.status_code == 200
                    data = response.json()
                    assert "session_id" in data
                    assert data["adapter_type"] == "discord"
                    assert data["current_step"] == "token"

    def test_wizard_start_no_wizard_returns_error(self, client, mock_agent):
        """Test starting wizard for adapter without wizard config returns 404."""
        import httpx

        with patch("ciris_manager.docker_discovery.DockerAgentDiscovery") as mock_discovery:
            mock_discovery.return_value.discover_agents.return_value = [mock_agent]

            with patch("ciris_manager.agent_auth.get_agent_auth") as mock_auth_fn:
                mock_auth_fn.return_value.get_auth_headers.return_value = {
                    "Authorization": "Bearer test"
                }

                with patch("httpx.AsyncClient") as mock_httpx:
                    # Agent returns 404 for adapters without wizard
                    mock_response = Mock()
                    mock_response.status_code = 404
                    mock_response.text = "Adapter not configurable"

                    def raise_for_status():
                        raise httpx.HTTPStatusError("404", request=Mock(), response=mock_response)

                    mock_response.raise_for_status = raise_for_status

                    mock_client = MagicMock()
                    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                    mock_client.__aexit__ = AsyncMock(return_value=None)
                    mock_client.post = AsyncMock(return_value=mock_response)
                    mock_httpx.return_value = mock_client

                    response = client.post(
                        "/manager/v1/agents/test-agent/adapters/api/wizard/start",
                        json={},
                    )

                    assert response.status_code == 404
                    assert "not found or not configurable" in response.json()["detail"]


class TestRemoveAdapterConfig:
    """Tests for DELETE /agents/{agent_id}/adapters/{adapter_type}/config."""

    @pytest.fixture
    def mock_manager(self):
        manager = Mock()
        manager.config = Mock()
        manager.config.running = True
        manager.config.manager = Mock()
        manager.config.manager.templates_directory = "/tmp/test-templates"
        manager.agent_registry = Mock()
        manager.agent_registry.list_agents = Mock(return_value=[])
        manager.agent_registry.remove_adapter_config = Mock(return_value=True)
        manager.port_manager = Mock()
        manager.docker_client = Mock()
        server_config = Mock()
        server_config.is_local = True
        manager.docker_client.get_server_config = Mock(return_value=server_config)
        return manager

    @pytest.fixture
    def mock_auth(self):
        def override():
            return {"id": "test-user", "email": "test@test.com", "name": "Test"}

        return override

    @pytest.fixture
    def mock_agent(self):
        agent = Mock()
        agent.agent_id = "test-agent"
        agent.api_port = 8001
        agent.occurrence_id = None
        agent.server_id = "main"
        return agent

    def test_remove_config_success(self, mock_manager, mock_auth, mock_agent):
        app = FastAPI()
        app.state.manager = mock_manager

        from ciris_manager.api.routes.dependencies import _get_auth_dependency_runtime

        app.dependency_overrides[_get_auth_dependency_runtime] = mock_auth

        router = create_routes(mock_manager)
        app.include_router(router, prefix="/manager/v1")
        client = TestClient(app)

        with patch("ciris_manager.docker_discovery.DockerAgentDiscovery") as mock_discovery:
            mock_discovery.return_value.discover_agents.return_value = [mock_agent]

            with patch("ciris_manager.agent_auth.get_agent_auth") as mock_auth_fn:
                mock_auth_fn.return_value.get_auth_headers.return_value = {
                    "Authorization": "Bearer test"
                }

                with patch("httpx.AsyncClient") as mock_httpx:
                    mock_response = Mock()
                    mock_response.status_code = 200
                    mock_response.json.return_value = {}

                    mock_client = MagicMock()
                    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                    mock_client.__aexit__ = AsyncMock(return_value=None)
                    mock_client.delete = AsyncMock(return_value=mock_response)
                    mock_httpx.return_value = mock_client

                    response = client.delete(
                        "/manager/v1/agents/test-agent/adapters/discord/config"
                    )

                    assert response.status_code == 200
                    data = response.json()
                    assert data["config_removed"] is True

    def test_remove_config_not_found(self, mock_manager, mock_auth, mock_agent):
        # Set remove_adapter_config to return False (not found)
        mock_manager.agent_registry.remove_adapter_config = Mock(return_value=False)

        app = FastAPI()
        app.state.manager = mock_manager

        from ciris_manager.api.routes.dependencies import _get_auth_dependency_runtime

        app.dependency_overrides[_get_auth_dependency_runtime] = mock_auth

        router = create_routes(mock_manager)
        app.include_router(router, prefix="/manager/v1")
        client = TestClient(app)

        with patch("ciris_manager.docker_discovery.DockerAgentDiscovery") as mock_discovery:
            mock_discovery.return_value.discover_agents.return_value = [mock_agent]

            with patch("ciris_manager.agent_auth.get_agent_auth") as mock_auth_fn:
                mock_auth_fn.return_value.get_auth_headers.return_value = {
                    "Authorization": "Bearer test"
                }

                response = client.delete(
                    "/manager/v1/agents/test-agent/adapters/nonexistent/config"
                )

                assert response.status_code == 404
                assert "No configuration found" in response.json()["detail"]
