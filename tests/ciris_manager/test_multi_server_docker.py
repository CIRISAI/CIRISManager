"""
Unit tests for MultiServerDockerClient.
"""

import pytest
from unittest.mock import Mock, patch
from ciris_manager.config.settings import ServerConfig
from ciris_manager.multi_server_docker import MultiServerDockerClient


class TestMultiServerDockerClient:
    """Test cases for MultiServerDockerClient."""

    @pytest.fixture
    def local_server_config(self):
        """Create local server configuration."""
        return ServerConfig(
            server_id="main",
            hostname="agents.ciris.ai",
            is_local=True,
        )

    @pytest.fixture
    def remote_server_config(self):
        """Create remote server configuration."""
        return ServerConfig(
            server_id="scout",
            hostname="scoutapi.ciris.ai",
            is_local=False,
            vpc_ip="10.2.96.4",
            docker_host="tcp://10.2.96.4:2376",
            tls_ca="/certs/ca.pem",
            tls_cert="/certs/client-cert.pem",
            tls_key="/certs/client-key.pem",
        )

    def test_initialization(self, local_server_config, remote_server_config):
        """Test MultiServerDockerClient initialization."""
        client = MultiServerDockerClient([local_server_config, remote_server_config])

        assert len(client.servers) == 2
        assert "main" in client.servers
        assert "scout" in client.servers
        assert client.servers["main"].hostname == "agents.ciris.ai"
        assert client.servers["scout"].hostname == "scoutapi.ciris.ai"

    def test_initialization_single_server(self, local_server_config):
        """Test initialization with single server."""
        client = MultiServerDockerClient([local_server_config])

        assert len(client.servers) == 1
        assert "main" in client.servers

    def test_list_servers(self, local_server_config, remote_server_config):
        """Test listing configured servers."""
        client = MultiServerDockerClient([local_server_config, remote_server_config])

        servers = client.list_servers()
        assert len(servers) == 2
        assert "main" in servers
        assert "scout" in servers

    def test_get_server_config(self, local_server_config, remote_server_config):
        """Test getting server configuration."""
        client = MultiServerDockerClient([local_server_config, remote_server_config])

        main_config = client.get_server_config("main")
        assert main_config.server_id == "main"
        assert main_config.is_local is True

        scout_config = client.get_server_config("scout")
        assert scout_config.server_id == "scout"
        assert scout_config.is_local is False

    def test_get_server_config_unknown(self, local_server_config):
        """Test getting configuration for unknown server."""
        client = MultiServerDockerClient([local_server_config])

        with pytest.raises(ValueError, match="Unknown server 'unknown'"):
            client.get_server_config("unknown")

    @patch("ciris_manager.multi_server_docker.docker.from_env")
    def test_get_client_local(self, mock_from_env, local_server_config):
        """Test getting Docker client for local server."""
        mock_docker_client = Mock()
        mock_from_env.return_value = mock_docker_client

        client = MultiServerDockerClient([local_server_config])
        docker_client = client.get_client("main")

        assert docker_client == mock_docker_client
        mock_from_env.assert_called_once()

    @patch("ciris_manager.multi_server_docker.DockerClient")
    @patch("ciris_manager.multi_server_docker.TLSConfig")
    def test_get_client_remote(self, mock_tls_config, mock_docker_client, remote_server_config):
        """Test getting Docker client for remote server with TLS."""
        mock_tls = Mock()
        mock_tls_config.return_value = mock_tls
        mock_client = Mock()
        mock_docker_client.return_value = mock_client

        client = MultiServerDockerClient([remote_server_config])
        docker_client = client.get_client("scout")

        assert docker_client == mock_client

        # Verify TLS config was created with correct parameters
        mock_tls_config.assert_called_once_with(
            client_cert=("/certs/client-cert.pem", "/certs/client-key.pem"),
            ca_cert="/certs/ca.pem",
            verify=True,
        )

        # Verify Docker client was created with TLS and timeout
        mock_docker_client.assert_called_once_with(
            base_url="tcp://10.2.96.4:2376", tls=mock_tls, timeout=5
        )

    @patch("ciris_manager.multi_server_docker.docker.from_env")
    def test_get_client_caching(self, mock_from_env, local_server_config):
        """Test that Docker clients are cached."""
        mock_docker_client = Mock()
        mock_from_env.return_value = mock_docker_client

        client = MultiServerDockerClient([local_server_config])

        # Get client twice
        docker_client1 = client.get_client("main")
        docker_client2 = client.get_client("main")

        # Should return same instance
        assert docker_client1 is docker_client2

        # Should only call from_env once
        assert mock_from_env.call_count == 1

    def test_get_client_unknown_server(self, local_server_config):
        """Test getting client for unknown server."""
        client = MultiServerDockerClient([local_server_config])

        with pytest.raises(ValueError, match="Unknown server 'unknown'"):
            client.get_client("unknown")

    def test_get_client_remote_missing_docker_host(self):
        """Test getting client for remote server without docker_host."""
        config = ServerConfig(
            server_id="scout",
            hostname="scoutapi.ciris.ai",
            is_local=False,
            # Missing docker_host
        )

        client = MultiServerDockerClient([config])

        with pytest.raises(ValueError, match="docker_host is not configured"):
            client.get_client("scout")

    def test_get_client_remote_missing_tls_certs(self):
        """Test getting client for remote server without TLS certificates."""
        config = ServerConfig(
            server_id="scout",
            hostname="scoutapi.ciris.ai",
            is_local=False,
            docker_host="tcp://10.2.96.4:2376",
            # Missing TLS certs
        )

        client = MultiServerDockerClient([config])

        with pytest.raises(ValueError, match="requires TLS certificates"):
            client.get_client("scout")

    @patch("ciris_manager.multi_server_docker.docker.from_env")
    def test_test_connection_success(self, mock_from_env, local_server_config):
        """Test successful connection test."""
        mock_docker_client = Mock()
        mock_docker_client.ping.return_value = True
        mock_from_env.return_value = mock_docker_client

        client = MultiServerDockerClient([local_server_config])
        result = client.test_connection("main")

        assert result is True
        mock_docker_client.ping.assert_called_once()

    @patch("ciris_manager.multi_server_docker.docker.from_env")
    def test_test_connection_failure(self, mock_from_env, local_server_config):
        """Test failed connection test."""
        mock_docker_client = Mock()
        mock_docker_client.ping.side_effect = Exception("Connection failed")
        mock_from_env.return_value = mock_docker_client

        client = MultiServerDockerClient([local_server_config])
        result = client.test_connection("main")

        assert result is False

    @patch("ciris_manager.multi_server_docker.docker.from_env")
    def test_close_all(self, mock_from_env, local_server_config):
        """Test closing all Docker client connections."""
        mock_docker_client = Mock()
        mock_from_env.return_value = mock_docker_client

        client = MultiServerDockerClient([local_server_config])

        # Get client to create it
        client.get_client("main")

        # Close all
        client.close_all()

        # Verify close was called
        mock_docker_client.close.assert_called_once()

        # Verify clients cleared
        assert len(client._clients) == 0

    @patch("ciris_manager.multi_server_docker.docker.from_env")
    def test_context_manager(self, mock_from_env, local_server_config):
        """Test using MultiServerDockerClient as context manager."""
        mock_docker_client = Mock()
        mock_from_env.return_value = mock_docker_client

        with MultiServerDockerClient([local_server_config]) as client:
            client.get_client("main")
            # Client should be created
            assert len(client._clients) == 1

        # After exiting context, close should be called
        mock_docker_client.close.assert_called_once()

    @patch("ciris_manager.multi_server_docker.docker.from_env")
    def test_close_all_handles_errors(self, mock_from_env, local_server_config):
        """Test close_all handles errors gracefully."""
        mock_docker_client = Mock()
        mock_docker_client.close.side_effect = Exception("Close failed")
        mock_from_env.return_value = mock_docker_client

        client = MultiServerDockerClient([local_server_config])
        client.get_client("main")

        # Should not raise exception
        client.close_all()

        # Verify clients still cleared despite error
        assert len(client._clients) == 0


