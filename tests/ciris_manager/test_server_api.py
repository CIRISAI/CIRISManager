"""
Unit tests for server management API endpoints.
"""

import pytest
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient
from fastapi import FastAPI

from ciris_manager.api.server_routes import create_server_routes
from ciris_manager.config.settings import ServerConfig, CIRISManagerConfig
from ciris_manager.agent_registry import RegisteredAgent


@pytest.fixture
def mock_manager():
    """Create a mock manager instance."""
    manager = Mock()

    # Configure servers
    manager.config = CIRISManagerConfig()
    manager.config.servers = [
        ServerConfig(server_id="main", hostname="agents.ciris.ai", is_local=True),
        ServerConfig(
            server_id="scout",
            hostname="scoutapi.ciris.ai",
            is_local=False,
            vpc_ip="10.2.96.4",
            docker_host="https://10.2.96.4:2376",
        ),
    ]

    # Mock docker client
    manager.docker_client = Mock()
    manager.docker_client.test_connection = Mock(return_value=True)
    manager.docker_client.get_server_config = Mock(
        side_effect=lambda sid: next(s for s in manager.config.servers if s.server_id == sid)
    )

    # Mock agent registry
    manager.agent_registry = Mock()
    manager.agent_registry.list_agents = Mock(
        return_value=[
            RegisteredAgent(
                agent_id="agent1",
                name="Agent 1",
                port=8001,
                template="scout",
                compose_file="/path/to/compose.yml",
                service_token="token1",
                server_id="main",
            ),
            RegisteredAgent(
                agent_id="agent2",
                name="Agent 2",
                port=8002,
                template="scout",
                compose_file="/path/to/compose2.yml",
                service_token="token2",
                server_id="scout",
            ),
        ]
    )

    return manager


@pytest.fixture
def test_client(mock_manager):
    """Create a test client with server routes."""
    app = FastAPI()
    router = create_server_routes(mock_manager)
    app.include_router(router)
    return TestClient(app)


class TestListServers:
    """Tests for GET /servers endpoint."""

    def test_list_servers_success(self, test_client, mock_manager):
        """Test listing all servers."""
        response = test_client.get("/servers")

        assert response.status_code == 200
        servers = response.json()

        assert len(servers) == 2
        assert servers[0]["server_id"] == "main"
        assert servers[0]["hostname"] == "agents.ciris.ai"
        assert servers[0]["is_local"] is True
        assert servers[0]["status"] == "online"
        assert servers[0]["agent_count"] == 1

        assert servers[1]["server_id"] == "scout"
        assert servers[1]["hostname"] == "scoutapi.ciris.ai"
        assert servers[1]["is_local"] is False
        assert servers[1]["vpc_ip"] == "10.2.96.4"
        assert servers[1]["status"] == "online"
        assert servers[1]["agent_count"] == 1

    def test_list_servers_offline(self, test_client, mock_manager):
        """Test listing servers when one is offline."""

        # Make scout server offline
        def test_connection(server_id):
            return server_id == "main"

        mock_manager.docker_client.test_connection = Mock(side_effect=test_connection)

        response = test_client.get("/servers")

        assert response.status_code == 200
        servers = response.json()

        main_server = next(s for s in servers if s["server_id"] == "main")
        scout_server = next(s for s in servers if s["server_id"] == "scout")

        assert main_server["status"] == "online"
        assert scout_server["status"] == "offline"


class TestGetServerDetails:
    """Tests for GET /servers/{server_id} endpoint."""

    def test_get_server_details_success(self, test_client, mock_manager):
        """Test getting detailed server information."""
        response = test_client.get("/servers/main")

        assert response.status_code == 200
        data = response.json()

        assert data["server_id"] == "main"
        assert data["hostname"] == "agents.ciris.ai"
        assert data["status"] == "online"
        assert data["agent_count"] == 1
        assert "agent1" in data["agents"]
        # Stats may be None if psutil not available or stats retrieval fails
        # This is expected behavior

    def test_get_server_details_not_found(self, test_client, mock_manager):
        """Test getting details for non-existent server."""
        # Make get_server_config raise ValueError
        mock_manager.docker_client.get_server_config = Mock(
            side_effect=ValueError("Server not found")
        )

        response = test_client.get("/servers/nonexistent")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


class TestGetServerStats:
    """Tests for GET /servers/{server_id}/stats endpoint."""

    @patch("psutil.cpu_percent")
    @patch("psutil.virtual_memory")
    @patch("psutil.disk_usage")
    @patch("psutil.getloadavg")
    def test_get_local_server_stats(
        self, mock_loadavg, mock_disk, mock_mem, mock_cpu, test_client, mock_manager
    ):
        """Test getting stats for local server using psutil."""
        # Mock psutil responses
        mock_cpu.return_value = 45.2
        mock_mem.return_value = Mock(
            percent=62.5,
            total=34359738368,  # 32 GB
            used=21474836480,  # 20 GB
        )
        mock_disk.return_value = Mock(
            percent=55.0,
            total=536870912000,  # 500 GB
            used=295147905280,  # 275 GB
        )
        mock_loadavg.return_value = (1.5, 1.2, 0.9)

        response = test_client.get("/servers/main/stats")

        assert response.status_code == 200
        stats = response.json()

        assert stats["cpu_percent"] == 45.2
        assert stats["memory_percent"] == 62.5
        assert stats["memory_total_gb"] == 32.0
        assert stats["disk_percent"] == 55.0
        assert stats["load_average"] == [1.5, 1.2, 0.9]

    def test_get_remote_server_stats_error(self, test_client, mock_manager):
        """Test getting stats for offline remote server."""
        # Make docker client unavailable
        mock_manager.docker_client.get_client = Mock(side_effect=Exception("Connection refused"))

        response = test_client.get("/servers/scout/stats")

        assert response.status_code == 503
        assert "offline" in response.json()["detail"].lower()


class TestListServerAgents:
    """Tests for GET /servers/{server_id}/agents endpoint."""

    def test_list_agents_on_server(self, test_client, mock_manager):
        """Test listing agents on a specific server."""
        response = test_client.get("/servers/main/agents")

        assert response.status_code == 200
        agents = response.json()

        assert len(agents) == 1
        assert "agent1" in agents

    def test_list_agents_scout_server(self, test_client, mock_manager):
        """Test listing agents on scout server."""
        response = test_client.get("/servers/scout/agents")

        assert response.status_code == 200
        agents = response.json()

        assert len(agents) == 1
        assert "agent2" in agents

    def test_list_agents_server_not_found(self, test_client, mock_manager):
        """Test listing agents on non-existent server."""
        mock_manager.docker_client.get_server_config = Mock(
            side_effect=ValueError("Server not found")
        )

        response = test_client.get("/servers/invalid/agents")

        assert response.status_code == 404
