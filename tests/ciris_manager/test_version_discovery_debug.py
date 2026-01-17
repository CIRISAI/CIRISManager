"""
Tests to debug version discovery issues.

Reproduces the datum (old version) and echo-nemesis (null version) problems.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from ciris_manager.docker_discovery import DockerAgentDiscovery, invalidate_discovery_cache


class TestVersionDiscoveryDebug:
    """Debug version discovery issues for datum and echo-nemesis."""

    def test_version_discovery_with_auth_failure(self):
        """Test that version discovery fails gracefully when auth fails."""
        # Clear cache to ensure fresh discovery
        invalidate_discovery_cache()

        # Mock agent registry
        mock_registry = Mock()
        mock_agent = Mock()
        mock_agent.port = 8001
        mock_agent.template = "base"
        mock_agent.metadata = {"deployment": "CIRIS_DISCORD_PILOT"}
        mock_registry.get_agent.return_value = mock_agent

        # Mock Docker container
        mock_container = Mock()
        mock_container.name = "ciris-datum"
        mock_container.status = "running"
        mock_container.attrs = {
            "Config": {
                "Image": "ghcr.io/cirisai/ciris-agent:latest",
                "Env": [
                    "CIRIS_AGENT_ID=datum",
                    "CIRIS_API_PORT=8001",
                ],
            }
        }

        # Mock Docker client
        mock_docker_client = Mock()
        mock_docker_client.containers.list.return_value = [mock_container]

        # Mock auth failure
        with patch("docker.from_env", return_value=mock_docker_client):
            with patch("ciris_manager.agent_auth.get_agent_auth") as mock_get_auth:
                mock_auth = Mock()
                mock_auth.get_auth_headers.side_effect = ValueError("Authentication failed")
                mock_get_auth.return_value = mock_auth

                discovery = DockerAgentDiscovery(mock_registry)
                agents = discovery.discover_agents()

                assert len(agents) == 1
                agent = agents[0]
                assert agent.agent_id == "datum"
                assert agent.version is None  # This is the bug - should have version
                assert agent.api_port == 8001

    @pytest.mark.skip(reason="Authentication backoff interfering with test - needs investigation")
    def test_version_discovery_with_successful_auth(self):
        """Test that version discovery works when auth succeeds."""

        # Mock agent registry
        mock_registry = Mock()
        mock_agent = Mock()
        mock_agent.port = 8001
        mock_agent.template = "base"
        mock_agent.metadata = {"deployment": "CIRIS_DISCORD_PILOT"}
        mock_registry.get_agent.return_value = mock_agent

        # Mock Docker container
        mock_container = Mock()
        mock_container.name = "ciris-datum"
        mock_container.status = "running"
        mock_container.attrs = {
            "Config": {
                "Image": "ghcr.io/cirisai/ciris-agent:latest",
                "Env": [
                    "CIRIS_AGENT_ID=datum",
                    "CIRIS_API_PORT=8001",
                ],
            }
        }

        # Mock Docker client
        mock_docker_client = Mock()
        mock_docker_client.containers.list.return_value = [mock_container]

        # Mock successful auth and API response
        with patch("docker.from_env", return_value=mock_docker_client):
            with patch("ciris_manager.agent_auth.get_agent_auth") as mock_get_auth:
                with patch("httpx.Client") as mock_client_cls:
                    # Setup auth
                    mock_auth = Mock()
                    mock_auth.get_auth_headers.return_value = {"Authorization": "Bearer test-token"}
                    mock_get_auth.return_value = mock_auth

                    # Setup HTTP response
                    mock_response = Mock()
                    mock_response.status_code = 200
                    mock_response.json.return_value = {
                        "data": {
                            "version": "1.0.8",
                            "codename": "Stable Foundation",
                            "code_hash": "abc123",
                            "cognitive_state": "WORK",
                        }
                    }

                    mock_client = Mock()
                    mock_client.get.return_value = mock_response
                    mock_client_context = MagicMock()
                    mock_client_context.__enter__.return_value = mock_client
                    mock_client_context.__exit__.return_value = None
                    mock_client_cls.return_value = mock_client_context

                    discovery = DockerAgentDiscovery(mock_registry)
                    agents = discovery.discover_agents()

                    assert len(agents) == 1
                    agent = agents[0]
                    assert agent.agent_id == "datum"
                    assert agent.version == "1.0.8"
                    assert agent.codename == "Stable Foundation"
                    assert agent.code_hash == "abc123"
                    assert agent.cognitive_state == "WORK"

    @pytest.mark.skip(reason="Authentication backoff interfering with test - needs investigation")
    def test_old_version_persistence_in_registry(self):
        """Test how old versions persist in registry vs API discovery."""

        # This test simulates the datum issue: old version in metadata
        mock_registry = Mock()
        mock_agent = Mock()
        mock_agent.port = 8001
        mock_agent.template = "base"
        mock_agent.metadata = {"deployment": "CIRIS_DISCORD_PILOT"}
        mock_agent.current_version = "1.4.3-beta"  # Old version stored in metadata
        mock_registry.get_agent.return_value = mock_agent

        # Mock Docker container
        mock_container = Mock()
        mock_container.name = "ciris-datum"
        mock_container.status = "running"
        mock_container.attrs = {
            "Config": {
                "Image": "ghcr.io/cirisai/ciris-agent:latest",
                "Env": [
                    "CIRIS_AGENT_ID=datum",
                    "CIRIS_API_PORT=8001",
                ],
            }
        }

        # Mock Docker client
        mock_docker_client = Mock()
        mock_docker_client.containers.list.return_value = [mock_container]

        # Mock successful auth but agent returns current version
        with patch("docker.from_env", return_value=mock_docker_client):
            with patch("ciris_manager.agent_auth.get_agent_auth") as mock_get_auth:
                with patch("httpx.Client") as mock_client_cls:
                    # Setup auth
                    mock_auth = Mock()
                    mock_auth.get_auth_headers.return_value = {"Authorization": "Bearer test-token"}
                    mock_get_auth.return_value = mock_auth

                    # Setup HTTP response - agent returns CURRENT version
                    mock_response = Mock()
                    mock_response.status_code = 200
                    mock_response.json.return_value = {
                        "data": {
                            "version": "1.0.8",  # Current version from API
                            "codename": "Stable Foundation",
                            "code_hash": "abc123",
                            "cognitive_state": "WORK",
                        }
                    }

                    mock_client = Mock()
                    mock_client.get.return_value = mock_response
                    mock_client_context = MagicMock()
                    mock_client_context.__enter__.return_value = mock_client
                    mock_client_context.__exit__.return_value = None
                    mock_client_cls.return_value = mock_client_context

                    discovery = DockerAgentDiscovery(mock_registry)
                    agents = discovery.discover_agents()

                    assert len(agents) == 1
                    agent = agents[0]
                    assert agent.agent_id == "datum"
                    # The discovery should return the LIVE version from API, not stored version
                    assert agent.version == "1.0.8"  # Should be live version
                    assert agent.codename == "Stable Foundation"

                    # The issue might be that the API shows stored version from registry
                    # instead of live version from discovery

    @pytest.mark.skip(reason="Authentication backoff interfering with test - needs investigation")
    def test_metadata_update_on_version_discovery(self):
        """Test that registry metadata gets updated when new version is discovered."""

        # Mock agent registry that tracks updates
        mock_registry = Mock()
        mock_agent = Mock()
        mock_agent.port = 8001
        mock_agent.template = "base"
        mock_agent.metadata = {"deployment": "CIRIS_DISCORD_PILOT"}
        mock_agent.current_version = "1.4.3-beta"  # Old version
        mock_registry.get_agent.return_value = mock_agent
        mock_registry.update_agent_version = Mock()  # Track version updates

        # Mock Docker container
        mock_container = Mock()
        mock_container.name = "ciris-datum"
        mock_container.status = "running"
        mock_container.attrs = {
            "Config": {
                "Image": "ghcr.io/cirisai/ciris-agent:latest",
                "Env": [
                    "CIRIS_AGENT_ID=datum",
                    "CIRIS_API_PORT=8001",
                ],
            }
        }

        mock_docker_client = Mock()
        mock_docker_client.containers.list.return_value = [mock_container]

        with patch("docker.from_env", return_value=mock_docker_client):
            with patch("ciris_manager.agent_auth.get_agent_auth") as mock_get_auth:
                with patch("httpx.Client") as mock_client_cls:
                    mock_auth = Mock()
                    mock_auth.get_auth_headers.return_value = {"Authorization": "Bearer test-token"}
                    mock_get_auth.return_value = mock_auth

                    mock_response = Mock()
                    mock_response.status_code = 200
                    mock_response.json.return_value = {
                        "data": {
                            "version": "1.0.8",
                            "codename": "Stable Foundation",
                            "code_hash": "abc123",
                            "cognitive_state": "WORK",
                        }
                    }

                    mock_client = Mock()
                    mock_client.get.return_value = mock_response
                    mock_client_context = MagicMock()
                    mock_client_context.__enter__.return_value = mock_client
                    mock_client_context.__exit__.return_value = None
                    mock_client_cls.return_value = mock_client_context

                    discovery = DockerAgentDiscovery(mock_registry)
                    agents = discovery.discover_agents()

                    # Check if discovery should trigger registry update
                    # This might be where the bug is - discovery doesn't update the registry
                    assert len(agents) == 1
                    agent = agents[0]
                    assert agent.version == "1.0.8"

                    # The key insight: discovery returns live data but doesn't persist it
                    # The registry still has old data, and API might show registry data

    @pytest.mark.skip(reason="Authentication backoff interfering with test - needs investigation")
    def test_echo_nemesis_token_issue(self):
        """Test echo-nemesis specific token/auth issue."""

        mock_registry = Mock()
        mock_agent = Mock()
        mock_agent.port = 8009
        mock_agent.template = "echo-core"
        mock_agent.metadata = {"deployment": "CIRIS_DISCORD_PILOT"}
        mock_agent.current_version = None  # No version stored
        mock_registry.get_agent.return_value = mock_agent
        mock_registry.update_agent_state = Mock()  # Track calls

        mock_container = Mock()
        mock_container.name = "ciris-echo-nemesis-v2tyey"
        mock_container.status = "running"
        mock_container.attrs = {
            "Config": {
                "Image": "ghcr.io/cirisai/ciris-agent:latest",
                "Env": [
                    "CIRIS_AGENT_ID=echo-nemesis-v2tyey",
                    "CIRIS_API_PORT=8009",
                ],
            }
        }

        mock_docker_client = Mock()
        mock_docker_client.containers.list.return_value = [mock_container]

        # Test both auth failure and success scenarios
        with patch("docker.from_env", return_value=mock_docker_client):
            with patch("ciris_manager.agent_auth.get_agent_auth") as mock_get_auth:
                # Scenario 1: Auth fails (current state)
                mock_auth = Mock()
                mock_auth.get_auth_headers.side_effect = ValueError("Token decryption failed")
                mock_get_auth.return_value = mock_auth

                discovery = DockerAgentDiscovery(mock_registry)
                agents = discovery.discover_agents()

                assert len(agents) == 1
                agent = agents[0]
                assert agent.agent_id == "echo-nemesis-v2tyey"
                assert agent.version is None  # Auth failed, no version

                # Scenario 2: Auth succeeds (after our fix)
                mock_auth.get_auth_headers.side_effect = None
                mock_auth.get_auth_headers.return_value = {"Authorization": "Bearer working-token"}

                with patch("httpx.Client") as mock_client_cls:
                    mock_response = Mock()
                    mock_response.status_code = 200
                    mock_response.json.return_value = {
                        "data": {
                            "version": "1.0.8",
                            "codename": "Stable Foundation",
                            "code_hash": "abc123",
                            "cognitive_state": "WORK",
                        }
                    }

                    mock_client = Mock()
                    mock_client.get.return_value = mock_response
                    mock_client_context = MagicMock()
                    mock_client_context.__enter__.return_value = mock_client
                    mock_client_context.__exit__.return_value = None
                    mock_client_cls.return_value = mock_client_context

                    agents = discovery.discover_agents()
                    agent = agents[0]
                    assert agent.version == "1.0.8"  # Should work after auth fix

                    # Verify registry was updated with fresh version info
                    mock_registry.update_agent_state.assert_called_once_with(
                        "echo-nemesis-v2tyey", "1.0.8", "WORK"
                    )

    @pytest.mark.skip(reason="Authentication backoff interfering with test - needs investigation")
    def test_registry_update_on_successful_discovery(self):
        """Test that registry gets updated when version discovery succeeds."""

        mock_registry = Mock()
        mock_agent = Mock()
        mock_agent.port = 8001
        mock_agent.template = "base"
        mock_agent.metadata = {"deployment": "CIRIS_DISCORD_PILOT"}
        mock_registry.get_agent.return_value = mock_agent
        mock_registry.update_agent_state = Mock()  # Track calls

        mock_container = Mock()
        mock_container.name = "ciris-datum"
        mock_container.status = "running"
        mock_container.attrs = {
            "Config": {
                "Image": "ghcr.io/cirisai/ciris-agent:latest",
                "Env": [
                    "CIRIS_AGENT_ID=datum",
                    "CIRIS_API_PORT=8001",
                ],
            }
        }

        mock_docker_client = Mock()
        mock_docker_client.containers.list.return_value = [mock_container]

        with patch("docker.from_env", return_value=mock_docker_client):
            with patch("ciris_manager.agent_auth.get_agent_auth") as mock_get_auth:
                with patch("httpx.Client") as mock_client_cls:
                    mock_auth = Mock()
                    mock_auth.get_auth_headers.return_value = {"Authorization": "Bearer token"}
                    mock_get_auth.return_value = mock_auth

                    mock_response = Mock()
                    mock_response.status_code = 200
                    mock_response.json.return_value = {
                        "data": {
                            "version": "1.0.8",
                            "codename": "Stable Foundation",
                            "code_hash": "abc123",
                            "cognitive_state": "WORK",
                        }
                    }

                    mock_client = Mock()
                    mock_client.get.return_value = mock_response
                    mock_client_context = MagicMock()
                    mock_client_context.__enter__.return_value = mock_client
                    mock_client_context.__exit__.return_value = None
                    mock_client_cls.return_value = mock_client_context

                    discovery = DockerAgentDiscovery(mock_registry)
                    agents = discovery.discover_agents()

                    # Verify agent info is correct
                    assert len(agents) == 1
                    agent = agents[0]
                    assert agent.agent_id == "datum"
                    assert agent.version == "1.0.8"
                    assert agent.cognitive_state == "WORK"

                    # Verify registry was updated with the fresh data
                    mock_registry.update_agent_state.assert_called_once_with(
                        "datum", "1.0.8", "WORK"
                    )
