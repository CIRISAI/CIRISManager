"""Tests for multi-occurrence agent authentication.

Tests that the authentication system correctly handles agents with occurrence_id,
ensuring token lookup and format detection work properly.
"""

import pytest
from unittest.mock import Mock, patch
from ciris_manager.agent_auth import AgentAuth
from ciris_manager.agent_registry import AgentRegistry, RegisteredAgent


@pytest.fixture
def mock_registry():
    """Create a mock agent registry with multi-occurrence agents."""
    registry = Mock(spec=AgentRegistry)

    # Scout agent on main server (no occurrence_id)
    scout_main = RegisteredAgent(
        agent_id="scout-remote-test-dahrb9",
        name="scout-remote-test",
        port=8000,
        template="scout",
        compose_file="/opt/ciris/agents/scout-remote-test-dahrb9/docker-compose.yml",
        server_id="scout",
        occurrence_id=None,
        service_token="encrypted_token_scout_main",
    )

    # Scout agent on scout2 server (occurrence_id=002)
    scout2 = RegisteredAgent(
        agent_id="scout-remote-test-dahrb9",
        name="scout-remote-test",
        port=8002,
        template="scout",
        compose_file="/opt/ciris/agents/scout-remote-test-dahrb9/docker-compose-002.yml",
        server_id="scout2",
        occurrence_id="002",
        service_token="encrypted_token_scout2",
    )

    def get_agent_side_effect(agent_id, occurrence_id=None, server_id=None):
        """Mock get_agent with proper composite key lookup."""
        if agent_id == "scout-remote-test-dahrb9":
            if occurrence_id == "002" and server_id == "scout2":
                return scout2
            elif occurrence_id is None and server_id == "scout":
                return scout_main
            elif server_id == "scout2":
                # Fallback: if only server_id is provided, return that server's agent
                return scout2
            elif server_id == "scout":
                return scout_main
        return None

    registry.get_agent.side_effect = get_agent_side_effect
    return registry


@pytest.fixture
def mock_docker_client_manager():
    """Create a mock Docker client manager."""
    manager = Mock()

    def get_server_config_side_effect(server_id):
        """Return server configs."""
        server_config = Mock()
        if server_id == "scout2":
            server_config.vpc_ip = "10.2.96.8"
            server_config.hostname = "scoutapilb.ciris.ai"
        else:
            server_config.vpc_ip = None
            server_config.hostname = "localhost"
        return server_config

    manager.get_server_config.side_effect = get_server_config_side_effect
    return manager


@pytest.fixture
def mock_encryption():
    """Mock encryption for decrypting tokens."""
    with patch("ciris_manager.crypto.get_token_encryption") as mock_get_encryption:
        encryption = Mock()
        encryption.decrypt_token.side_effect = lambda token: f"decrypted_{token}"
        mock_get_encryption.return_value = encryption
        yield encryption


