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
    mock_main.update_config = Mock(return_value=(True, ""))
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


def _create_mock_container(agent_info, current_image="ghcr.io/cirisai/ciris-agent:1.5.0"):
    """Create a properly mocked Docker container for an agent."""
    mock_container = Mock()
    mock_container.name = agent_info.container_name
    mock_container.id = f"container-{agent_info.agent_id}"
    mock_container.status = "running"

    # Mock image with tags
    mock_image = Mock()
    mock_image.tags = [current_image]
    mock_image.id = f"sha256:{'a'*64}"
    mock_container.image = mock_image

    # Mock attrs for environment variables
    mock_container.attrs = {
        "Config": {
            "Env": [
                f"CIRIS_AGENT_ID={agent_info.agent_id}",
                f"CIRIS_API_PORT={agent_info.api_port}",
            ],
            "Image": current_image,
        },
        "State": {
            "Status": "running",
            "Running": True,
        },
    }

    # Mock methods
    mock_container.stop = Mock()
    mock_container.remove = Mock()
    mock_container.restart = Mock()

    return mock_container


def _create_mock_docker_client(server_id, containers_map=None):
    """
    Create a properly mocked Docker client for a server.

    Args:
        server_id: Server ID (main, scout, scout2, etc.)
        containers_map: Dict mapping container names to AgentInfo objects
    """
    mock_client = Mock()

    # Mock images.pull
    mock_images = Mock()
    mock_images.pull = Mock(return_value=None)
    mock_images.get = Mock(return_value=Mock(tags=["ghcr.io/cirisai/ciris-agent:1.5.1"]))
    mock_client.images = mock_images

    # Mock containers
    mock_containers = Mock()

    def get_container_side_effect(name_or_id):
        """Return proper container mock based on name."""
        if containers_map and name_or_id in containers_map:
            agent_info = containers_map[name_or_id]
            return _create_mock_container(agent_info)
        # Return a generic container if not found
        return _create_mock_container(
            type(
                "obj",
                (object,),
                {"agent_id": name_or_id, "container_name": name_or_id, "api_port": 8000},
            )()
        )

    mock_containers.get = Mock(side_effect=get_container_side_effect)
    mock_containers.list = Mock(return_value=[])
    mock_containers.run = Mock(return_value=Mock(id="new-container-id"))
    mock_client.containers = mock_containers

    return mock_client


@pytest.fixture
def mock_manager(tmp_path):
    """Create mock manager with agent registry and fully mocked docker client."""
    from ciris_manager.agent_registry import AgentRegistry

    manager = Mock()
    manager.agent_registry = AgentRegistry(tmp_path / "metadata.json")

    # Mock docker_client with multi-server support
    mock_docker_client_mgr = Mock()

    # Store clients for easy access in tests
    clients = {
        "main": _create_mock_docker_client("main"),
        "scout": _create_mock_docker_client("scout"),
        "scout2": _create_mock_docker_client("scout2"),
    }

    def get_client_side_effect(server_id):
        return clients.get(server_id, clients["main"])

    mock_docker_client_mgr.get_client = Mock(side_effect=get_client_side_effect)
    mock_docker_client_mgr._clients = clients  # Store for test access

    # Mock get_server_config
    from ciris_manager.config.settings import ServerConfig

    def get_server_config_side_effect(server_id):
        if server_id == "main":
            return ServerConfig(server_id="main", hostname="agents.ciris.ai", is_local=True)
        elif server_id == "scout":
            return ServerConfig(
                server_id="scout",
                hostname="scoutapi.ciris.ai",
                is_local=False,
                vpc_ip="10.2.96.4",
            )
        elif server_id == "scout2":
            return ServerConfig(
                server_id="scout2",
                hostname="scout2api.ciris.ai",
                is_local=False,
                vpc_ip="10.3.96.4",
            )
        raise ValueError(f"Unknown server: {server_id}")

    mock_docker_client_mgr.get_server_config = Mock(side_effect=get_server_config_side_effect)
    manager.docker_client = mock_docker_client_mgr

    return manager


@pytest.fixture
def orchestrator(mock_manager, tmp_path):
    """Create deployment orchestrator with mocked dependencies."""
    from ciris_manager.deployment_orchestrator import DeploymentOrchestrator
    from unittest.mock import AsyncMock

    orchestrator = DeploymentOrchestrator(manager=mock_manager)

    # Use temporary directory for state to ensure isolation
    orchestrator.state_dir = tmp_path / "state"
    orchestrator.state_dir.mkdir(exist_ok=True)
    orchestrator.deployment_state_file = orchestrator.state_dir / "deployment_state.json"

    # Clear any existing deployments to ensure clean state
    orchestrator.deployments = {}
    orchestrator.current_deployment = None

    # Mock the registry client to avoid real network calls
    orchestrator.registry_client = Mock()
    orchestrator.registry_client.resolve_image_digest = AsyncMock(return_value="sha256:test123")

    return orchestrator


@pytest.fixture
def update_notification():
    """Create sample update notification."""
    from ciris_manager.models import UpdateNotification

    return UpdateNotification(
        agent_image="ghcr.io/cirisai/ciris-agent:v2.0",
        gui_image="ghcr.io/cirisai/ciris-gui:v2.0",
        message="Security update",
        strategy="canary",
        metadata={"version": "2.0"},
    )


@pytest.fixture
def sample_agents():
    """Create sample agents across multiple servers."""
    from ciris_manager.models import AgentInfo

    agents = []
    for i in range(10):
        # Distribute agents across servers
        if i < 6:
            server_id = "main"
        elif i < 8:
            server_id = "scout"
        else:
            server_id = "scout2"

        agents.append(
            AgentInfo(
                agent_id=f"agent-{i}",
                agent_name=f"Agent {i}",
                container_name=f"ciris-agent-{i}",
                api_port=8080 + i,
                status="running",
                server_id=server_id,
            )
        )
    return agents
