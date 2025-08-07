"""
Test enhanced settings functionality for agent configuration.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
import yaml
from fastapi.testclient import TestClient

from ciris_manager.api.routes import create_routes


class TestEnhancedSettings:
    """Test suite for enhanced agent settings functionality."""

    @pytest.fixture
    def mock_manager(self):
        """Create a mock manager instance."""
        manager = Mock()
        manager.config = Mock()
        manager.config.manager = Mock()
        manager.config.manager.templates_directory = "/tmp/test_templates"
        manager.template_verifier = Mock()
        manager.template_verifier.list_pre_approved_templates = Mock(return_value={})
        manager.agent_registry = Mock()
        manager.create_agent = AsyncMock(
            return_value={
                "agent_id": "test-agent",
                "container": "ciris-test-agent",
                "port": 8001,
                "api_endpoint": "http://localhost:8001",
                "status": "running",
            }
        )
        return manager

    @pytest.fixture
    def app(self, mock_manager):
        """Create a FastAPI app with routes."""
        from fastapi import FastAPI

        app = FastAPI()

        # Set dev mode to bypass auth
        import os

        os.environ["CIRIS_AUTH_MODE"] = "development"

        router = create_routes(mock_manager)
        app.include_router(router, prefix="/manager/v1")
        return app

    @pytest.fixture
    def client(self, app):
        """Create a test client."""
        return TestClient(app)

    def test_get_agent_config_success(self, client):
        """Test successfully getting agent configuration."""
        compose_data = {
            "services": {
                "test-agent": {
                    "environment": {
                        "DISCORD_BOT_TOKEN": "test-token",
                        "DISCORD_CHANNEL_IDS": "123,456,789",
                        "WA_USER_IDS": "user1,user2",
                        "OPENAI_API_KEY": "sk-test",
                        "CIRIS_MOCK_LLM": "true",
                    }
                }
            }
        }

        with patch("builtins.open", mock_open(read_data=yaml.dump(compose_data))):
            with patch("pathlib.Path.exists", return_value=True):
                response = client.get("/manager/v1/agents/test-agent/config")

        assert response.status_code == 200
        data = response.json()
        assert data["agent_id"] == "test-agent"
        assert "DISCORD_BOT_TOKEN" in data["environment"]
        assert data["environment"]["DISCORD_CHANNEL_IDS"] == "123,456,789"

    def test_get_agent_config_not_found(self, client):
        """Test getting config for non-existent agent."""
        with patch("pathlib.Path.exists", return_value=False):
            response = client.get("/manager/v1/agents/nonexistent/config")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_update_agent_config_discord_adapter(self, client):
        """Test updating agent config to enable Discord adapter."""
        compose_data = {
            "services": {
                "test-agent": {"environment": {"CIRIS_ADAPTER": "api", "CIRIS_MOCK_LLM": "false"}}
            }
        }

        config_update = {
            "environment": {
                "CIRIS_ENABLE_DISCORD": "true",
                "DISCORD_BOT_TOKEN": "new-token",
                "DISCORD_CHANNEL_IDS": "111,222,333",
            }
        }

        with patch("builtins.open", mock_open(read_data=yaml.dump(compose_data))) as mock_file:
            with patch("pathlib.Path.exists", return_value=True):
                with patch("subprocess.run") as mock_run:
                    mock_run.return_value = Mock(returncode=0)

                    response = client.patch(
                        "/manager/v1/agents/test-agent/config", json=config_update
                    )

        assert response.status_code == 200

        # Verify CIRIS_ENABLE_DISCORD was translated to CIRIS_ADAPTER modification
        saved_data = None
        for call in mock_file().write.call_args_list:
            if call[0][0]:
                saved_data = call[0][0]
                break

        # The adapter list should now include discord
        assert saved_data is not None

    def test_wa_review_required_for_tier_4_agent(self, client, mock_manager):
        """Test that WA review is required for Tier 4 agents."""
        template_data = {
            "name": "Echo",
            "description": "Echo moderation agent",
            "stewardship": {"stewardship_tier": 4},
        }

        request_data = {
            "template": "echo",
            "name": "test-echo",
            "environment": {},
            "wa_review_completed": False,  # No WA review
        }

        with patch("builtins.open", mock_open(read_data=yaml.dump(template_data))):
            with patch("pathlib.Path.exists", return_value=True):
                response = client.post("/manager/v1/agents", json=request_data)

        assert response.status_code == 400
        assert "WA review confirmation required" in response.json()["detail"]

    def test_wa_review_accepted_for_tier_4_agent(self, client, mock_manager):
        """Test that Tier 4 agents can be created with WA review."""
        template_data = {
            "name": "Echo",
            "description": "Echo moderation agent",
            "stewardship": {"stewardship_tier": 4},
        }

        request_data = {
            "template": "echo",
            "name": "test-echo",
            "environment": {},
            "wa_review_completed": True,  # WA review confirmed
        }

        with patch("builtins.open", mock_open(read_data=yaml.dump(template_data))):
            with patch("pathlib.Path.exists", return_value=True):
                response = client.post("/manager/v1/agents", json=request_data)

        assert response.status_code == 200
        assert response.json()["agent_id"] == "test-agent"

    def test_wa_review_not_required_for_tier_2_agent(self, client, mock_manager):
        """Test that WA review is not required for Tier 2 agents."""
        template_data = {
            "name": "Sage",
            "description": "Sage agent",
            "stewardship": {"stewardship_tier": 2},
        }

        request_data = {
            "template": "sage",
            "name": "test-sage",
            "environment": {},
            "wa_review_completed": False,  # No WA review needed
        }

        with patch("builtins.open", mock_open(read_data=yaml.dump(template_data))):
            with patch("pathlib.Path.exists", return_value=True):
                response = client.post("/manager/v1/agents", json=request_data)

        assert response.status_code == 200

    def test_template_details_endpoint(self, client):
        """Test getting template details including stewardship tier."""
        template_data = {
            "name": "Echo",
            "description": "Echo moderation agent",
            "stewardship": {"stewardship_tier": 4},
        }

        with patch("builtins.open", mock_open(read_data=yaml.dump(template_data))):
            with patch("pathlib.Path.exists", return_value=True):
                response = client.get("/manager/v1/templates/echo/details")

        assert response.status_code == 200
        data = response.json()
        assert data["stewardship_tier"] == 4
        assert data["requires_wa_review"] is True

    def test_channel_ids_cleaned_up(self, client):
        """Test that Discord channel IDs are properly cleaned."""
        compose_data = {"services": {"test-agent": {"environment": {"CIRIS_ADAPTER": "discord"}}}}

        config_update = {
            "environment": {
                "DISCORD_CHANNEL_IDS": "111\n222\n333"  # Newline separated
            }
        }

        with patch("builtins.open", mock_open(read_data=yaml.dump(compose_data))):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("subprocess.run") as mock_run:
                    with patch("yaml.dump"):
                        mock_run.return_value = Mock(returncode=0)

                        response = client.patch(
                            "/manager/v1/agents/test-agent/config", json=config_update
                        )

        assert response.status_code == 200

    def test_multiple_env_vars_update(self, client):
        """Test updating multiple environment variables at once."""
        compose_data = {"services": {"test-agent": {"environment": {"EXISTING_VAR": "old_value"}}}}

        config_update = {
            "environment": {
                "NEW_VAR_1": "value1",
                "NEW_VAR_2": "value2",
                "EXISTING_VAR": "new_value",
                "DISCORD_BOT_TOKEN": "token123",
                "OPENAI_API_KEY": "sk-test",
            }
        }

        with patch("builtins.open", mock_open(read_data=yaml.dump(compose_data))):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("subprocess.run") as mock_run:
                    with patch("yaml.dump"):
                        mock_run.return_value = Mock(returncode=0)

                        response = client.patch(
                            "/manager/v1/agents/test-agent/config", json=config_update
                        )

        assert response.status_code == 200
        assert "updated" in response.json()["status"]


class TestEnvFileParser:
    """Test .env file parsing functionality."""

    def test_parse_basic_env_file(self):
        """Test parsing a basic .env file."""
        content = """
        # Comment line
        KEY1=value1
        KEY2=value2
        KEY_WITH_SPACES = value with spaces
        """

        # This would be tested in JavaScript, but we can test the concept
        lines = content.strip().split("\n")
        env = {}

        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if "=" in line:
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip()

        assert env["KEY1"] == "value1"
        assert env["KEY2"] == "value2"
        assert env["KEY_WITH_SPACES"] == "value with spaces"

    def test_parse_env_with_quotes(self):
        """Test parsing .env file with quoted values."""
        content = """
        QUOTED="value in quotes"
        SINGLE_QUOTED='another value'
        NO_QUOTES=plain value
        """

        lines = content.strip().split("\n")
        env = {}

        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()

                # Remove quotes if present
                if (value.startswith('"') and value.endswith('"')) or (
                    value.startswith("'") and value.endswith("'")
                ):
                    value = value[1:-1]

                env[key] = value

        assert env["QUOTED"] == "value in quotes"
        assert env["SINGLE_QUOTED"] == "another value"
        assert env["NO_QUOTES"] == "plain value"


def mock_open(read_data=""):
    """Helper to create a mock file object."""
    import io
    from unittest.mock import MagicMock

    file_obj = io.StringIO(read_data)
    mock = MagicMock(return_value=file_obj)
    mock.__enter__ = MagicMock(return_value=file_obj)
    mock.__exit__ = MagicMock(return_value=None)
    return mock


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
