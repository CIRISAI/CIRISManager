"""
Unit tests for LLM configuration API routes.
"""

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from unittest.mock import Mock, AsyncMock

from ciris_manager.api.routes import create_routes
from ciris_manager.agent_registry import RegisteredAgent


class TestLLMRoutes:
    """Test cases for LLM configuration routes."""

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

        # Mock port manager
        manager.port_manager = Mock()
        manager.port_manager.allocated_ports = {}

        # Mock template verifier
        manager.template_verifier = Mock()
        manager.template_verifier.list_pre_approved_templates = Mock(return_value={})

        # Mock docker_client to prevent discovery issues
        manager.docker_client = None

        # Mock regenerate_agent_compose and restart_container
        manager.regenerate_agent_compose = AsyncMock()
        manager.restart_container = AsyncMock(return_value=True)

        return manager

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

    @pytest.fixture
    def sample_agent(self):
        """Create a sample registered agent."""
        return RegisteredAgent(
            agent_id="test-agent",
            name="Test",
            port=8081,
            template="base",
            compose_file="/path/to/docker-compose.yml",
        )

    @pytest.fixture
    def sample_llm_config(self):
        """Sample LLM config as stored in registry."""
        return {
            "primary": {
                "provider": "together",
                "api_key": "test-together-key-12345",
                "model": "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8",
                "api_base": "https://api.together.xyz/v1",
            },
            "backup": {
                "provider": "groq",
                "api_key": "gsk_test-groq-key-67890",
                "model": "meta-llama/llama-4-maverick-17b-128e-instruct",
                "api_base": "https://api.groq.com/openai/v1",
            },
        }

    def test_get_llm_config(self, client, mock_manager, sample_agent, sample_llm_config):
        """Test getting LLM configuration."""
        mock_manager.agent_registry.get_agents_by_agent_id.return_value = [sample_agent]
        mock_manager.agent_registry.get_llm_config.return_value = sample_llm_config

        response = client.get("/manager/v1/agents/test-agent/llm")
        assert response.status_code == 200

        data = response.json()
        assert data["agent_id"] == "test-agent"
        assert data["llm_config"]["primary"]["provider"] == "together"
        assert (
            data["llm_config"]["primary"]["model"]
            == "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8"
        )
        # API key should be redacted
        assert "api_key_hint" in data["llm_config"]["primary"]
        assert "api_key" not in data["llm_config"]["primary"]

    def test_get_llm_config_not_set(self, client, mock_manager, sample_agent):
        """Test getting LLM config when none is set."""
        mock_manager.agent_registry.get_agents_by_agent_id.return_value = [sample_agent]
        mock_manager.agent_registry.get_llm_config.return_value = None

        response = client.get("/manager/v1/agents/test-agent/llm")
        assert response.status_code == 200

        data = response.json()
        assert data["llm_config"] is None
        assert "environment variables" in data["message"]

    def test_get_llm_config_agent_not_found(self, client, mock_manager):
        """Test getting LLM config for non-existent agent."""
        mock_manager.agent_registry.get_agents_by_agent_id.return_value = []

        response = client.get("/manager/v1/agents/nonexistent/llm")
        assert response.status_code == 404

    def test_patch_llm_config_primary_model(
        self, client, mock_manager, sample_agent, sample_llm_config
    ):
        """Test patching only the primary model."""
        mock_manager.agent_registry.get_agents_by_agent_id.return_value = [sample_agent]
        mock_manager.agent_registry.get_llm_config.return_value = sample_llm_config
        mock_manager.agent_registry.set_llm_config.return_value = True

        response = client.patch(
            "/manager/v1/agents/test-agent/llm?restart=false",
            json={"primary_model": "google/gemma-4-31B-it"},
        )
        assert response.status_code == 200

        data = response.json()
        assert "primary_model=google/gemma-4-31B-it" in data["changes"]

        # Verify set_llm_config was called with merged config
        call_args = mock_manager.agent_registry.set_llm_config.call_args
        saved_config = call_args[0][1]  # Second positional arg is the config

        # Primary model should be updated
        assert saved_config["primary"]["model"] == "google/gemma-4-31B-it"
        # Primary API key should be preserved
        assert saved_config["primary"]["api_key"] == "test-together-key-12345"
        # Backup should be unchanged
        assert saved_config["backup"]["model"] == "meta-llama/llama-4-maverick-17b-128e-instruct"

    def test_patch_llm_config_backup_model(
        self, client, mock_manager, sample_agent, sample_llm_config
    ):
        """Test patching only the backup model."""
        mock_manager.agent_registry.get_agents_by_agent_id.return_value = [sample_agent]
        mock_manager.agent_registry.get_llm_config.return_value = sample_llm_config
        mock_manager.agent_registry.set_llm_config.return_value = True

        response = client.patch(
            "/manager/v1/agents/test-agent/llm?restart=false",
            json={"backup_model": "meta-llama/llama-4-scout-17b-16e-instruct"},
        )
        assert response.status_code == 200

        data = response.json()
        assert "backup_model=meta-llama/llama-4-scout-17b-16e-instruct" in data["changes"]

        # Verify the config was updated correctly
        call_args = mock_manager.agent_registry.set_llm_config.call_args
        saved_config = call_args[0][1]

        # Primary should be unchanged
        assert (
            saved_config["primary"]["model"] == "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8"
        )
        # Backup model should be updated
        assert saved_config["backup"]["model"] == "meta-llama/llama-4-scout-17b-16e-instruct"
        # Backup API key should be preserved
        assert saved_config["backup"]["api_key"] == "gsk_test-groq-key-67890"

    def test_patch_llm_config_both_models(
        self, client, mock_manager, sample_agent, sample_llm_config
    ):
        """Test patching both primary and backup models."""
        mock_manager.agent_registry.get_agents_by_agent_id.return_value = [sample_agent]
        mock_manager.agent_registry.get_llm_config.return_value = sample_llm_config
        mock_manager.agent_registry.set_llm_config.return_value = True

        response = client.patch(
            "/manager/v1/agents/test-agent/llm?restart=false",
            json={
                "primary_model": "google/gemma-4-31B-it",
                "backup_model": "meta-llama/llama-4-scout-17b-16e-instruct",
            },
        )
        assert response.status_code == 200

        data = response.json()
        assert len(data["changes"]) == 2
        assert "primary_model=google/gemma-4-31B-it" in data["changes"]
        assert "backup_model=meta-llama/llama-4-scout-17b-16e-instruct" in data["changes"]

    def test_patch_llm_config_no_changes(
        self, client, mock_manager, sample_agent, sample_llm_config
    ):
        """Test patching with no changes provided."""
        mock_manager.agent_registry.get_agents_by_agent_id.return_value = [sample_agent]
        mock_manager.agent_registry.get_llm_config.return_value = sample_llm_config

        response = client.patch(
            "/manager/v1/agents/test-agent/llm?restart=false",
            json={},
        )
        assert response.status_code == 200

        data = response.json()
        assert data["message"] == "No changes provided"
        # set_llm_config should not be called
        mock_manager.agent_registry.set_llm_config.assert_not_called()

    def test_patch_llm_config_no_existing_config(self, client, mock_manager, sample_agent):
        """Test patching when no config exists."""
        mock_manager.agent_registry.get_agents_by_agent_id.return_value = [sample_agent]
        mock_manager.agent_registry.get_llm_config.return_value = None

        response = client.patch(
            "/manager/v1/agents/test-agent/llm?restart=false",
            json={"primary_model": "google/gemma-4-31B-it"},
        )
        assert response.status_code == 404
        assert "No LLM configuration exists" in response.json()["detail"]

    def test_patch_llm_config_agent_not_found(self, client, mock_manager):
        """Test patching config for non-existent agent."""
        mock_manager.agent_registry.get_agents_by_agent_id.return_value = []

        response = client.patch(
            "/manager/v1/agents/nonexistent/llm?restart=false",
            json={"primary_model": "google/gemma-4-31B-it"},
        )
        assert response.status_code == 404

    def test_patch_llm_config_with_restart(
        self, client, mock_manager, sample_agent, sample_llm_config
    ):
        """Test patching config with container restart."""
        mock_manager.agent_registry.get_agents_by_agent_id.return_value = [sample_agent]
        mock_manager.agent_registry.get_llm_config.return_value = sample_llm_config
        mock_manager.agent_registry.set_llm_config.return_value = True

        response = client.patch(
            "/manager/v1/agents/test-agent/llm",  # restart=true by default
            json={"primary_model": "google/gemma-4-31B-it"},
        )
        assert response.status_code == 200

        data = response.json()
        assert data["restarted"] is True
        assert "container restarted" in data["message"]

        # Verify restart was called
        mock_manager.regenerate_agent_compose.assert_called_once()
        mock_manager.restart_container.assert_called_once()

    def test_patch_llm_config_provider_change(
        self, client, mock_manager, sample_agent, sample_llm_config
    ):
        """Test patching the provider."""
        mock_manager.agent_registry.get_agents_by_agent_id.return_value = [sample_agent]
        mock_manager.agent_registry.get_llm_config.return_value = sample_llm_config
        mock_manager.agent_registry.set_llm_config.return_value = True

        response = client.patch(
            "/manager/v1/agents/test-agent/llm?restart=false",
            json={"primary_provider": "openai"},
        )
        assert response.status_code == 200

        data = response.json()
        assert "primary_provider=openai" in data["changes"]

        # Verify provider was updated
        call_args = mock_manager.agent_registry.set_llm_config.call_args
        saved_config = call_args[0][1]
        assert saved_config["primary"]["provider"] == "openai"

    def test_patch_llm_config_no_backup(self, client, mock_manager, sample_agent):
        """Test patching config that has no backup configured."""
        config_no_backup = {
            "primary": {
                "provider": "together",
                "api_key": "test-key",
                "model": "some-model",
                "api_base": "https://api.together.xyz/v1",
            }
        }

        mock_manager.agent_registry.get_agents_by_agent_id.return_value = [sample_agent]
        mock_manager.agent_registry.get_llm_config.return_value = config_no_backup
        mock_manager.agent_registry.set_llm_config.return_value = True

        # Patching backup_model when no backup exists should work but not add a backup
        response = client.patch(
            "/manager/v1/agents/test-agent/llm?restart=false",
            json={"primary_model": "new-model"},
        )
        assert response.status_code == 200

        call_args = mock_manager.agent_registry.set_llm_config.call_args
        saved_config = call_args[0][1]
        assert "backup" not in saved_config