class TestCircuitBreaker:
    """Test cases for circuit breaker functionality."""

    @pytest.fixture(autouse=True)
    def clear_circuit_breaker(self):
        """Clear circuit breaker state before and after each test."""
        from ciris_manager.multi_server_docker import _server_failures
        _server_failures.clear()
        yield
        _server_failures.clear()

    @pytest.fixture
    def remote_server_config(self):
        """Create remote server configuration."""
        return ServerConfig(
            server_id="scout",
            hostname="scoutapi.ciris.ai",
            is_local=False,
            vpc_ip="10.2.96.4",
            docker_host="tcp://10.2.96.4:2376",
            tls_ca="/certs/ca.pem",
            tls_cert="/certs/client-cert.pem",
            tls_key="/certs/client-key.pem",
        )

    def test_is_server_available_initially(self, remote_server_config):
        """Test server is available when not marked as failed."""
        client = MultiServerDockerClient([remote_server_config])
        available, error = client.is_server_available("scout")
        assert available is True
        assert error is None

    def test_mark_server_failed(self, remote_server_config):
        """Test marking a server as failed triggers circuit breaker."""
        client = MultiServerDockerClient([remote_server_config])
        client.mark_server_failed("scout", "Connection refused")
        
        available, error = client.is_server_available("scout")
        assert available is False
        assert "Connection refused" in error

    def test_mark_server_healthy_clears_failure(self, remote_server_config):
        """Test marking server healthy clears circuit breaker."""
        client = MultiServerDockerClient([remote_server_config])
        client.mark_server_failed("scout", "Connection refused")
        client.mark_server_healthy("scout")
        
        available, error = client.is_server_available("scout")
        assert available is True
        assert error is None

    @patch("ciris_manager.multi_server_docker.DockerClient")
    @patch("ciris_manager.multi_server_docker.TLSConfig")
    def test_get_client_respects_circuit_breaker(
        self, mock_tls_config, mock_docker_client, remote_server_config
    ):
        """Test get_client raises ConnectionError when circuit breaker is open."""
        client = MultiServerDockerClient([remote_server_config])
        client.mark_server_failed("scout", "Connection refused")
        
        with pytest.raises(ConnectionError) as exc_info:
            client.get_client("scout")
        
        assert "circuit breaker" in str(exc_info.value).lower()

    @patch("ciris_manager.multi_server_docker.time.time")
    def test_circuit_breaker_timeout_resets(self, mock_time, remote_server_config):
        """Test circuit breaker resets after timeout."""
        from ciris_manager.multi_server_docker import CIRCUIT_BREAKER_TIMEOUT
        
        client = MultiServerDockerClient([remote_server_config])
        
        # Mark failed at time 0
        mock_time.return_value = 0
        client.mark_server_failed("scout", "Connection refused")
        
        # Still in cooldown at time 30
        mock_time.return_value = 30
        available, _ = client.is_server_available("scout")
        assert available is False
        
        # Reset after timeout
        mock_time.return_value = CIRCUIT_BREAKER_TIMEOUT + 1
        available, _ = client.is_server_available("scout")
        assert available is True
