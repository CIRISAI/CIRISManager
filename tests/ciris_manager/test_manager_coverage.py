"""
Additional tests for CIRISManager to improve coverage.
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from pathlib import Path
from ciris_manager.manager import CIRISManager, main
from ciris_manager.config.settings import CIRISManagerConfig


class TestManagerCoverage:
    """Additional test cases for manager coverage."""

    @pytest.mark.asyncio
    async def test_main_entry_point(self):
        """Test main entry point."""
        with patch("ciris_manager.manager.logging.basicConfig"):
            with patch("ciris_manager.manager.CIRISManagerConfig.from_file") as mock_from_file:
                mock_config = Mock()
                mock_from_file.return_value = mock_config

                with patch("ciris_manager.manager.CIRISManager") as mock_manager_class:
                    mock_manager = AsyncMock()
                    mock_manager.run = AsyncMock()
                    mock_manager_class.return_value = mock_manager

                    with patch("ciris_manager.manager.asyncio.run"):
                        # Call main through asyncio
                        await main()

                        # Verify manager was created and run
                        mock_manager_class.assert_called_once_with(mock_config)
                        mock_manager.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_nginx_route(
        self, multi_server_config, mock_docker_client, mock_nginx_managers, mock_agent_discovery
    ):
        """Test nginx route addition with multi-server nginx."""
        mock_discovery_class, mock_discovery = mock_agent_discovery

        # Configure discovery to return a test agent
        mock_agent_main = Mock()
        mock_agent_main.agent_id = "test-agent"
        mock_agent_main.agent_name = "Test Agent"
        mock_agent_main.api_port = 8081
        mock_agent_main.has_port = True
        mock_discovery.discover_agents = Mock(return_value=[mock_agent_main])

        with (
            patch("subprocess.run", return_value=Mock(returncode=0, stderr=b"", stdout=b"")),
            patch("ciris_manager.manager.MultiServerDockerClient", return_value=mock_docker_client),
            patch("ciris_manager.manager.DockerImageCleanup"),
            patch("ciris_manager.docker_discovery.DockerAgentDiscovery", mock_discovery_class),
            patch("ciris_manager.nginx_manager.NginxManager") as mock_nginx_class,
        ):
            # Configure NginxManager to return our mocks based on hostname
            def nginx_side_effect(*args, **kwargs):
                hostname = kwargs.get("hostname", "")
                if "scout" in hostname:
                    return mock_nginx_managers["scout"]
                return mock_nginx_managers["main"]

            mock_nginx_class.side_effect = nginx_side_effect

            # Create manager
            manager = CIRISManager(multi_server_config)

            # Replace nginx_managers with our mocks so we can verify calls
            manager.nginx_managers = mock_nginx_managers
            manager.nginx_manager = mock_nginx_managers["main"]  # backward compatibility

            # Mock agent registry to return server_id
            mock_agent_info = Mock()
            mock_agent_info.server_id = "main"
            manager.agent_registry.get_agent = Mock(return_value=mock_agent_info)

            # Test nginx route addition - call update_nginx_config directly
            result = await manager.update_nginx_config()

            # Verify it succeeded
            assert result is True

            # Should have created nginx managers for both servers
            assert "main" in manager.nginx_managers
            assert "scout" in manager.nginx_managers

            # Verify the mocks were called appropriately
            # Main server (local) should use update_config
            mock_nginx_managers["main"].update_config.assert_called_once()
            # Scout server (remote) should use generate_config + deploy_remote_config
            mock_nginx_managers["scout"].generate_config.assert_called_once()
            mock_nginx_managers["scout"].deploy_remote_config.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_nginx_config_error_handling(self, tmp_path):
        """Test nginx config update error handling with multi-server."""
        nginx_dir = tmp_path / "nginx"
        nginx_dir.mkdir()

        config = CIRISManagerConfig(
            manager={"agents_directory": str(tmp_path / "agents")},
            nginx={"config_dir": str(nginx_dir), "enabled": True},
            servers=[
                {"server_id": "main", "hostname": "agents.ciris.ai", "is_local": True},
            ],
        )

        with patch("ciris_manager.nginx_manager.NginxManager") as mock_nginx_class:
            # Configure nginx manager mock to raise error
            mock_nginx = Mock()
            mock_nginx.update_config = Mock(side_effect=Exception("Config error"))
            mock_nginx_class.return_value = mock_nginx

            with patch("ciris_manager.docker_discovery.DockerAgentDiscovery"):
                with patch("ciris_manager.manager.DockerImageCleanup"):
                    manager = CIRISManager(config)

                    # Should catch exception and return False
                    result = await manager.update_nginx_config()
                    assert result is False

    @pytest.mark.asyncio
    async def test_add_nginx_route_failure(self, tmp_path):
        """Test nginx route addition failure with multi-server."""
        nginx_dir = tmp_path / "nginx"
        nginx_dir.mkdir()

        config = CIRISManagerConfig(
            manager={"agents_directory": str(tmp_path / "agents")},
            nginx={"config_dir": str(nginx_dir), "enabled": True},
            servers=[
                {"server_id": "main", "hostname": "agents.ciris.ai", "is_local": True},
            ],
        )

        with patch("ciris_manager.nginx_manager.NginxManager") as mock_nginx_class:
            # Configure nginx manager mock to return False
            mock_nginx = Mock()
            mock_nginx.update_config = Mock(return_value=False)
            mock_nginx_class.return_value = mock_nginx

            with patch(
                "ciris_manager.docker_discovery.DockerAgentDiscovery"
            ) as mock_discovery_class:
                with patch("ciris_manager.manager.DockerImageCleanup"):
                    mock_discovery = Mock()
                    mock_discovery.discover_agents = Mock(return_value=[])
                    mock_discovery_class.return_value = mock_discovery

                    manager = CIRISManager(config)

                    # Should raise RuntimeError when update fails
                    with pytest.raises(RuntimeError, match="Failed to update nginx configuration"):
                        await manager._add_nginx_route("scout", 8081)

    @pytest.mark.asyncio
    async def test_multi_server_nginx_deployment(
        self, multi_server_config, mock_docker_client, mock_nginx_managers, mock_agent_discovery
    ):
        """Test nginx configuration deployment across multiple servers."""
        mock_discovery_class, mock_discovery = mock_agent_discovery

        # Mock discovery to return agents on both servers
        mock_main_agent = Mock()
        mock_main_agent.agent_id = "main-agent"
        mock_main_agent.agent_name = "Main Agent"
        mock_main_agent.api_port = 8080
        mock_main_agent.has_port = True

        mock_scout_agent = Mock()
        mock_scout_agent.agent_id = "scout-agent"
        mock_scout_agent.agent_name = "Scout Agent"
        mock_scout_agent.api_port = 8000
        mock_scout_agent.has_port = True

        mock_discovery.discover_agents = Mock(return_value=[mock_main_agent, mock_scout_agent])

        with (
            patch("subprocess.run", return_value=Mock(returncode=0, stderr=b"", stdout=b"")),
            patch("ciris_manager.manager.MultiServerDockerClient", return_value=mock_docker_client),
            patch("ciris_manager.manager.DockerImageCleanup"),
            patch("ciris_manager.docker_discovery.DockerAgentDiscovery", mock_discovery_class),
            patch("ciris_manager.nginx_manager.NginxManager") as mock_nginx_class,
        ):
            # Configure NginxManager to return our mocks based on hostname
            def nginx_side_effect(*args, **kwargs):
                hostname = kwargs.get("hostname", "")
                if "scout" in hostname:
                    return mock_nginx_managers["scout"]
                return mock_nginx_managers["main"]

            mock_nginx_class.side_effect = nginx_side_effect

            # Create manager
            manager = CIRISManager(multi_server_config)

            # Replace nginx_managers with our mocks so we can verify calls
            manager.nginx_managers = mock_nginx_managers
            manager.nginx_manager = mock_nginx_managers["main"]  # backward compatibility

            # Mock agent registry to return appropriate server_ids
            def get_agent_info(agent_id):
                if agent_id == "main-agent":
                    info = Mock()
                    info.server_id = "main"
                    return info
                elif agent_id == "scout-agent":
                    info = Mock()
                    info.server_id = "scout"
                    return info
                return None

            manager.agent_registry.get_agent = Mock(side_effect=get_agent_info)

            # Update nginx config across all servers
            result = await manager.update_nginx_config()

            # Should succeed
            assert result is True

            # Should call update_config on main server (local)
            mock_nginx_managers["main"].update_config.assert_called_once()
            # Verify it was called with only main server agents
            main_call_args = mock_nginx_managers["main"].update_config.call_args[0][0]
            assert len(main_call_args) == 1
            assert main_call_args[0].agent_id == "main-agent"

            # Should call deploy_remote_config on scout server (remote)
            mock_nginx_managers["scout"].generate_config.assert_called_once()
            mock_nginx_managers["scout"].deploy_remote_config.assert_called_once()

            # Verify scout config was called with only scout server agents
            scout_call_args = mock_nginx_managers["scout"].generate_config.call_args[0][0]
            assert len(scout_call_args) == 1
            assert scout_call_args[0].agent_id == "scout-agent"

    @pytest.mark.asyncio
    async def test_multi_server_nginx_remote_deployment_failure(
        self, multi_server_config, mock_docker_client, mock_nginx_managers, mock_agent_discovery
    ):
        """Test handling of remote nginx deployment failure."""
        mock_discovery_class, mock_discovery = mock_agent_discovery

        # Simulate remote deployment failure
        mock_nginx_managers["scout"].deploy_remote_config = Mock(return_value=False)

        with (
            patch("subprocess.run", return_value=Mock(returncode=0, stderr=b"", stdout=b"")),
            patch("ciris_manager.manager.MultiServerDockerClient", return_value=mock_docker_client),
            patch("ciris_manager.manager.DockerImageCleanup"),
            patch("ciris_manager.docker_discovery.DockerAgentDiscovery", mock_discovery_class),
            patch("ciris_manager.nginx_manager.NginxManager") as mock_nginx_class,
        ):
            # Configure NginxManager to return our mocks based on hostname
            def nginx_side_effect(*args, **kwargs):
                hostname = kwargs.get("hostname", "")
                if "scout" in hostname:
                    return mock_nginx_managers["scout"]
                return mock_nginx_managers["main"]

            mock_nginx_class.side_effect = nginx_side_effect

            # Create manager
            manager = CIRISManager(multi_server_config)

            # Replace nginx_managers with our mocks so we can verify calls
            manager.nginx_managers = mock_nginx_managers
            manager.nginx_manager = mock_nginx_managers["main"]  # backward compatibility

            # Update nginx config - should report failure
            result = await manager.update_nginx_config()

            # Should return False because scout deployment failed
            assert result is False

            # Main should have succeeded
            mock_nginx_managers["main"].update_config.assert_called_once()

            # Scout deployment should have been attempted
            mock_nginx_managers["scout"].deploy_remote_config.assert_called_once()

    @pytest.mark.asyncio
    async def test_pull_agent_images(self, tmp_path):
        """Test pulling agent images."""
        nginx_dir = tmp_path / "nginx"
        nginx_dir.mkdir()

        config = CIRISManagerConfig(
            manager={"agents_directory": str(tmp_path / "agents")},
            nginx={"config_dir": str(nginx_dir), "enabled": True},
        )

        with patch("ciris_manager.manager.DockerImageCleanup"):
            manager = CIRISManager(config)

        compose_path = tmp_path / "docker-compose.yml"
        compose_path.write_text("version: '3.8'\n")

        # Mock subprocess
        with patch("asyncio.create_subprocess_exec") as mock_subprocess:
            mock_process = AsyncMock()
            mock_process.communicate = AsyncMock(return_value=(b"", b""))
            mock_subprocess.return_value = mock_process

            await manager._pull_agent_images(compose_path)

            # Verify docker-compose pull was called
            mock_subprocess.assert_called_once()
            call_args = mock_subprocess.call_args[0]
            assert call_args[0] == "docker-compose"
            assert call_args[1] == "-f"
            assert str(compose_path) in call_args[2]
            assert call_args[3] == "pull"

    def test_scan_existing_agents_no_directory(self, tmp_path):
        """Test scanning when agents directory doesn't exist."""
        nginx_dir = tmp_path / "nginx"
        nginx_dir.mkdir()

        config = CIRISManagerConfig(
            manager={"agents_directory": str(tmp_path / "nonexistent")},
            nginx={"config_dir": str(nginx_dir), "enabled": True},
        )

        # Should not raise error
        with patch("ciris_manager.manager.DockerImageCleanup"):
            manager = CIRISManager(config)
        manager._scan_existing_agents()

        # No agents should be found
        assert len(manager.agent_registry.agents) == 0

    @pytest.mark.asyncio
    async def test_container_management_loop_error_handling(self, tmp_path):
        """Test container management loop error handling."""
        nginx_dir = tmp_path / "nginx"
        nginx_dir.mkdir()

        config = CIRISManagerConfig(
            manager={"agents_directory": str(tmp_path / "agents")},
            nginx={"config_dir": str(nginx_dir), "enabled": True},
            container_management={"interval": 1},  # Minimum valid interval
        )

        with patch("ciris_manager.manager.DockerImageCleanup"):
            manager = CIRISManager(config)
        manager._running = True

        # Register an agent with invalid compose file
        manager.agent_registry.register_agent(
            agent_id="agent-test",
            name="Test",
            port=8080,
            template="test",
            compose_file="/invalid/path/compose.yml",
        )

        # Mock _recover_crashed_containers to raise an error
        with patch.object(
            manager, "_recover_crashed_containers", side_effect=Exception("Test error")
        ):
            # Run loop briefly
            loop_task = asyncio.create_task(manager.container_management_loop())
            await asyncio.sleep(0.05)

            # Stop
            manager._running = False

            # Cancel and wait
            loop_task.cancel()
            try:
                await loop_task
            except asyncio.CancelledError:
                pass

            # Should have handled error and continued

    @pytest.mark.asyncio
    async def test_create_agent_allocate_existing_port(self, tmp_path):
        """Test agent creation when port is already allocated."""
        nginx_dir = tmp_path / "nginx"
        nginx_dir.mkdir()

        config = CIRISManagerConfig(
            manager={
                "agents_directory": str(tmp_path / "agents"),
                "templates_directory": str(tmp_path / "templates"),
            },
            nginx={"config_dir": str(nginx_dir), "enabled": True},
        )

        # Create template
        templates_dir = Path(config.manager.templates_directory)
        templates_dir.mkdir(parents=True)
        template_path = templates_dir / "test.yaml"
        template_path.write_text("name: test\n")

        with patch("ciris_manager.nginx_manager.NginxManager") as mock_nginx_class:
            # Configure nginx manager mock
            mock_nginx = Mock()
            mock_nginx.ensure_managed_sections = Mock(return_value=True)
            mock_nginx.add_agent_route = Mock(return_value=True)
            mock_nginx_class.return_value = mock_nginx

            # Mock DockerImageCleanup to avoid Docker connection
            with patch("ciris_manager.manager.DockerImageCleanup"):
                manager = CIRISManager(config)
            manager.nginx_manager = mock_nginx

            # Pre-allocate port
            manager.port_manager.allocate_port("agent-existing")

            # Mock verifier and subprocess
            manager.template_verifier.is_pre_approved = AsyncMock(return_value=True)

            with patch("asyncio.create_subprocess_exec") as mock_subprocess:
                mock_process = AsyncMock()
                mock_process.returncode = 0
                mock_process.communicate = AsyncMock(return_value=(b"", b""))
                mock_subprocess.return_value = mock_process

                # Also mock subprocess.run for sudo chown calls
                with patch("subprocess.run") as mock_run:
                    mock_run.return_value = Mock(returncode=0)

                    # Create agent - should get next available port
                    result = await manager.create_agent("test", "Test")

                assert result["port"] == 8081  # Next available

    @pytest.mark.asyncio
    async def test_start_api_server_disabled(self, tmp_path):
        """Test that API server doesn't start when port is not configured."""
        nginx_dir = tmp_path / "nginx"
        nginx_dir.mkdir()

        config = CIRISManagerConfig(
            manager={
                "agents_directory": str(tmp_path / "agents"),
                "port": 0,  # Disable API (0 means don't bind)
            },
            nginx={"config_dir": str(nginx_dir), "enabled": True},
        )

        with patch("ciris_manager.manager.DockerImageCleanup"):
            manager = CIRISManager(config)

        with patch.object(manager, "_start_api_server") as mock_start_api:
            # Mock all background tasks to prevent hanging
            with patch.object(manager, "container_management_loop", new_callable=AsyncMock):
                with patch.object(manager.watchdog, "start", new_callable=AsyncMock):
                    with patch.object(
                        manager.image_cleanup, "run_periodic_cleanup", new_callable=AsyncMock
                    ):
                        await manager.start()

                        # API server should not be started
                        mock_start_api.assert_not_called()

                        # Mock watchdog.stop to avoid CancelledError
                        with patch.object(manager.watchdog, "stop", new_callable=AsyncMock):
                            await manager.stop()

    @pytest.mark.asyncio
    async def test_run_with_signal_handlers(self, tmp_path):
        """Test run method with signal handling."""
        nginx_dir = tmp_path / "nginx"
        nginx_dir.mkdir()

        config = CIRISManagerConfig(
            manager={"agents_directory": str(tmp_path / "agents")},
            nginx={"config_dir": str(nginx_dir), "enabled": True},
        )

        with patch("ciris_manager.manager.DockerImageCleanup"):
            manager = CIRISManager(config)

        # Mock signal handler setup
        with patch("asyncio.get_event_loop") as mock_get_loop:
            mock_loop = Mock()
            mock_get_loop.return_value = mock_loop

            # Mock all background tasks to prevent hanging
            with patch.object(manager, "_start_api_server", new_callable=AsyncMock):
                with patch.object(manager, "container_management_loop", new_callable=AsyncMock):
                    with patch.object(manager.watchdog, "start", new_callable=AsyncMock):
                        with patch.object(manager.watchdog, "stop", new_callable=AsyncMock):
                            with patch.object(
                                manager.image_cleanup,
                                "run_periodic_cleanup",
                                new_callable=AsyncMock,
                            ):
                                # Start run task
                                run_task = asyncio.create_task(manager.run())

                                # Let it start
                                await asyncio.sleep(0.01)

                                # Trigger shutdown
                                manager._shutdown_event.set()

                                # Wait for completion
                                await run_task

            # Verify signal handlers were added
            assert mock_loop.add_signal_handler.called
