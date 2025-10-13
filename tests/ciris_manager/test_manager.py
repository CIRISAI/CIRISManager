"""
Unit tests for CIRISManager main class.
"""

import pytest
import tempfile
import asyncio
import json
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from ciris_manager.manager import CIRISManager
from ciris_manager.config.settings import CIRISManagerConfig


class TestCIRISManager:
    """Test cases for CIRISManager."""

    def test_generate_agent_suffix(self):
        """Test agent suffix generation."""
        # Import just what we need to test
        import secrets

        # Copy the implementation to test it in isolation
        SAFE_CHARS = "abcdefghjkmnpqrstuvwxyz23456789"

        def generate_suffix():
            return "".join(secrets.choice(SAFE_CHARS) for _ in range(6))

        # Test multiple suffixes
        suffixes = set()
        for _ in range(100):
            suffix = generate_suffix()

            # Check length
            assert len(suffix) == 6

            # Check all characters are from SAFE_CHARS
            assert all(c in SAFE_CHARS for c in suffix)

            # Check no confusing characters
            assert "0" not in suffix
            assert "O" not in suffix
            assert "I" not in suffix
            assert "l" not in suffix
            assert "1" not in suffix

            suffixes.add(suffix)

        # Check reasonable uniqueness (should get at least 90 unique in 100 tries)
        assert len(suffixes) >= 90

    def test_manager_generate_agent_suffix(self, manager):
        """Test the actual manager's suffix generation method."""
        # Generate multiple suffixes using the manager's method
        suffixes = set()
        for _ in range(100):
            suffix = manager._generate_agent_suffix()

            # Check length
            assert len(suffix) == 6

            # Check all characters are from SAFE_CHARS
            assert all(c in manager.SAFE_CHARS for c in suffix)

            # Check no confusing characters
            assert "0" not in suffix
            assert "O" not in suffix
            assert "I" not in suffix
            assert "l" not in suffix
            assert "1" not in suffix

            suffixes.add(suffix)

        # With cryptographically secure random, we should get very high uniqueness
        assert len(suffixes) >= 95  # Even higher expectation with secrets module

    @pytest.fixture
    def temp_dirs(self):
        """Create temporary directories for testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            base_path = Path(temp_dir)
            agents_dir = base_path / "agents"
            agents_dir.mkdir()

            # Create pre-approved manifest
            manifest = {
                "version": "1.0",
                "templates": {
                    "scout": {"checksum": "sha256:test_checksum", "description": "Scout template"}
                },
                "root_signature": "test_signature",
                "root_public_key": "test_key",
            }

            manifest_path = base_path / "pre-approved-templates.json"
            with open(manifest_path, "w") as f:
                json.dump(manifest, f)

            # Create template directory
            templates_dir = base_path / "templates"
            templates_dir.mkdir()

            # Create test templates
            scout_template = templates_dir / "scout.yaml"
            with open(scout_template, "w") as f:
                f.write("name: scout\ntype: test\n")

            # Create custom template for testing
            custom_template = templates_dir / "custom.yaml"
            with open(custom_template, "w") as f:
                f.write("name: custom\ntype: test\n")

            yield {
                "base": base_path,
                "agents": agents_dir,
                "manifest": manifest_path,
                "templates": templates_dir,
            }

    @pytest.fixture
    def config(self, temp_dirs):
        """Create test configuration."""
        # Create nginx config dir in temp directory
        nginx_config_dir = temp_dirs["base"] / "nginx"
        nginx_config_dir.mkdir(exist_ok=True)

        from ciris_manager.config.settings import ServerConfig

        return CIRISManagerConfig(
            manager={
                "agents_directory": str(temp_dirs["agents"]),
                "templates_directory": str(temp_dirs["templates"]),
                "manifest_path": str(temp_dirs["manifest"]),
                "port": 8888,
                "host": "127.0.0.1",
            },
            docker={"registry": "test.registry", "image": "test-image:latest"},
            ports={"start": 8080, "end": 8090, "reserved": [8888]},
            nginx={"config_dir": str(nginx_config_dir), "container_name": "test-nginx"},
            servers=[
                ServerConfig(
                    server_id="main",
                    hostname="agents.ciris.ai",
                    is_local=True,
                )
            ],
        )

    @pytest.fixture
    def manager(self, config):
        """Create CIRISManager instance."""
        with patch(
            "ciris_manager.template_verifier.TemplateVerifier._verify_manifest_signature",
            return_value=True,
        ):
            with patch("ciris_manager.nginx_manager.NginxManager") as mock_nginx_class:
                with patch(
                    "ciris_manager.multi_server_docker.MultiServerDockerClient"
                ) as mock_docker_class:
                    with patch("ciris_manager.manager.DockerImageCleanup") as mock_cleanup_class:
                        # Configure nginx manager mock
                        mock_nginx = Mock()
                        mock_nginx.ensure_managed_sections = Mock(return_value=True)
                        mock_nginx.add_agent_route = Mock(return_value=True)
                        mock_nginx.remove_agent_route = Mock(return_value=True)
                        mock_nginx.reload_nginx = Mock(return_value=True)
                        mock_nginx_class.return_value = mock_nginx

                        # Configure multi-server Docker client mock
                        mock_docker_client = Mock()
                        mock_docker_client.test_connection = Mock(return_value=True)
                        mock_docker_client.get_client = Mock()
                        # Return the server config from the config object
                        mock_docker_client.get_server_config = Mock(return_value=config.servers[0])
                        mock_docker_client.list_servers = Mock(return_value=["main"])
                        mock_docker_class.return_value = mock_docker_client

                        # Configure image cleanup mock
                        mock_cleanup = Mock()
                        mock_cleanup.run_periodic_cleanup = AsyncMock()
                        mock_cleanup_class.return_value = mock_cleanup

                        manager = CIRISManager(config)
                        manager.nginx_manager = mock_nginx
                        manager.docker_client = mock_docker_client
                        return manager

    def test_initialization(self, manager, config):
        """Test CIRISManager initialization."""
        assert manager.config == config
        assert manager.agents_dir.exists()
        assert manager.port_manager is not None
        assert manager.template_verifier is not None
        assert manager.agent_registry is not None
        assert manager.compose_generator is not None
        assert manager.watchdog is not None
        assert not manager._running

    def test_scan_existing_agents(self, temp_dirs, config):
        """Test scanning existing agents on startup."""
        # Create agent directory with compose file
        agent_dir = temp_dirs["agents"] / "scout"
        agent_dir.mkdir()

        compose_path = agent_dir / "docker-compose.yml"
        with open(compose_path, "w") as f:
            f.write("version: '3.8'\nservices:\n  agent-scout:\n    image: test\n")

        # Create metadata
        metadata = {
            "version": "1.0",
            "agents": {
                "agent-scout": {
                    "name": "Scout",
                    "port": 8081,
                    "template": "scout",
                    "compose_file": str(compose_path),
                    "created_at": "2025-01-21T10:00:00Z",
                }
            },
        }

        metadata_path = temp_dirs["agents"] / "metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f)

        # Create manager - should scan on init
        with patch(
            "ciris_manager.template_verifier.TemplateVerifier._verify_manifest_signature",
            return_value=True,
        ):
            with patch("ciris_manager.multi_server_docker.MultiServerDockerClient"):
                with patch("ciris_manager.nginx_manager.NginxManager"):
                    with patch("ciris_manager.manager.DockerImageCleanup"):
                        manager = CIRISManager(config)

        # Verify agent was found
        agent = manager.agent_registry.get_agent("agent-scout")
        assert agent is not None
        assert agent.name == "Scout"
        assert agent.port == 8081

    @pytest.mark.asyncio
    async def test_create_agent_pre_approved(self, manager):
        """Test creating agent with pre-approved template."""
        # Set required environment variables for encryption
        import os

        os.environ["MANAGER_JWT_SECRET"] = "test-secret-key-for-testing-only"
        os.environ["CIRIS_ENCRYPTION_SALT"] = "test-salt-sixteen-chars"

        # Mock template verifier
        manager.template_verifier.is_pre_approved = AsyncMock(return_value=True)

        # Mock subprocess for docker-compose
        with patch("asyncio.create_subprocess_exec") as mock_subprocess:
            mock_process = AsyncMock()
            mock_process.returncode = 0
            mock_process.communicate = AsyncMock(return_value=(b"", b""))
            mock_subprocess.return_value = mock_process

            # Also mock subprocess.run for sudo chown
            with patch("subprocess.run"):
                # Create agent
                result = await manager.create_agent(
                    template="scout", name="Scout", environment={"CUSTOM": "value"}
                )

        # Verify result - agent_id now includes a 6-char suffix
        assert result["agent_id"].startswith("scout-")
        assert len(result["agent_id"].split("-")[-1]) == 6  # 6-char suffix
        assert result["container"] == f"ciris-{result['agent_id']}"
        assert result["port"] == 8080  # First available
        assert result["status"] == "starting"

        # Verify agent registered
        agent = manager.agent_registry.get_agent(result["agent_id"])
        assert agent is not None
        assert agent.name == "Scout"

        # Verify docker-compose called
        mock_subprocess.assert_called()
        call_args = mock_subprocess.call_args[0]
        assert call_args[0] == "docker-compose"
        assert call_args[1] == "-f"
        # Path now includes the full agent ID with suffix
        assert f"{result['agent_id']}/docker-compose.yml" in call_args[2]
        assert call_args[3] == "up"
        assert call_args[4] == "-d"

    @pytest.mark.asyncio
    async def test_create_agent_custom_template_no_signature(self, manager):
        """Test creating agent with custom template without signature."""
        # Mock template verifier
        manager.template_verifier.is_pre_approved = AsyncMock(return_value=False)

        # Should raise permission error
        with pytest.raises(PermissionError, match="WA signature required"):
            await manager.create_agent(template="custom", name="Custom")

    @pytest.mark.asyncio
    async def test_create_agent_custom_template_with_signature(self, manager):
        """Test creating agent with custom template and signature."""
        # Mock template verifier
        manager.template_verifier.is_pre_approved = AsyncMock(return_value=False)

        # Mock subprocess
        with patch("asyncio.create_subprocess_exec") as mock_subprocess:
            mock_process = AsyncMock()
            mock_process.returncode = 0
            mock_process.communicate = AsyncMock(return_value=(b"", b""))
            mock_subprocess.return_value = mock_process

            # Also mock subprocess.run for sudo chown
            with patch("subprocess.run"):
                # Create agent with signature
                result = await manager.create_agent(
                    template="custom", name="Custom", wa_signature="test_signature"
                )

        # Should succeed - agent_id now includes a 6-char suffix
        assert result["agent_id"].startswith("custom-")
        assert len(result["agent_id"].split("-")[-1]) == 6
        assert result["status"] == "starting"

    @pytest.mark.asyncio
    async def test_create_agent_with_billing_enabled(self, manager):
        """Test creating agent with billing enabled."""
        # Set required environment variables for encryption
        import os

        os.environ["MANAGER_JWT_SECRET"] = "test-secret-key-for-testing-only"
        os.environ["CIRIS_ENCRYPTION_SALT"] = "test-salt-sixteen-chars"

        # Mock template verifier
        manager.template_verifier.is_pre_approved = AsyncMock(return_value=True)

        # Mock subprocess for docker-compose
        with patch("asyncio.create_subprocess_exec") as mock_subprocess:
            mock_process = AsyncMock()
            mock_process.returncode = 0
            mock_process.communicate = AsyncMock(return_value=(b"", b""))
            mock_subprocess.return_value = mock_process

            # Also mock subprocess.run for sudo chown
            with patch("subprocess.run"):
                # Create agent with billing enabled
                result = await manager.create_agent(
                    template="scout",
                    name="Scout",
                    billing_enabled=True,
                    billing_api_key="test-billing-key-abc123",
                )

        # Verify result
        assert result["agent_id"].startswith("scout-")
        assert result["status"] == "starting"

        # Verify agent registered
        agent = manager.agent_registry.get_agent(result["agent_id"])
        assert agent is not None

        # Verify compose file was created with billing environment variables
        compose_file = Path(agent.compose_file)
        assert compose_file.exists()

        # Read and verify compose file content
        import yaml

        with open(compose_file) as f:
            compose_config = yaml.safe_load(f)

        env = compose_config["services"][result["agent_id"]]["environment"]
        assert env["CIRIS_BILLING_ENABLED"] == "true"
        assert env["CIRIS_BILLING_API_KEY"] == "test-billing-key-abc123"

    @pytest.mark.asyncio
    async def test_create_agent_with_billing_disabled(self, manager):
        """Test creating agent with billing disabled (default)."""
        # Set required environment variables for encryption
        import os

        os.environ["MANAGER_JWT_SECRET"] = "test-secret-key-for-testing-only"
        os.environ["CIRIS_ENCRYPTION_SALT"] = "test-salt-sixteen-chars"

        # Mock template verifier
        manager.template_verifier.is_pre_approved = AsyncMock(return_value=True)

        # Mock subprocess for docker-compose
        with patch("asyncio.create_subprocess_exec") as mock_subprocess:
            mock_process = AsyncMock()
            mock_process.returncode = 0
            mock_process.communicate = AsyncMock(return_value=(b"", b""))
            mock_subprocess.return_value = mock_process

            # Also mock subprocess.run for sudo chown
            with patch("subprocess.run"):
                # Create agent with billing explicitly disabled
                result = await manager.create_agent(
                    template="scout", name="Scout", billing_enabled=False
                )

        # Verify compose file was created with billing disabled
        agent = manager.agent_registry.get_agent(result["agent_id"])
        compose_file = Path(agent.compose_file)

        import yaml

        with open(compose_file) as f:
            compose_config = yaml.safe_load(f)

        env = compose_config["services"][result["agent_id"]]["environment"]
        assert env["CIRIS_BILLING_ENABLED"] == "false"
        assert "CIRIS_BILLING_API_KEY" not in env

    @pytest.mark.asyncio
    async def test_create_agent_template_not_found(self, manager):
        """Test creating agent with non-existent template."""
        # Should raise ValueError
        with pytest.raises(ValueError, match="Template not found"):
            await manager.create_agent(template="nonexistent", name="Test")

    @pytest.mark.asyncio
    async def test_create_agent_docker_failure(self, manager):
        """Test handling docker-compose failure."""
        # Mock template verifier
        manager.template_verifier.is_pre_approved = AsyncMock(return_value=True)

        # Mock subprocess to fail
        with patch("asyncio.create_subprocess_exec") as mock_subprocess:
            mock_process = AsyncMock()
            mock_process.returncode = 1
            mock_process.communicate = AsyncMock(return_value=(b"", b"Error: failed"))
            mock_subprocess.return_value = mock_process

            # Also mock subprocess.run for sudo chown
            with patch("subprocess.run"):
                # Should raise RuntimeError
                with pytest.raises(RuntimeError, match="Failed to start"):
                    await manager.create_agent(template="scout", name="Scout")

    @pytest.mark.asyncio
    async def test_container_management_loop(self, manager):
        """Test container management loop."""
        # Create compose file that exists
        scout_dir = manager.agents_dir / "scout"
        scout_dir.mkdir(exist_ok=True)
        compose_file = scout_dir / "docker-compose.yml"
        with open(compose_file, "w") as f:
            f.write("version: '3.8'\nservices:\n  scout:\n    image: test\n")

        # Register agent with existing compose file
        manager.agent_registry.register_agent(
            agent_id="agent-scout",
            name="Scout",
            port=8081,
            template="scout",
            compose_file=str(compose_file),
        )

        # Mock _recover_crashed_containers to avoid slow operations
        with patch.object(
            manager, "_recover_crashed_containers", new_callable=AsyncMock
        ) as mock_recover:
            # Reduce interval for faster testing
            manager.config.container_management.interval = 0.05

            # Start loop
            manager._running = True
            loop_task = asyncio.create_task(manager.container_management_loop())

            # Let it run for at least one iteration
            await asyncio.sleep(0.2)

            # Stop
            manager._running = False

            # Cancel task
            loop_task.cancel()
            try:
                await loop_task
            except asyncio.CancelledError:
                pass

            # Verify recovery was called
            assert mock_recover.called

    @pytest.mark.asyncio
    async def test_start_stop(self, manager):
        """Test starting and stopping manager."""
        # Mock all background tasks to prevent them from running
        with patch.object(manager, "_start_api_server", new_callable=AsyncMock):
            with patch.object(manager, "container_management_loop", new_callable=AsyncMock):
                with patch.object(manager.watchdog, "start", new_callable=AsyncMock):
                    with patch.object(manager.watchdog, "stop", new_callable=AsyncMock):
                        with patch.object(
                            manager.image_cleanup, "run_periodic_cleanup", new_callable=AsyncMock
                        ):
                            # Start
                            await manager.start()
                            assert manager._running

                            # Stop
                            await manager.stop()
                            assert not manager._running
                            assert manager._shutdown_event.is_set()

    def test_get_status(self, manager):
        """Test getting manager status."""
        status = manager.get_status()

        assert not status["running"]
        assert "config" in status
        assert "watchdog_status" in status
        assert "components" in status

        # Start and check again
        manager._running = True
        status = manager.get_status()
        assert status["running"]

    @pytest.mark.asyncio
    async def test_port_allocation_persistence(self, manager):
        """Test port allocation persists across restarts."""
        # Mock template and subprocess
        manager.template_verifier.is_pre_approved = AsyncMock(return_value=True)

        with patch("asyncio.create_subprocess_exec") as mock_subprocess:
            mock_process = AsyncMock()
            mock_process.returncode = 0
            mock_process.communicate = AsyncMock(return_value=(b"", b""))
            mock_subprocess.return_value = mock_process

            # Also mock subprocess.run for sudo chown
            with patch("subprocess.run"):
                # Create agents
                result1 = await manager.create_agent("scout", "Scout1")
                result2 = await manager.create_agent("scout", "Scout2")

        assert result1["port"] == 8080
        assert result2["port"] == 8081

        # Store the actual agent IDs
        agent_id1 = result1["agent_id"]
        agent_id2 = result2["agent_id"]

        # Create new manager instance
        with patch(
            "ciris_manager.template_verifier.TemplateVerifier._verify_manifest_signature",
            return_value=True,
        ):
            with patch("ciris_manager.multi_server_docker.MultiServerDockerClient"):
                with patch("ciris_manager.nginx_manager.NginxManager"):
                    with patch("ciris_manager.manager.DockerImageCleanup"):
                        manager2 = CIRISManager(manager.config)

        # Ports should still be allocated to the actual agent IDs
        assert manager2.port_manager.get_port(agent_id1) == 8080
        assert manager2.port_manager.get_port(agent_id2) == 8081

    @pytest.mark.asyncio
    async def test_concurrent_agent_creation(self, manager):
        """Test concurrent agent creation."""
        # Mock template and subprocess
        manager.template_verifier.is_pre_approved = AsyncMock(return_value=True)

        async def mock_subprocess(*args, **kwargs):
            mock_process = AsyncMock()
            mock_process.returncode = 0
            mock_process.communicate = AsyncMock(return_value=(b"", b""))
            return mock_process

        with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess):
            # Also mock subprocess.run for sudo chown
            with patch("subprocess.run"):
                # Create multiple agents concurrently
                tasks = []
                for i in range(5):
                    task = asyncio.create_task(manager.create_agent("scout", f"Scout{i}"))
                    tasks.append(task)

                results = await asyncio.gather(*tasks)

        # All should succeed with unique ports
        ports = [r["port"] for r in results]
        assert len(set(ports)) == 5  # All unique
        assert all(8080 <= p <= 8090 for p in ports)

    @pytest.mark.asyncio
    async def test_delete_agent_success(self, manager, temp_dirs):
        """Test successful agent deletion."""
        # First create an agent
        manager.template_verifier.is_pre_approved = Mock(return_value=True)

        # Create agent directory and compose file
        agent_id = "test-abc123"
        agent_dir = temp_dirs["agents"] / agent_id
        agent_dir.mkdir()
        compose_file = agent_dir / "docker-compose.yml"
        compose_file.write_text("version: '3.8'\n")

        # Register the agent
        manager.agent_registry.register_agent(
            agent_id=agent_id,
            name="Test Agent",
            port=8080,
            template="test",
            compose_file=str(compose_file),
        )
        manager.port_manager.allocate_port(agent_id)

        # Mock subprocess and docker discovery
        async def mock_subprocess(*args, **kwargs):
            mock_process = AsyncMock()
            mock_process.returncode = 0
            mock_process.communicate = AsyncMock(return_value=(b"", b""))
            return mock_process

        with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess):
            with patch(
                "ciris_manager.docker_discovery.DockerAgentDiscovery"
            ) as mock_discovery_class:
                mock_discovery = Mock()
                mock_discovery.discover_agents = Mock(return_value=[])
                mock_discovery_class.return_value = mock_discovery

                # Delete the agent
                result = await manager.delete_agent(agent_id)

        # Verify deletion
        assert result is True
        assert manager.agent_registry.get_agent(agent_id) is None
        assert manager.port_manager.is_port_available(8080)  # Port should be freed
        assert not compose_file.exists()  # Compose file should be deleted

    @pytest.mark.asyncio
    async def test_delete_agent_not_found(self, manager):
        """Test deleting non-existent agent."""
        result = await manager.delete_agent("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_agent_error_handling(self, manager, temp_dirs):
        """Test delete agent with subprocess error."""
        # Create and register an agent
        agent_id = "test-error"
        agent_dir = temp_dirs["agents"] / agent_id
        agent_dir.mkdir()
        compose_file = agent_dir / "docker-compose.yml"
        compose_file.write_text("version: '3.8'\n")

        manager.agent_registry.register_agent(
            agent_id=agent_id,
            name="Test Agent",
            port=8080,
            template="test",
            compose_file=str(compose_file),
        )

        # Mock subprocess to raise an error
        with patch("asyncio.create_subprocess_exec", side_effect=Exception("Docker error")):
            result = await manager.delete_agent(agent_id)

        # Should return False on error
        assert result is False

    @pytest.mark.asyncio
    async def test_crash_recovery_non_zero_exit(self, manager, tmp_path):
        """Test that containers with non-zero exit codes are restarted."""
        # Create a temporary compose file
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text("version: '3.8'\n")

        # Register test agents
        manager.agent_registry.register_agent(
            agent_id="crashed-agent",
            name="Crashed Agent",
            port=8080,
            template="test",
            compose_file=str(compose_file),
        )

        # Mock Docker client for multi-server support
        mock_client = MagicMock()
        mock_container = MagicMock()

        # Container has crashed (non-zero exit code)
        mock_container.status = "exited"
        mock_container.attrs = {"State": {"ExitCode": 1}}  # Non-zero = crash

        mock_client.containers.get.return_value = mock_container

        # Configure manager's docker_client to return our mock
        manager.docker_client.get_client = Mock(return_value=mock_client)

        # Mock subprocess for docker-compose restart
        with patch("asyncio.create_subprocess_exec") as mock_subprocess:
            mock_process = AsyncMock()
            mock_process.returncode = 0
            mock_process.communicate = AsyncMock(return_value=(b"Container restarted", b""))
            mock_subprocess.return_value = mock_process

            # Also mock docker.from_env for _is_agent_in_deployment check
            with patch("docker.from_env", return_value=mock_client):
                # Run recovery
                await manager._recover_crashed_containers()

                # Verify docker-compose was called to restart
                mock_subprocess.assert_called_once()
                call_args = mock_subprocess.call_args[0]
                assert "docker-compose" in call_args
                assert "up" in call_args
                assert "-d" in call_args

    @pytest.mark.asyncio
    async def test_crash_recovery_zero_exit_not_restarted(self, manager, tmp_path):
        """Test that containers with exit code 0 (consensual shutdown) are NOT restarted."""
        # Create a temporary compose file
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text("version: '3.8'\n")

        # Register test agent
        manager.agent_registry.register_agent(
            agent_id="shutdown-agent",
            name="Shutdown Agent",
            port=8081,
            template="test",
            compose_file=str(compose_file),
        )

        # Mock Docker client
        with patch("docker.from_env") as mock_docker:
            mock_client = MagicMock()
            mock_container = MagicMock()

            # Container exited cleanly (exit code 0)
            mock_container.status = "exited"
            mock_container.attrs = {"State": {"ExitCode": 0}}  # Zero = consensual shutdown

            mock_client.containers.get.return_value = mock_container
            mock_docker.return_value = mock_client

            # Mock subprocess
            with patch("asyncio.create_subprocess_exec") as mock_subprocess:
                # Run recovery
                await manager._recover_crashed_containers()

                # Verify docker-compose was NOT called
                mock_subprocess.assert_not_called()

    @pytest.mark.asyncio
    async def test_crash_recovery_running_containers_ignored(self, manager, tmp_path):
        """Test that running containers are never touched (maintains autonomy)."""
        # Create a temporary compose file
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text("version: '3.8'\n")

        # Register test agent
        manager.agent_registry.register_agent(
            agent_id="running-agent",
            name="Running Agent",
            port=8082,
            template="test",
            compose_file=str(compose_file),
        )

        # Mock Docker client
        with patch("docker.from_env") as mock_docker:
            mock_client = MagicMock()
            mock_container = MagicMock()

            # Container is running
            mock_container.status = "running"

            mock_client.containers.get.return_value = mock_container
            mock_docker.return_value = mock_client

            # Mock subprocess
            with patch("asyncio.create_subprocess_exec") as mock_subprocess:
                # Run recovery
                await manager._recover_crashed_containers()

                # Verify docker-compose was NOT called (never touch running containers)
                mock_subprocess.assert_not_called()

    @pytest.mark.asyncio
    async def test_crash_recovery_recent_stop_ignored(self, manager, tmp_path):
        """Test that recently stopped containers (potential deployment) are not restarted."""
        # Create a temporary compose file
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text("version: '3.8'\n")

        # Register test agent
        manager.agent_registry.register_agent(
            agent_id="recent-stop",
            name="Recent Stop",
            port=8083,
            template="test",
            compose_file=str(compose_file),
        )

        # Mock Docker client for _is_agent_in_deployment check
        with patch("docker.from_env") as mock_docker:
            mock_client = MagicMock()
            mock_container = MagicMock()

            # Container crashed but very recently (might be deployment)
            mock_container.status = "exited"
            mock_container.attrs = {
                "State": {
                    "ExitCode": 1,
                    "FinishedAt": "2024-01-01T12:00:00.000000000Z",  # Recent timestamp
                }
            }

            mock_client.containers.get.return_value = mock_container
            mock_docker.return_value = mock_client

            # Mock time to make it look like container just stopped
            with patch("ciris_manager.manager.datetime") as mock_datetime:
                from datetime import datetime, timezone

                mock_datetime.now.return_value = datetime(
                    2024, 1, 1, 12, 0, 30, tzinfo=timezone.utc
                )
                mock_datetime.timezone = timezone

                # Mock dateutil.parser
                with patch("ciris_manager.manager.dateutil.parser.parse") as mock_parse:
                    mock_parse.return_value = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

                    # Mock subprocess
                    with patch("asyncio.create_subprocess_exec") as mock_subprocess:
                        # Run recovery
                        await manager._recover_crashed_containers()

                        # Should not restart (too recent, might be deployment)
                        mock_subprocess.assert_not_called()

    @pytest.mark.asyncio
    async def test_crash_recovery_old_crash_restarted(self, manager, tmp_path):
        """Test that old crashed containers (not deployment) are restarted."""
        # Create a temporary compose file
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text("version: '3.8'\n")

        # Register test agent
        manager.agent_registry.register_agent(
            agent_id="old-crash",
            name="Old Crash",
            port=8084,
            template="test",
            compose_file=str(compose_file),
        )

        # Mock Docker client for multi-server support
        mock_client = MagicMock()
        mock_container = MagicMock()

        # Container crashed a while ago (not deployment)
        mock_container.status = "exited"
        mock_container.attrs = {
            "State": {
                "ExitCode": 1,
                "FinishedAt": "2024-01-01T11:00:00.000000000Z",  # Old timestamp
            }
        }

        # First call for main check, second for deployment check
        mock_client.containers.get.return_value = mock_container

        # Configure manager's docker_client to return our mock
        manager.docker_client.get_client = Mock(return_value=mock_client)

        # Mock time to show crash was > 5 minutes ago
        with patch("ciris_manager.manager.datetime") as mock_datetime:
            from datetime import datetime, timezone

            mock_datetime.now.return_value = datetime(2024, 1, 1, 12, 10, 0, tzinfo=timezone.utc)
            mock_datetime.timezone = timezone

            # Mock dateutil.parser
            with patch("ciris_manager.manager.dateutil.parser.parse") as mock_parse:
                mock_parse.return_value = datetime(2024, 1, 1, 11, 0, 0, tzinfo=timezone.utc)

                # Mock subprocess for restart
                with patch("asyncio.create_subprocess_exec") as mock_subprocess:
                    mock_process = AsyncMock()
                    mock_process.returncode = 0
                    mock_process.communicate = AsyncMock(return_value=(b"Restarted", b""))
                    mock_subprocess.return_value = mock_process

                    # Also mock docker.from_env for _is_agent_in_deployment check
                    with patch("docker.from_env", return_value=mock_client):
                        # Run recovery
                        await manager._recover_crashed_containers()

                        # Should restart (old crash, not deployment)
                        mock_subprocess.assert_called_once()

    @pytest.mark.asyncio
    async def test_crash_recovery_docker_error_handled(self, manager, tmp_path):
        """Test that Docker errors are handled gracefully in crash recovery."""
        # Create a temporary compose file
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text("version: '3.8'\n")

        # Register test agent
        manager.agent_registry.register_agent(
            agent_id="error-agent",
            name="Error Agent",
            port=8085,
            template="test",
            compose_file=str(compose_file),
        )

        # Mock Docker client to raise an error
        with patch("docker.from_env") as mock_docker:
            mock_docker.side_effect = Exception("Docker daemon not accessible")

            # Run recovery - should not crash
            await manager._recover_crashed_containers()  # Should complete without exception

    @pytest.mark.asyncio
    async def test_container_management_loop_crash_recovery(self, manager):
        """Test that container management loop calls crash recovery."""
        manager._running = True

        # Reduce interval for faster testing
        manager.config.container_management.interval = 0.01

        # Mock the recovery method
        manager._recover_crashed_containers = AsyncMock()

        # Run the loop for a short time
        loop_task = asyncio.create_task(manager.container_management_loop())

        # Let it run for one iteration
        await asyncio.sleep(0.05)

        # Stop the loop
        manager._running = False
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

        # Verify recovery was called
        manager._recover_crashed_containers.assert_called()
