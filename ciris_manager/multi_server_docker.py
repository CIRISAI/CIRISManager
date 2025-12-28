"""
Multi-server Docker client for managing containers across multiple hosts.

Provides unified Docker API access to both local and remote Docker daemons
with TLS authentication.
"""

import logging
import time
from typing import Dict, Optional, Tuple
import docker
from docker import DockerClient
from docker.tls import TLSConfig

from ciris_manager.config.settings import ServerConfig

logger = logging.getLogger(__name__)

# Connection timeout for remote Docker API (seconds)
DOCKER_CONNECTION_TIMEOUT = 5

# Circuit breaker: skip servers that failed recently
_server_failures: Dict[str, Tuple[float, str]] = {}  # server_id -> (failure_time, error_msg)
CIRCUIT_BREAKER_TIMEOUT = 60  # seconds to wait before retrying failed server


class MultiServerDockerClient:
    """
    Manages Docker connections to multiple servers.

    Provides access to Docker clients for both local and remote servers,
    handling TLS authentication automatically for remote connections.
    """

    def __init__(self, servers: list[ServerConfig]):
        """
        Initialize multi-server Docker client.

        Args:
            servers: List of server configurations
        """
        self.servers: Dict[str, ServerConfig] = {s.server_id: s for s in servers}
        self._clients: Dict[str, DockerClient] = {}

        logger.info(f"Initialized multi-server Docker client with {len(servers)} servers")
        for server in servers:
            logger.info(
                f"  - {server.server_id}: {server.hostname} "
                f"(local={server.is_local}, vpc_ip={server.vpc_ip})"
            )

    def is_server_available(self, server_id: str) -> Tuple[bool, Optional[str]]:
        """
        Check if server is available (not in circuit breaker cooldown).

        Args:
            server_id: Server identifier

        Returns:
            Tuple of (is_available, error_message if unavailable)
        """
        if server_id in _server_failures:
            failure_time, error_msg = _server_failures[server_id]
            elapsed = time.time() - failure_time
            if elapsed < CIRCUIT_BREAKER_TIMEOUT:
                remaining = int(CIRCUIT_BREAKER_TIMEOUT - elapsed)
                return False, f"Circuit breaker open ({remaining}s remaining): {error_msg}"
            else:
                # Circuit breaker timeout expired, remove from failures
                del _server_failures[server_id]
                logger.info(f"Circuit breaker reset for {server_id}")
        return True, None

    def mark_server_failed(self, server_id: str, error: str) -> None:
        """Mark a server as failed for circuit breaker."""
        _server_failures[server_id] = (time.time(), error)
        logger.warning(f"Server {server_id} marked as failed: {error}")

    def mark_server_healthy(self, server_id: str) -> None:
        """Mark a server as healthy (clear circuit breaker)."""
        if server_id in _server_failures:
            del _server_failures[server_id]
            logger.info(f"Server {server_id} marked as healthy")

    def get_client(self, server_id: str = "main") -> DockerClient:
        """
        Get Docker client for a specific server.

        Args:
            server_id: Server identifier (e.g., 'main', 'scout')

        Returns:
            Docker client instance

        Raises:
            ValueError: If server_id is not configured
            ConnectionError: If server is in circuit breaker cooldown
        """
        if server_id not in self.servers:
            available_servers = ", ".join(self.servers.keys())
            raise ValueError(
                f"Unknown server '{server_id}'. Available servers: {available_servers}"
            )

        # Check circuit breaker
        is_available, error = self.is_server_available(server_id)
        if not is_available:
            raise ConnectionError(f"Server {server_id} unavailable: {error}")

        # Return cached client if available
        if server_id in self._clients:
            return self._clients[server_id]

        # Create new client
        server = self.servers[server_id]

        if server.is_local:
            # Local server - use Unix socket
            logger.debug(f"Creating local Docker client for {server_id}")
            client = docker.from_env()
        else:
            # Remote server - use TLS
            if not server.docker_host:
                raise ValueError(
                    f"Server '{server_id}' is remote but docker_host is not configured"
                )

            if not all([server.tls_ca, server.tls_cert, server.tls_key]):
                raise ValueError(
                    f"Server '{server_id}' requires TLS certificates " "(tls_ca, tls_cert, tls_key)"
                )

            logger.debug(f"Creating remote Docker client for {server_id} at {server.docker_host}")

            # Type assertions for mypy - we've already checked these are not None
            assert server.tls_cert is not None
            assert server.tls_key is not None
            assert server.tls_ca is not None

            tls_config = TLSConfig(
                client_cert=(server.tls_cert, server.tls_key),
                ca_cert=server.tls_ca,
                verify=True,
            )

            # Use short timeout to fail fast on unreachable servers
            client = DockerClient(
                base_url=server.docker_host, tls=tls_config, timeout=DOCKER_CONNECTION_TIMEOUT
            )

        # Cache and return
        self._clients[server_id] = client
        logger.info(f"Docker client created for {server_id}")

        return client

    def get_server_config(self, server_id: str) -> ServerConfig:
        """
        Get server configuration by ID.

        Args:
            server_id: Server identifier

        Returns:
            Server configuration

        Raises:
            ValueError: If server_id is not configured
        """
        if server_id not in self.servers:
            available = ", ".join(self.servers.keys())
            raise ValueError(f"Unknown server '{server_id}'. Available servers: {available}")

        return self.servers[server_id]

    def list_servers(self) -> list[str]:
        """
        List all configured server IDs.

        Returns:
            List of server IDs
        """
        return list(self.servers.keys())

    def test_connection(self, server_id: str) -> bool:
        """
        Test Docker API connection to a server.

        Args:
            server_id: Server identifier

        Returns:
            True if connection successful, False otherwise
        """
        try:
            client = self.get_client(server_id)
            # Ping Docker API
            client.ping()
            logger.info(f"Docker API connection test successful for {server_id}")
            return True
        except Exception as e:
            logger.error(f"Docker API connection test failed for {server_id}: {e}")
            return False

    def close_all(self) -> None:
        """Close all Docker client connections."""
        for server_id, client in self._clients.items():
            try:
                client.close()
                logger.debug(f"Closed Docker client for {server_id}")
            except Exception as e:
                logger.warning(f"Error closing Docker client for {server_id}: {e}")

        self._clients.clear()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - close all connections."""
        self.close_all()
