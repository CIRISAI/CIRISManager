"""
Test environment variable loading functionality.
"""

import pytest
from unittest.mock import Mock, patch, mock_open
import yaml
from fastapi.testclient import TestClient

from ciris_manager.api.routes import create_routes


class TestEnvLoading:
    """Test suite for environment variable loading functionality."""

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
        manager.port_manager = Mock()
        manager.port_manager.allocated_ports = {}
        manager.port_manager.reserved_ports = []
        manager.port_manager.start_port = 8000
        manager.port_manager.end_port = 9000
        return manager

    @pytest.fixture
    def app(self, mock_manager):
        """Create a FastAPI app with routes."""
        from fastapi import FastAPI
        import os

        app = FastAPI()
        # Set dev mode to bypass auth
        os.environ["CIRIS_AUTH_MODE"] = "development"

        router = create_routes(mock_manager)
        app.include_router(router, prefix="/manager/v1")
        return app

    @pytest.fixture
    def client(self, app):
        """Create a test client."""
        return TestClient(app)

    def test_env_default_endpoint_with_file(self, client):
        """Test /env/default endpoint when .env file exists."""
        env_content = """# Test environment file
OPENAI_API_KEY=test-key-123
DISCORD_BOT_TOKEN=test-token
DISCORD_CHANNEL_IDS=123,456,789
WA_USER_IDS=user1,user2
CIRIS_ADAPTER=api,discord
PROFILE_NAME=test-profile
# Comment line
OAUTH_CALLBACK_BASE_URL=https://agents.ciris.ai
"""

        with patch("pathlib.Path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=env_content)):
                response = client.get("/manager/v1/env/default")

        assert response.status_code == 200
        data = response.json()
        assert "content" in data

        # Parse the returned content
        lines = data["content"].split("\n")
        env_dict = {}
        for line in lines:
            if "=" in line:
                key, value = line.split("=", 1)
                env_dict[key] = value

        # Check that sensitive keys are cleared
        assert env_dict.get("OPENAI_API_KEY") == ""
        assert env_dict.get("DISCORD_BOT_TOKEN") == ""

        # Check that non-sensitive values are preserved
        assert env_dict.get("DISCORD_CHANNEL_IDS") == "123,456,789"
        assert env_dict.get("WA_USER_IDS") == "user1,user2"
        assert env_dict.get("OAUTH_CALLBACK_BASE_URL") == "https://agents.ciris.ai"

        # Check that essential keys are added if missing
        assert "CIRIS_API_PORT" in env_dict
        assert "CIRIS_API_HOST" in env_dict

    def test_env_default_endpoint_without_file(self, client):
        """Test /env/default endpoint when .env file doesn't exist."""
        with patch("pathlib.Path.exists", return_value=False):
            response = client.get("/manager/v1/env/default")

        assert response.status_code == 200
        data = response.json()
        assert "content" in data

        # Parse the returned content
        lines = data["content"].split("\n")
        env_dict = {}
        for line in lines:
            if "=" in line:
                key, value = line.split("=", 1)
                env_dict[key] = value

        # Check that fallback defaults are present
        assert "OPENAI_API_KEY" in env_dict
        assert "DISCORD_BOT_TOKEN" in env_dict
        assert "DISCORD_CHANNEL_IDS" in env_dict
        assert "CIRIS_API_HOST" in env_dict
        assert env_dict["CIRIS_API_HOST"] == "0.0.0.0"
        assert "CIRIS_API_PORT" in env_dict
        assert env_dict["CIRIS_API_PORT"] == "8080"
        assert "OAUTH_CALLBACK_BASE_URL" in env_dict

    def test_env_default_handles_malformed_file(self, client):
        """Test /env/default endpoint handles malformed .env file gracefully."""
        env_content = """This is not a valid env file
= no key here
KEY_WITHOUT_VALUE=
VALID_KEY=valid_value
===multiple equals===
"""

        with patch("pathlib.Path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=env_content)):
                response = client.get("/manager/v1/env/default")

        assert response.status_code == 200
        data = response.json()
        assert "content" in data

        # Should still return some valid content
        assert "VALID_KEY=valid_value" in data["content"]
        assert "KEY_WITHOUT_VALUE=" in data["content"]

    def test_env_default_filters_sensitive_keys(self, client):
        """Test that sensitive keys are properly filtered."""
        env_content = """
OPENAI_API_KEY=sk-actual-secret-key
DISCORD_BOT_TOKEN=actual-discord-token
CIRIS_OPENAI_API_KEY_2=another-secret
CIRIS_OPENAI_VISION_KEY=vision-secret
NON_SENSITIVE_KEY=public-value
WA_USER_IDS=12345,67890
"""

        with patch("pathlib.Path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=env_content)):
                response = client.get("/manager/v1/env/default")

        assert response.status_code == 200
        data = response.json()
        content = data["content"]

        # Check sensitive keys are cleared
        assert "OPENAI_API_KEY=" in content
        assert "sk-actual-secret-key" not in content
        assert "actual-discord-token" not in content
        assert "another-secret" not in content
        assert "vision-secret" not in content

        # Check non-sensitive values are preserved
        assert "NON_SENSITIVE_KEY=public-value" in content
        assert "WA_USER_IDS=12345,67890" in content

    def test_get_agent_config_with_env_file(self, client):
        """Test getting agent config that references an env_file."""
        compose_data = {
            "services": {
                "test-agent": {
                    "env_file": [".env"],
                    "environment": {"OVERRIDE_VAR": "override_value"},
                }
            }
        }

        env_file_content = """
ENV_FILE_VAR=from_env_file
SHARED_VAR=env_file_value
"""

        # Mock multiple file operations
        def mock_multi_open(path, *args, **kwargs):
            path_str = str(path)
            if path_str.endswith("docker-compose.yml"):
                return mock_open(read_data=yaml.dump(compose_data))()
            elif path_str.endswith(".env"):
                return mock_open(read_data=env_file_content)()
            return mock_open()()

        with patch("builtins.open", mock_multi_open):
            with patch("pathlib.Path.exists", return_value=True):
                response = client.get("/manager/v1/agents/test-agent/config")

        assert response.status_code == 200
        data = response.json()

        # Check that env_file variables are loaded
        assert data["environment"]["ENV_FILE_VAR"] == "from_env_file"
        assert data["environment"]["SHARED_VAR"] == "env_file_value"

        # Check that explicit environment overrides env_file
        assert data["environment"]["OVERRIDE_VAR"] == "override_value"

    def test_get_agent_config_handles_quoted_values(self, client):
        """Test that quoted values in .env files are handled correctly."""
        compose_data = {"services": {"test-agent": {"env_file": ".env"}}}

        env_file_content = """
SINGLE_QUOTED='value in single quotes'
DOUBLE_QUOTED="value in double quotes"
NO_QUOTES=value without quotes
EMPTY_QUOTES=""
MIXED_QUOTES="it's a mixed value"
"""

        def mock_multi_open(path, *args, **kwargs):
            path_str = str(path)
            if path_str.endswith("docker-compose.yml"):
                return mock_open(read_data=yaml.dump(compose_data))()
            elif path_str.endswith(".env"):
                return mock_open(read_data=env_file_content)()
            return mock_open()()

        with patch("builtins.open", mock_multi_open):
            with patch("pathlib.Path.exists", return_value=True):
                response = client.get("/manager/v1/agents/test-agent/config")

        assert response.status_code == 200
        data = response.json()

        # Check quotes are properly stripped
        assert data["environment"]["SINGLE_QUOTED"] == "value in single quotes"
        assert data["environment"]["DOUBLE_QUOTED"] == "value in double quotes"
        assert data["environment"]["NO_QUOTES"] == "value without quotes"
        assert data["environment"]["EMPTY_QUOTES"] == ""
        assert data["environment"]["MIXED_QUOTES"] == "it's a mixed value"

    def test_update_agent_config_with_discord_toggle(self, client):
        """Test updating agent config to toggle Discord adapter."""
        compose_data = {
            "services": {
                "test-agent": {
                    "environment": {"CIRIS_ADAPTER": "api", "EXISTING_VAR": "existing_value"}
                }
            }
        }

        # Test enabling Discord
        config_update = {
            "environment": {
                "CIRIS_ENABLE_DISCORD": "true",
                "DISCORD_BOT_TOKEN": "new-token",
                "DISCORD_CHANNEL_IDS": "111,222,333",
            }
        }

        # Mock file operations
        with patch("builtins.open", mock_open(read_data=yaml.dump(compose_data))):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("subprocess.run") as mock_run:
                    with patch("yaml.dump") as mock_yaml_dump:
                        mock_run.return_value = Mock(returncode=0)

                        response = client.patch(
                            "/manager/v1/agents/test-agent/config", json=config_update
                        )

        assert response.status_code == 200
        assert response.json()["status"] == "updated"

        # Verify the YAML dump was called
        assert mock_yaml_dump.called

    def test_update_agent_config_preserves_adapter_list(self, client):
        """Test that updating config preserves existing adapters in the list."""
        compose_data = {
            "services": {
                "test-agent": {
                    "environment": {"CIRIS_ADAPTER": "api,webhook", "EXISTING_VAR": "value"}
                }
            }
        }

        # Test enabling Discord while preserving existing adapters
        config_update = {"environment": {"CIRIS_ENABLE_DISCORD": "true"}}

        captured_yaml = {}

        def capture_yaml_dump(data, file, **kwargs):
            captured_yaml["data"] = data

        with patch("builtins.open", mock_open(read_data=yaml.dump(compose_data))):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("subprocess.run") as mock_run:
                    with patch("yaml.dump", side_effect=capture_yaml_dump):
                        mock_run.return_value = Mock(returncode=0)

                        response = client.patch(
                            "/manager/v1/agents/test-agent/config", json=config_update
                        )

        assert response.status_code == 200

        # Check that the adapter list includes discord and preserves existing
        updated_adapters = captured_yaml["data"]["services"]["test-agent"]["environment"][
            "CIRIS_ADAPTER"
        ]
        assert "api" in updated_adapters
        assert "webhook" in updated_adapters
        assert "discord" in updated_adapters

    def test_parse_env_file_javascript_logic(self):
        """Test the JavaScript parseEnvFile logic (simulated in Python)."""

        def parse_env_file(content):
            """Python simulation of JavaScript parseEnvFile function."""
            env = {}
            lines = content.strip().split("\n")

            for line in lines:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith("#"):
                    continue

                # Parse key=value pairs
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

            return env

        # Test various .env file formats
        test_content = """
# Comment line
KEY1=value1
KEY2 = value with spaces
QUOTED="quoted value"
SINGLE_QUOTED='single quoted'
EMPTY=
KEY_WITH_EQUALS=key=value
# Another comment
LAST_KEY=last_value
"""

        result = parse_env_file(test_content)

        assert result["KEY1"] == "value1"
        assert result["KEY2"] == "value with spaces"
        assert result["QUOTED"] == "quoted value"
        assert result["SINGLE_QUOTED"] == "single quoted"
        assert result["EMPTY"] == ""
        assert result["KEY_WITH_EQUALS"] == "key=value"
        assert result["LAST_KEY"] == "last_value"
        assert "# Comment line" not in str(result)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
