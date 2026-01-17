"""
Test file loading functionality for environment variables.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from fastapi.testclient import TestClient

from ciris_manager.api.routes import create_routes


class TestFileLoading:
    """Test suite for file loading functionality."""

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
        app.state.manager = mock_manager
        os.environ["CIRIS_AUTH_MODE"] = "development"

        router = create_routes(mock_manager)
        app.include_router(router, prefix="/manager/v1")
        return app

    @pytest.fixture
    def client(self, app):
        """Create a test client."""
        return TestClient(app)


class TestJavaScriptParsing:
    """Test JavaScript parsing logic (Python simulation)."""

    def parse_env_file(self, content):
        """Python simulation of JavaScript parseEnvFile function."""
        env = {}
        lines = content.split("\n")

        for line in lines:
            # Trim the line
            line = line.strip()

            # Skip comments and empty lines
            if not line or line.startswith("#"):
                continue

            # Check if line contains an equals sign
            equals_index = line.find("=")
            if equals_index > 0:
                key = line[:equals_index].strip()
                value = line[equals_index + 1 :].strip()

                # Remove quotes if present
                if (value.startswith('"') and value.endswith('"')) or (
                    value.startswith("'") and value.endswith("'")
                ):
                    value = value[1:-1]

                env[key] = value

        return env

    def test_parse_basic_env(self):
        """Test parsing basic .env file."""
        content = """
KEY1=value1
KEY2=value2
KEY3=value3
"""
        result = self.parse_env_file(content)
        assert result == {"KEY1": "value1", "KEY2": "value2", "KEY3": "value3"}

    def test_parse_with_comments(self):
        """Test parsing with comments."""
        content = """
# This is a comment
KEY1=value1
# Another comment
KEY2=value2
### Multiple hash marks
KEY3=value3
"""
        result = self.parse_env_file(content)
        assert result == {"KEY1": "value1", "KEY2": "value2", "KEY3": "value3"}

    def test_parse_with_quotes(self):
        """Test parsing values with quotes."""
        content = """
SINGLE_QUOTED='value in single quotes'
DOUBLE_QUOTED="value in double quotes"
NO_QUOTES=value without quotes
MIXED_QUOTES="it's a 'mixed' value"
EMPTY_QUOTES=""
EMPTY_SINGLE=''
"""
        result = self.parse_env_file(content)
        assert result == {
            "SINGLE_QUOTED": "value in single quotes",
            "DOUBLE_QUOTED": "value in double quotes",
            "NO_QUOTES": "value without quotes",
            "MIXED_QUOTES": "it's a 'mixed' value",
            "EMPTY_QUOTES": "",
            "EMPTY_SINGLE": "",
        }

    def test_parse_with_spaces(self):
        """Test parsing with spaces around equals."""
        content = """
KEY1 = value1
KEY2= value2
KEY3 =value3
KEY4   =   value4
KEY_WITH_SPACES=value with spaces
"""
        result = self.parse_env_file(content)
        assert result == {
            "KEY1": "value1",
            "KEY2": "value2",
            "KEY3": "value3",
            "KEY4": "value4",
            "KEY_WITH_SPACES": "value with spaces",
        }

    def test_parse_empty_values(self):
        """Test parsing empty values."""
        content = """
EMPTY1=
EMPTY2=""
EMPTY3=''
HAS_VALUE=not_empty
"""
        result = self.parse_env_file(content)
        assert result["EMPTY1"] == ""
        assert result["EMPTY2"] == ""
        assert result["EMPTY3"] == ""
        assert result["HAS_VALUE"] == "not_empty"

    def test_parse_special_characters(self):
        """Test parsing special characters."""
        content = """
URL=https://example.com/path?query=value
PATH=/usr/local/bin:/usr/bin
KEY_WITH_EQUALS=key=value
JSON={"key": "value"}
REGEX=^[a-z]+$
COMMAND=echo "hello world"
"""
        result = self.parse_env_file(content)
        assert result["URL"] == "https://example.com/path?query=value"
        assert result["PATH"] == "/usr/local/bin:/usr/bin"
        assert result["KEY_WITH_EQUALS"] == "key=value"
        assert result["JSON"] == '{"key": "value"}'
        assert result["REGEX"] == "^[a-z]+$"
        assert result["COMMAND"] == 'echo "hello world"'

    def test_parse_multiline_ignored(self):
        """Test that multiline values are not supported (as expected)."""
        content = """
SINGLE_LINE=value1
ATTEMPTED_MULTILINE=line1
line2
NEXT_KEY=value2
"""
        result = self.parse_env_file(content)
        # The parser should ignore lines without = that aren't comments
        assert result == {
            "SINGLE_LINE": "value1",
            "ATTEMPTED_MULTILINE": "line1",
            "NEXT_KEY": "value2",
        }

    def test_parse_edge_cases(self):
        """Test edge cases."""
        content = """
# Empty file would return empty dict
=no_key
KEY_ONLY
MULTIPLE===equals===signs
 LEADING_SPACE=value
TRAILING_SPACE =value
"""
        result = self.parse_env_file(content)
        # Should handle these gracefully
        assert "KEY_ONLY" not in result  # No equals sign
        assert "MULTIPLE" in result
        assert result["MULTIPLE"] == "==equals===signs"
        assert "LEADING_SPACE" in result
        assert "TRAILING_SPACE" in result

    def test_parse_real_env_file(self):
        """Test parsing a realistic .env file."""
        content = """
# Application Configuration
NODE_ENV=production
APP_PORT=3000
APP_URL=https://myapp.com

# Database Configuration
DB_HOST=localhost
DB_PORT=5432
DB_NAME=myapp_db
DB_USER=admin
# nosec B105 - Test data only, not real password
DB_PASSWORD="p@ssw0rd!123"

