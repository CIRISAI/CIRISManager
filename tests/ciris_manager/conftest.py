"""
Shared fixtures for CIRISManager tests.
"""

import pytest
from unittest.mock import Mock
from ciris_manager.config.settings import CIRISManagerConfig


@pytest.fixture
def temp_dirs(tmp_path):
    """Create temporary directories for testing."""
    dirs = {
        "agents": tmp_path / "agents",
        "templates": tmp_path / "templates",
        "nginx": tmp_path / "nginx",
        "config": tmp_path / "config",
    }
    for dir_path in dirs.values():
        dir_path.mkdir(parents=True, exist_ok=True)
    return dirs


@pytest.fixture
def multi_server_config(temp_dirs):
    """Config with main and scout servers."""
    # Create manifest file
    manifest_path = temp_dirs["config"] / "manifest.json"
    manifest_path.write_text('{"root_public_key": "test-key", "approved_templates": ["scout"]}')

    return CIRISManagerConfig(
        manager={
            "agents_directory": str(temp_dirs["agents"]),
            "templates_directory": str(temp_dirs["templates"]),
            "manifest_path": str(manifest_path),
        },
        nginx={"config_dir": str(temp_dirs["nginx"]), "enabled": True},
        servers=[
            {"server_id": "main", "hostname": "agents.ciris.ai", "is_local": True},
            {
                "server_id": "scout",
                "hostname": "scoutapi.ciris.ai",
                "is_local": False,
                "vpc_ip": "10.2.96.4",
                "docker_host": "https://10.2.96.4:2376",
                "tls_ca": "/fake/ca.pem",
                "tls_cert": "/fake/cert.pem",
                "tls_key": "/fake/key.pem",
            },
        ],
    )


@pytest.fixture
def mock_docker_client():
    """Mock MultiServerDockerClient with proper server config."""
    mock = Mock()
    mock.test_connection = Mock(return_value=True)

    # Mock get_server_config to return server configs
    def get_server_config_side_effect(server_id):
        from ciris_manager.config.settings import ServerConfig

        if server_id == "main":
            return ServerConfig(server_id="main", hostname="agents.ciris.ai", is_local=True)
        elif server_id == "scout":
            return ServerConfig(
                server_id="scout",
                hostname="scoutapi.ciris.ai",
                is_local=False,
                vpc_ip="10.2.96.4",
                docker_host="https://10.2.96.4:2376",
                tls_ca="/fake/ca.pem",
                tls_cert="/fake/cert.pem",
                tls_key="/fake/key.pem",
            )
        raise ValueError(f"Unknown server: {server_id}")

    mock.get_server_config = Mock(side_effect=get_server_config_side_effect)

    # Mock container for remote nginx deployment
    mock_container = Mock()
    mock_exec_result = Mock()
    mock_exec_result.exit_code = 0
    mock_exec_result.output = b""
    mock_container.exec_run = Mock(return_value=mock_exec_result)

    mock_remote_client = Mock()
    mock_remote_client.containers.get = Mock(return_value=mock_container)

    mock.get_client = Mock(return_value=mock_remote_client)
    mock.list_servers = Mock(return_value=["main", "scout"])

    return mock


@pytest.fixture
def mock_nginx_managers():
    """Create mock nginx managers for main and scout servers."""
    # Main server nginx manager
    mock_main = Mock()
    mock_main.update_config = Mock(return_value=True)
    mock_main.generate_config = Mock(return_value="main nginx config")

    # Scout server nginx manager
    mock_scout = Mock()
    mock_scout.generate_config = Mock(return_value="scout nginx config")
    mock_scout.deploy_remote_config = Mock(return_value=True)

    return {"main": mock_main, "scout": mock_scout}


@pytest.fixture
def mock_agent_discovery():
    """Mock DockerAgentDiscovery that returns test agents."""
    mock_discovery_class = Mock()
    mock_discovery = Mock()

    # Default: no agents
    mock_discovery.discover_agents = Mock(return_value=[])
    mock_discovery_class.return_value = mock_discovery

    return mock_discovery_class, mock_discovery
