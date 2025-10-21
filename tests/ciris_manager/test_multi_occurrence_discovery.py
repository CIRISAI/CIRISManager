"""Tests for multi-occurrence agent discovery.

Tests that the discovery system correctly handles agents with occurrence_id,
especially when they're deployed across multiple servers.
"""

import pytest
from unittest.mock import Mock, patch
from ciris_manager.docker_discovery import DockerAgentDiscovery
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
            elif server_id == "scout2" and occurrence_id is None:
                # This should match scout2 even without occurrence_id
                return scout2
            elif server_id == "scout":
                return scout_main
        return None

    registry.get_agent.side_effect = get_agent_side_effect

    def update_agent_state_side_effect(
        agent_id, version, cognitive_state, occurrence_id=None, server_id=None
    ):
        """Mock update_agent_state."""
        pass

    registry.update_agent_state.side_effect = update_agent_state_side_effect

    return registry


@pytest.fixture
def mock_docker_client_manager():
    """Create a mock Docker client manager for multi-server support."""
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


def create_mock_container(
    name, agent_id, occurrence_id=None, server_id="main", port=8000, status="running"
):
    """Helper to create a mock Docker container."""
    container = Mock()
    container.name = name
    container.status = status

    # Build environment variables
    env_vars = [
        f"CIRIS_AGENT_ID={agent_id}",
        f"CIRIS_AGENT_NAME={agent_id.replace('-', ' ').title()}",
        "CIRIS_ADAPTER=api",
        "CIRIS_API_HOST=0.0.0.0",
        f"CIRIS_API_PORT={port}",
        "CIRIS_MOCK_LLM=true",
    ]

    if occurrence_id:
        env_vars.append(f"AGENT_OCCURRENCE_ID={occurrence_id}")

    container.attrs = {"Config": {"Env": env_vars, "Image": "ghcr.io/cirisai/ciris-agent:1.4.5"}}

    return container


class TestMultiOccurrenceDiscovery:
    """Test multi-occurrence agent discovery."""

    def test_extract_occurrence_id_from_container(self, mock_registry, mock_docker_client_manager):
        """Test that occurrence_id is correctly extracted from container environment."""
        discovery = DockerAgentDiscovery(
            agent_registry=mock_registry, docker_client_manager=mock_docker_client_manager
        )

        # Create container with occurrence_id
        container = create_mock_container(
            name="ciris-scout-remote-test-dahrb9-002",
            agent_id="scout-remote-test-dahrb9",
            occurrence_id="002",
            server_id="scout2",
            port=8002,
        )

        # Build env_dict manually (simulating what _extract_agent_info does)
        env_vars = container.attrs["Config"]["Env"]
        env_dict = {}
        for env in env_vars:
            if "=" in env:
                key, value = env.split("=", 1)
                env_dict[key] = value

        # Verify occurrence_id is in env_dict
        assert env_dict.get("AGENT_OCCURRENCE_ID") == "002"

        # Extract agent info
        agent_info = discovery._extract_agent_info(container, env_dict, server_id="scout2")

        # Verify extraction succeeded
        assert agent_info is not None
        assert agent_info.agent_id == "scout-remote-test-dahrb9"
        assert agent_info.api_port == 8002
        assert agent_info.server_id == "scout2"

    def test_registry_lookup_with_occurrence_id(self, mock_registry, mock_docker_client_manager):
        """Test that registry lookup includes occurrence_id when present."""
        discovery = DockerAgentDiscovery(
            agent_registry=mock_registry, docker_client_manager=mock_docker_client_manager
        )

        # Create container with occurrence_id
        container = create_mock_container(
            name="ciris-scout-remote-test-dahrb9-002",
            agent_id="scout-remote-test-dahrb9",
            occurrence_id="002",
            server_id="scout2",
            port=8002,
        )

        env_vars = container.attrs["Config"]["Env"]
        env_dict = {}
        for env in env_vars:
            if "=" in env:
                key, value = env.split("=", 1)
                env_dict[key] = value

        # Extract agent info - this should call get_agent with occurrence_id
        agent_info = discovery._extract_agent_info(container, env_dict, server_id="scout2")

        # Verify registry was called with occurrence_id
        mock_registry.get_agent.assert_called_with(
            "scout-remote-test-dahrb9", occurrence_id="002", server_id="scout2"
        )

        # Verify correct port was retrieved from registry
        assert agent_info.api_port == 8002

    def test_registry_lookup_without_occurrence_id(self, mock_registry, mock_docker_client_manager):
        """Test that registry lookup works for agents without occurrence_id."""
        discovery = DockerAgentDiscovery(
            agent_registry=mock_registry, docker_client_manager=mock_docker_client_manager
        )

        # Create container WITHOUT occurrence_id
        container = create_mock_container(
            name="ciris-scout-remote-test-dahrb9",
            agent_id="scout-remote-test-dahrb9",
            occurrence_id=None,
            server_id="scout",
            port=8000,
        )

        env_vars = container.attrs["Config"]["Env"]
        env_dict = {}
        for env in env_vars:
            if "=" in env:
                key, value = env.split("=", 1)
                env_dict[key] = value

        # Extract agent info
        agent_info = discovery._extract_agent_info(container, env_dict, server_id="scout")

        # Verify registry was called without occurrence_id
        mock_registry.get_agent.assert_called_with(
            "scout-remote-test-dahrb9", occurrence_id=None, server_id="scout"
        )

        # Verify correct port was retrieved
        assert agent_info.api_port == 8000

    def test_version_query_passes_occurrence_id(self, mock_registry, mock_docker_client_manager):
        """Test that occurrence_id is passed through to version query and auth."""
        from ciris_manager.agent_auth import AgentAuth

        # Mock successful HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "version": "1.4.5",
            "codename": "Stable Foundation",
            "code_hash": "abc123",
            "cognitive_state": "WORK",
        }

        mock_client_instance = Mock()
        mock_client_instance.get.return_value = mock_response
        mock_client_instance.__enter__ = Mock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = Mock(return_value=False)

        # Create discovery with mock auth
        discovery = DockerAgentDiscovery(
            agent_registry=mock_registry, docker_client_manager=mock_docker_client_manager
        )

        # Mock the auth system and httpx
        with patch("ciris_manager.agent_auth.get_agent_auth") as mock_get_auth:
            with patch("httpx.Client") as mock_httpx_client:
                mock_httpx_client.return_value = mock_client_instance

                mock_auth = Mock(spec=AgentAuth)
                mock_auth.get_auth_headers.return_value = {"Authorization": "Bearer test_token"}
                mock_auth._should_skip_auth_attempt.return_value = False
                mock_get_auth.return_value = mock_auth

                # Query version with occurrence_id
                version_info = discovery._query_agent_version(
                    agent_id="scout-remote-test-dahrb9",
                    port=8002,
                    occurrence_id="002",
                    server_id="scout2",
                )

                # Verify auth was called with occurrence_id
                mock_auth.get_auth_headers.assert_called_with(
                    "scout-remote-test-dahrb9", occurrence_id="002", server_id="scout2"
                )

                # Verify version info was returned
                assert version_info is not None
                assert version_info["version"] == "1.4.5"
                assert version_info["cognitive_state"] == "WORK"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