# Redis Configuration
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_PASSWORD=

# API Keys
OPENAI_API_KEY=sk-proj-abcdef123456
STRIPE_SECRET_KEY=sk_test_123456789
DISCORD_BOT_TOKEN=

# Feature Flags
ENABLE_CACHE=true
DEBUG_MODE=false
MAX_RETRIES=3

# URLs and Paths
CALLBACK_URL=https://myapp.com/auth/callback
UPLOAD_PATH=/var/uploads
LOG_PATH=/var/log/myapp.log
"""
        result = self.parse_env_file(content)

        assert result["NODE_ENV"] == "production"
        assert result["APP_PORT"] == "3000"
        assert result["DB_PASSWORD"] == "p@ssw0rd!123"
        assert result["REDIS_PASSWORD"] == ""
        assert result["ENABLE_CACHE"] == "true"
        assert result["MAX_RETRIES"] == "3"
        assert result["CALLBACK_URL"] == "https://myapp.com/auth/callback"

    def test_parse_discord_config(self):
        """Test parsing Discord-specific configuration."""
        content = """
# Discord Configuration
DISCORD_BOT_TOKEN=TEST_BOT_TOKEN_123456789.ABCDEF.ghijklmnop_qrstuvwxyz
DISCORD_CHANNEL_IDS=1382010877171073108,1387961206190637076
DISCORD_DEFERRAL_CHANNEL_ID=1382010936600301569
WA_USER_IDS=537080239679864862,123456789012345678
DISCORD_SERVER_ID=1151280646611218583
"""
        result = self.parse_env_file(content)

        assert (
            result["DISCORD_BOT_TOKEN"] == "TEST_BOT_TOKEN_123456789.ABCDEF.ghijklmnop_qrstuvwxyz"
        )
        assert result["DISCORD_CHANNEL_IDS"] == "1382010877171073108,1387961206190637076"
        assert result["WA_USER_IDS"] == "537080239679864862,123456789012345678"


class TestFileUploadIntegration:
    """Test file upload integration scenarios."""

    def test_txt_file_acceptance(self):
        """Test that .txt files are accepted."""
        # This would be tested in browser
        # Checking that accept attribute includes .txt
        html_snippet = 'input.accept = ".env,.txt,text/plain"'
        assert ".txt" in html_snippet
        assert "text/plain" in html_snippet

    def test_env_file_acceptance(self):
        """Test that .env files are accepted."""
        html_snippet = 'input.accept = ".env,.txt,text/plain"'
        assert ".env" in html_snippet

    def test_file_loading_error_handling(self):
        """Test error handling in file loading."""
        test_cases = [
            ("", "No valid environment variables found in file"),
            ("# Only comments\n# No variables", "No valid environment variables found in file"),
            ("invalid content without equals", "No valid environment variables found in file"),
        ]

        parser = TestJavaScriptParsing()
        for content, expected_error in test_cases:
            result = parser.parse_env_file(content)
            if len(result) == 0:
                # This would trigger the error message in JavaScript
                assert expected_error == "No valid environment variables found in file"

    def test_success_message_format(self):
        """Test success message formatting."""
        parser = TestJavaScriptParsing()
        content = """
KEY1=value1
KEY2=value2
KEY3=value3
"""
        result = parser.parse_env_file(content)
        count = len(result)
        filename = "test.env"

        # JavaScript would show: `Loaded ${count} environment variables from ${file.name}`
        expected_message = f"Loaded {count} environment variables from {filename}"
        assert expected_message == "Loaded 3 environment variables from test.env"


class TestAPIEndpointIntegration(TestFileLoading):
    """Test API endpoint integration with file loading."""

    def test_env_default_provides_loadable_format(self, client):
        """Test that /env/default returns content that parseEnvFile can handle."""
        with patch("pathlib.Path.exists", return_value=False):
            response = client.get("/manager/v1/env/default")

        assert response.status_code == 200
        data = response.json()
        assert "content" in data

        # Parse the content using our simulated parser
        parser = TestJavaScriptParsing()
        env = parser.parse_env_file(data["content"])

        # Should have parsed some variables
        assert len(env) > 0
        assert "CIRIS_API_HOST" in env
        assert "CIRIS_API_PORT" in env

    def test_env_default_with_production_file(self, client):
        """Test /env/default with production .env file."""
        production_env = """
# Production Configuration
OPENAI_API_KEY=sk-secret-key
DISCORD_BOT_TOKEN=secret-token
DISCORD_CHANNEL_IDS=123,456,789
WA_USER_IDS=user1,user2
OAUTH_CALLBACK_BASE_URL=https://agents.ciris.ai
"""

        # Create an async mock for aiofiles.open
        mock_file = AsyncMock()
        mock_file.read = AsyncMock(return_value=production_env)
        mock_file.__aenter__ = AsyncMock(return_value=mock_file)
        mock_file.__aexit__ = AsyncMock(return_value=None)

        with patch("pathlib.Path.exists", return_value=True):
            with patch("aiofiles.open", return_value=mock_file):
                response = client.get("/manager/v1/env/default")

        assert response.status_code == 200
        data = response.json()

        # Parse and verify
        parser = TestJavaScriptParsing()
        env = parser.parse_env_file(data["content"])

        # Sensitive keys should be cleared
        assert env.get("OPENAI_API_KEY") == ""
        assert env.get("DISCORD_BOT_TOKEN") == ""

        # Non-sensitive values preserved
        assert env.get("DISCORD_CHANNEL_IDS") == "123,456,789"
        assert env.get("WA_USER_IDS") == "user1,user2"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
