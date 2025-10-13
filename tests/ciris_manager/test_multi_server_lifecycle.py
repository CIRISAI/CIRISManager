"""
Unit tests for multi-server agent lifecycle (create, delete, recovery).
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from pathlib import Path
import yaml

from ciris_manager.manager import CIRISManager
from ciris_manager.config.settings import CIRISManagerConfig, ServerConfig


@pytest.fixture
def multi_server_config(temp_dirs):
    """Create config with multiple servers."""
    # Create manifest file BEFORE initializing config
    manifest_path = temp_dirs["config"] / "manifest.json"
    manifest_path.write_text('{"root_public_key": "test-key", "approved_templates": ["scout"]}')

    config = CIRISManagerConfig(
        docker={"compose_file": "docker-compose.yml", "registry": "ghcr.io", "image": "test/agent"},
        watchdog={"check_interval": 30, "crash_threshold": 3, "crash_window": 300},
        container_management={"check_interval": 60, "auto_pull": False},
        api={"host": "0.0.0.0", "port": 8888},
        manager={
            "agents_directory": str(temp_dirs["agents"]),
            "templates_directory": str(temp_dirs["templates"]),
            "manifest_path": str(manifest_path),
        },
        nginx={
            "config_dir": str(temp_dirs["nginx"]),
            "container_name": "test-nginx",
            "enabled": True,
        },
        ports={"start": 8001, "end": 8100, "reserved": []},
        servers=[
            ServerConfig(server_id="main", hostname="agents.ciris.ai", is_local=True),
            ServerConfig(
                server_id="scout",
                hostname="scoutapi.ciris.ai",
                is_local=False,
                vpc_ip="10.2.96.4",
                docker_host="https://10.2.96.4:2376",
                tls_ca="/path/to/ca.pem",
                tls_cert="/path/to/cert.pem",
                tls_key="/path/to/key.pem",
            ),
        ],
    )
    return config


@pytest.fixture
def multi_server_manager(multi_server_config):
    """Create manager with mocked multi-server Docker client."""
    with (
        patch("ciris_manager.nginx_manager.NginxManager") as mock_nginx,
        patch("ciris_manager.multi_server_docker.MultiServerDockerClient") as mock_docker_class,
        patch("ciris_manager.manager.DockerImageCleanup"),
        patch(
            "ciris_manager.template_verifier.TemplateVerifier.is_pre_approved",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("ciris_manager.docker_discovery.DockerAgentDiscovery"),
    ):
        # Configure mock nginx manager
        mock_nginx_instance = Mock()
        mock_nginx_instance.update_config = Mock(return_value=True)
        mock_nginx_instance.remove_agent_routes = Mock(return_value=True)
        mock_nginx.return_value = mock_nginx_instance

        # Configure mock Docker client
        mock_docker_client = Mock()
        mock_docker_client.test_connection = Mock(return_value=True)

        def mock_get_server_config(sid):
            for s in multi_server_config.servers:
                if s.server_id == sid:
                    return s
            available = ", ".join([s.server_id for s in multi_server_config.servers])
            raise ValueError(f"Unknown server '{sid}'. Available servers: {available}")

        mock_docker_client.get_server_config = Mock(side_effect=mock_get_server_config)
        mock_docker_client.get_client = Mock()
        mock_docker_client.servers = {s.server_id: s for s in multi_server_config.servers}
        mock_docker_client.list_servers = Mock(return_value=["main", "scout"])

        mock_docker_class.return_value = mock_docker_client

        manager = CIRISManager(multi_server_config)
        manager.docker_client = mock_docker_client
        yield manager


class TestMultiServerAgentCreation:
    """Tests for creating agents on specific servers."""

    @pytest.mark.asyncio
    async def test_create_agent_on_main_server(self, multi_server_manager, temp_dirs):
        """Test creating agent on main (local) server."""
        # Create template
        template_path = temp_dirs["templates"] / "scout.yaml"
        template_path.write_text("name: scout\nversion: 1.0")

        # Mock docker-compose execution
        with patch("asyncio.create_subprocess_exec") as mock_subprocess:
            mock_process = AsyncMock()
            mock_process.communicate = AsyncMock(return_value=(b"", b""))
            mock_process.returncode = 0
            mock_subprocess.return_value = mock_process

            result = await multi_server_manager.create_agent(
                template="scout", name="test-agent", server_id="main"
            )

            assert result["agent_id"].startswith("test-agent-")
            assert result["status"] == "starting"

            # Verify agent was registered with correct server_id
            agent_info = multi_server_manager.agent_registry.get_agent(result["agent_id"])
            assert agent_info.server_id == "main"

    @pytest.mark.asyncio
    async def test_create_agent_on_remote_server(self, multi_server_manager, temp_dirs):
        """Test creating agent on remote scout server."""
        # Create template
        template_path = temp_dirs["templates"] / "scout.yaml"
        template_path.write_text("name: scout\nversion: 1.0")

        # Mock remote Docker client
        mock_remote_docker = Mock()
        mock_container = Mock()
        mock_remote_docker.containers.run = Mock(return_value=mock_container)
        # Mock containers.get to fail so we use Alpine fallback for directory creation
        mock_remote_docker.containers.get = Mock(side_effect=Exception("No nginx container"))
        multi_server_manager.docker_client.get_client = Mock(return_value=mock_remote_docker)

        result = await multi_server_manager.create_agent(
            template="scout", name="scout-agent", server_id="scout"
        )

        assert result["agent_id"].startswith("scout-agent-")

        # Verify agent was registered with scout server_id
        agent_info = multi_server_manager.agent_registry.get_agent(result["agent_id"])
        assert agent_info.server_id == "scout"

        # Verify Docker API was called multiple times:
        # - 1 time for base directory creation
        # - 6 times for subdirectories (data, data_archive, logs, config, audit_keys, .secrets)
        # - 1 time for permission fix script
        # - 1 time for the actual agent container
        assert mock_remote_docker.containers.run.call_count == 9

        # Verify the last call (the agent container) has the expected image
        last_call = mock_remote_docker.containers.run.call_args_list[-1]
        assert last_call[1]["image"] == "ghcr.io/test/agent"

    @pytest.mark.asyncio
    async def test_create_agent_invalid_server(self, multi_server_manager, temp_dirs):
        """Test creating agent on non-existent server fails."""
        # Create template
        template_path = temp_dirs["templates"] / "scout.yaml"
        template_path.write_text("name: scout\nversion: 1.0")

        with pytest.raises(ValueError, match="Unknown server"):
            await multi_server_manager.create_agent(
                template="scout", name="test", server_id="invalid"
            )

    @pytest.mark.asyncio
    async def test_create_agent_defaults_to_main(self, multi_server_manager, temp_dirs):
        """Test agent creation defaults to main server when server_id not specified."""
        template_path = temp_dirs["templates"] / "scout.yaml"
        template_path.write_text("name: scout\nversion: 1.0")

        with patch("asyncio.create_subprocess_exec") as mock_subprocess:
            mock_process = AsyncMock()
            mock_process.communicate = AsyncMock(return_value=(b"", b""))
            mock_process.returncode = 0
            mock_subprocess.return_value = mock_process

            result = await multi_server_manager.create_agent(
                template="scout",
                name="default-agent",
                # No server_id specified
            )

            agent_info = multi_server_manager.agent_registry.get_agent(result["agent_id"])
            assert agent_info.server_id == "main"


class TestMultiServerAgentDeletion:
    """Tests for deleting agents from specific servers."""

    @pytest.mark.asyncio
    async def test_delete_agent_from_local_server(self, multi_server_manager, temp_dirs):
        """Test deleting agent from local server uses docker-compose."""
        # Create compose file
        compose_path = temp_dirs["agents"] / "local-agent" / "docker-compose.yml"
        compose_path.parent.mkdir(parents=True, exist_ok=True)
        compose_path.write_text("version: '3'")

        # Register agent on main server
        multi_server_manager.agent_registry.register_agent(
            agent_id="local-agent",
            name="Local Agent",
            port=8001,
            template="scout",
            compose_file=str(compose_path),
            server_id="main",
        )

        with patch("asyncio.create_subprocess_exec") as mock_subprocess:
            mock_process = AsyncMock()
            mock_process.communicate = AsyncMock(return_value=(b"", b""))
            mock_subprocess.return_value = mock_process

            result = await multi_server_manager.delete_agent("local-agent")

            assert result is True
            # Verify docker-compose down was called
            mock_subprocess.assert_called()
            args = mock_subprocess.call_args[0]
            assert "docker-compose" in args

    @pytest.mark.asyncio
    async def test_delete_agent_from_remote_server(self, multi_server_manager, temp_dirs):
        """Test deleting agent from remote server uses Docker API."""
        # Create compose file
        compose_path = temp_dirs["agents"] / "remote-agent" / "docker-compose.yml"
        compose_path.parent.mkdir(parents=True, exist_ok=True)
        compose_path.write_text("version: '3'")

        # Register agent on scout server
        multi_server_manager.agent_registry.register_agent(
            agent_id="remote-agent",
            name="Remote Agent",
            port=8002,
            template="scout",
            compose_file=str(compose_path),
            server_id="scout",
        )

        # Mock remote Docker client
        mock_remote_docker = Mock()
        mock_container = Mock()
        mock_remote_docker.containers.get = Mock(return_value=mock_container)
        multi_server_manager.docker_client.get_client = Mock(return_value=mock_remote_docker)

        result = await multi_server_manager.delete_agent("remote-agent")

        assert result is True
        # Verify Docker API stop/remove was called
        mock_container.stop.assert_called_once()
        mock_container.remove.assert_called_once()


class TestMultiServerCrashRecovery:
    """Tests for crash recovery across multiple servers."""

    @pytest.mark.asyncio
    async def test_crash_recovery_queries_all_servers(self, multi_server_manager):
        """Test that crash recovery checks all configured servers."""
        # Register agents on different servers
        multi_server_manager.agent_registry.agents = {
            "main-agent": Mock(
                agent_id="main-agent", server_id="main", compose_file="/path/main.yml"
            ),
            "scout-agent": Mock(
                agent_id="scout-agent", server_id="scout", compose_file="/path/scout.yml"
            ),
        }
        multi_server_manager.agent_registry.list_agents = Mock(
            return_value=list(multi_server_manager.agent_registry.agents.values())
        )

        # Mock Docker clients for both servers
        main_client = Mock()
        scout_client = Mock()

        def get_client(server_id):
            return main_client if server_id == "main" else scout_client

        multi_server_manager.docker_client.get_client = Mock(side_effect=get_client)

        # Mock containers as not found (no crash)
        import docker.errors

        main_client.containers.get = Mock(side_effect=docker.errors.NotFound("Not found"))
        scout_client.containers.get = Mock(side_effect=docker.errors.NotFound("Not found"))

        # Run recovery
        await multi_server_manager._recover_crashed_containers()

        # Verify both clients were queried
        assert multi_server_manager.docker_client.get_client.call_count >= 2
        multi_server_manager.docker_client.get_client.assert_any_call("main")
        multi_server_manager.docker_client.get_client.assert_any_call("scout")

    @pytest.mark.asyncio
    async def test_crash_recovery_restarts_remote_agent(self, multi_server_manager, temp_dirs):
        """Test that crashed remote agent is restarted via Docker API."""
        # Create compose file
        compose_path = temp_dirs["agents"] / "crashed-scout" / "docker-compose.yml"
        compose_path.parent.mkdir(parents=True, exist_ok=True)
        compose_content = {
            "services": {
                "agent": {
                    "image": "test/agent:latest",
                    "environment": {"KEY": "value"},
                    "ports": ["8001:8001"],
                    "container_name": "ciris-crashed-scout",
                }
            }
        }
        compose_path.write_text(yaml.dump(compose_content))

        # Register crashed agent on scout server
        multi_server_manager.agent_registry.agents = {
            "crashed-scout": Mock(
                agent_id="crashed-scout",
                server_id="scout",
                compose_file=str(compose_path),
                do_not_autostart=False,
            )
        }
        multi_server_manager.agent_registry.list_agents = Mock(
            return_value=list(multi_server_manager.agent_registry.agents.values())
        )

        # Mock crashed container
        mock_container = Mock()
        mock_container.status = "exited"
        mock_container.attrs = {"State": {"ExitCode": 1, "FinishedAt": "2024-01-01T00:00:00Z"}}

        mock_scout_client = Mock()
        # First call returns crashed container, subsequent calls for nginx container fail (triggers Alpine fallback)
        mock_scout_client.containers.get = Mock(
            side_effect=[mock_container] + [Exception("No nginx")] * 10
        )
        mock_scout_client.containers.run = Mock()

        multi_server_manager.docker_client.get_client = Mock(return_value=mock_scout_client)

        # Mock _is_agent_in_deployment to return False
        multi_server_manager._is_agent_in_deployment = AsyncMock(return_value=False)

        await multi_server_manager._recover_crashed_containers()

        # Verify container was restarted via Docker API
        # Will be called multiple times (directory creation + agent container)
        assert mock_scout_client.containers.run.call_count >= 1


class TestRemoteDockerExecution:
    """Tests for remote Docker API execution."""

    @pytest.mark.asyncio
    async def test_start_agent_local_uses_compose(self, multi_server_manager):
        """Test starting local agent uses docker-compose."""
        with patch("asyncio.create_subprocess_exec") as mock_subprocess:
            mock_process = AsyncMock()
            mock_process.communicate = AsyncMock(return_value=(b"", b""))
            mock_process.returncode = 0
            mock_subprocess.return_value = mock_process

            await multi_server_manager._start_agent(
                "test-agent", Path("/path/to/compose.yml"), "main"
            )

            # Verify docker-compose was called
            mock_subprocess.assert_called_once()
            args = mock_subprocess.call_args[0]
            assert "docker-compose" in args

    @pytest.mark.asyncio
    async def test_start_agent_remote_uses_docker_api(self, multi_server_manager, temp_dirs):
        """Test starting remote agent uses Docker API."""
        # Create compose file
        compose_path = temp_dirs["agents"] / "remote-agent" / "docker-compose.yml"
        compose_path.parent.mkdir(parents=True, exist_ok=True)
        compose_content = {
            "services": {
                "agent": {
                    "image": "test/agent:latest",
                    "environment": {"TEST": "value"},
                    "ports": ["8001:8001"],
                    "container_name": "ciris-test",
                    "restart": "unless-stopped",
                }
            }
        }
        compose_path.write_text(yaml.dump(compose_content))

        mock_remote_docker = Mock()
        mock_remote_docker.containers.run = Mock()
        # Mock containers.get to fail so we use Alpine fallback for directory creation
        mock_remote_docker.containers.get = Mock(side_effect=Exception("No nginx container"))
        multi_server_manager.docker_client.get_client = Mock(return_value=mock_remote_docker)

        await multi_server_manager._start_agent("remote-agent", compose_path, "scout")

        # Verify Docker API was called multiple times (directory creation + agent container)
        # The exact count depends on whether volumes are in compose file
        assert mock_remote_docker.containers.run.call_count >= 1

        # Verify the last call is for the agent container
        last_call = mock_remote_docker.containers.run.call_args_list[-1]
        call_kwargs = last_call[1]

        assert call_kwargs["image"] == "test/agent:latest"
        assert call_kwargs["name"] == "ciris-test"
        assert call_kwargs["detach"] is True
        assert call_kwargs["restart_policy"]["Name"] == "unless-stopped"