class TestMultiOccurrenceAuth:
    """Test multi-occurrence agent authentication."""

    def test_get_service_token_with_occurrence_id(
        self, mock_registry, mock_docker_client_manager, mock_encryption
    ):
        """Test that service token lookup includes occurrence_id."""
        auth = AgentAuth(
            agent_registry=mock_registry, docker_client_manager=mock_docker_client_manager
        )

        # Get token with occurrence_id
        token = auth._get_service_token(
            agent_id="scout-remote-test-dahrb9", occurrence_id="002", server_id="scout2"
        )

        # Verify registry was called with occurrence_id
        mock_registry.get_agent.assert_called_with(
            "scout-remote-test-dahrb9", occurrence_id="002", server_id="scout2"
        )

        # Verify correct token was returned (decrypted)
        assert token == "decrypted_encrypted_token_scout2"

    def test_get_service_token_without_occurrence_id(
        self, mock_registry, mock_docker_client_manager, mock_encryption
    ):
        """Test that service token lookup works without occurrence_id."""
        auth = AgentAuth(
            agent_registry=mock_registry, docker_client_manager=mock_docker_client_manager
        )

        # Get token without occurrence_id
        token = auth._get_service_token(
            agent_id="scout-remote-test-dahrb9", occurrence_id=None, server_id="scout"
        )

        # Verify registry was called without occurrence_id
        mock_registry.get_agent.assert_called_with(
            "scout-remote-test-dahrb9", occurrence_id=None, server_id="scout"
        )

        # Verify correct token was returned
        assert token == "decrypted_encrypted_token_scout_main"

    def test_get_auth_headers_with_occurrence_id(
        self, mock_registry, mock_docker_client_manager, mock_encryption
    ):
        """Test that auth headers are generated correctly with occurrence_id."""
        auth = AgentAuth(
            agent_registry=mock_registry, docker_client_manager=mock_docker_client_manager
        )

        # Get auth headers with occurrence_id
        headers = auth.get_auth_headers(
            agent_id="scout-remote-test-dahrb9", occurrence_id="002", server_id="scout2"
        )

        # Verify headers contain the correct token
        assert "Authorization" in headers
        assert "decrypted_encrypted_token_scout2" in headers["Authorization"]

    def test_get_auth_headers_without_occurrence_id(
        self, mock_registry, mock_docker_client_manager, mock_encryption
    ):
        """Test that auth headers work without occurrence_id."""
        auth = AgentAuth(
            agent_registry=mock_registry, docker_client_manager=mock_docker_client_manager
        )

        # Get auth headers without occurrence_id
        headers = auth.get_auth_headers(
            agent_id="scout-remote-test-dahrb9", occurrence_id=None, server_id="scout"
        )

        # Verify headers contain the correct token
        assert "Authorization" in headers
        assert "decrypted_encrypted_token_scout_main" in headers["Authorization"]

    def test_get_auth_headers_different_occurrences(
        self, mock_registry, mock_docker_client_manager, mock_encryption
    ):
        """Test that different occurrences get different tokens."""
        auth = AgentAuth(
            agent_registry=mock_registry, docker_client_manager=mock_docker_client_manager
        )

        # Get headers for main server instance
        headers_main = auth.get_auth_headers(
            agent_id="scout-remote-test-dahrb9", occurrence_id=None, server_id="scout"
        )

        # Get headers for scout2 instance with occurrence_id
        headers_scout2 = auth.get_auth_headers(
            agent_id="scout-remote-test-dahrb9", occurrence_id="002", server_id="scout2"
        )

        # Verify they got different tokens
        assert headers_main["Authorization"] != headers_scout2["Authorization"]
        assert "decrypted_encrypted_token_scout_main" in headers_main["Authorization"]
        assert "decrypted_encrypted_token_scout2" in headers_scout2["Authorization"]

    def test_detect_auth_format_with_occurrence_id(
        self, mock_registry, mock_docker_client_manager, mock_encryption
    ):
        """Test that auth format detection works with occurrence_id."""

        # Mock successful HTTP response
        mock_response = Mock()
        mock_response.status_code = 200

        mock_client_instance = Mock()
        mock_client_instance.get.return_value = mock_response
        mock_client_instance.__enter__ = Mock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = Mock(return_value=False)

        auth = AgentAuth(
            agent_registry=mock_registry, docker_client_manager=mock_docker_client_manager
        )

        # Detect auth format with occurrence_id
        with patch("httpx.Client") as mock_httpx_client:
            mock_httpx_client.return_value = mock_client_instance

            auth_format = auth.detect_auth_format(
                agent_id="scout-remote-test-dahrb9", occurrence_id="002", server_id="scout2"
            )

            # Verify registry was called with occurrence_id
            assert mock_registry.get_agent.call_count >= 1
            # Check that at least one call included the occurrence_id
            calls = mock_registry.get_agent.call_args_list
            assert any(
                call.kwargs.get("occurrence_id") == "002"
                and call.kwargs.get("server_id") == "scout2"
                for call in calls
            )

            # Verify format was detected
            assert auth_format in ["service", "raw"]

    def test_missing_token_with_occurrence_id_raises_error(
        self, mock_docker_client_manager, mock_encryption
    ):
        """Test that missing token with occurrence_id raises appropriate error."""
        # Create registry that returns None for this lookup
        registry = Mock(spec=AgentRegistry)
        registry.get_agent.return_value = None

        auth = AgentAuth(agent_registry=registry, docker_client_manager=mock_docker_client_manager)

        # Should raise ValueError when token is not found
        with pytest.raises(ValueError, match="No service token found"):
            auth.get_auth_headers(
                agent_id="nonexistent-agent", occurrence_id="002", server_id="scout2"
            )


class TestMultiOccurrenceTokenIsolation:
    """Test that multi-occurrence agents maintain token isolation."""

    def test_occurrence_tokens_are_isolated(
        self, mock_registry, mock_docker_client_manager, mock_encryption
    ):
        """Ensure that tokens for different occurrences are properly isolated."""
        auth = AgentAuth(
            agent_registry=mock_registry, docker_client_manager=mock_docker_client_manager
        )

        # Get token for occurrence 002
        token_002 = auth._get_service_token(
            agent_id="scout-remote-test-dahrb9", occurrence_id="002", server_id="scout2"
        )

        # Get token for no occurrence (main)
        token_main = auth._get_service_token(
            agent_id="scout-remote-test-dahrb9", occurrence_id=None, server_id="scout"
        )

        # Verify they are different
        assert token_002 != token_main
        assert token_002 == "decrypted_encrypted_token_scout2"
        assert token_main == "decrypted_encrypted_token_scout_main"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
