"""
Additional manager tests for coverage.
"""

import pytest
import asyncio
from unittest.mock import patch, AsyncMock
from ciris_manager.manager import CIRISManager
from ciris_manager.config.settings import CIRISManagerConfig


class TestManagerAdditional:
    """Additional manager tests."""

    @pytest.mark.asyncio
    async def test_start_api_server_basic(self, tmp_path):
        """Test basic API server initialization."""
        # Create nginx config dir
        nginx_dir = tmp_path / "nginx"
        nginx_dir.mkdir()

        config = CIRISManagerConfig(
            manager={
                "agents_directory": str(tmp_path / "agents"),
                "port": 8889,  # Use a specific port
                "host": "127.0.0.1",
            },
            nginx={"config_dir": str(nginx_dir)},
        )

        # Mock Docker dependencies
        with (
            patch("ciris_manager.nginx_manager.NginxManager"),
            patch("ciris_manager.multi_server_docker.MultiServerDockerClient"),
            patch("ciris_manager.manager.DockerImageCleanup"),
            patch("ciris_manager.docker_discovery.DockerAgentDiscovery"),
        ):
            manager = CIRISManager(config)

            # Just verify that the method exists and is callable
            assert hasattr(manager, "_start_api_server")
            assert asyncio.iscoroutinefunction(manager._start_api_server)

    @pytest.mark.asyncio
    async def test_container_management_with_image_pull_disabled(self, tmp_path):
        """Test container management without pulling images."""
        # Create nginx config dir
        nginx_dir = tmp_path / "nginx"
        nginx_dir.mkdir()

        config = CIRISManagerConfig(
            manager={"agents_directory": str(tmp_path / "agents")},
            nginx={"config_dir": str(nginx_dir)},
            container_management={
                "pull_images": False,
                "interval": 1,  # Use 1 second for fast testing
            },
        )

        # Mock Docker dependencies
        with (
            patch("ciris_manager.nginx_manager.NginxManager"),
            patch("ciris_manager.multi_server_docker.MultiServerDockerClient"),
            patch("ciris_manager.manager.DockerImageCleanup"),
            patch("ciris_manager.docker_discovery.DockerAgentDiscovery"),
        ):
            manager = CIRISManager(config)

            # Create agent with compose file
            agent_dir = tmp_path / "agents" / "test"
            agent_dir.mkdir(parents=True)
            compose_file = agent_dir / "docker-compose.yml"
            compose_file.write_text("version: '3.8'\n")

            manager.agent_registry.register_agent(
                agent_id="agent-test",
                name="Test",
                port=8080,
                template="test",
                compose_file=str(compose_file),
            )

            # Mock _recover_crashed_containers to avoid slow operations
            with patch.object(
                manager, "_recover_crashed_containers", new_callable=AsyncMock
            ) as mock_recover:
                # Run briefly
                manager._running = True
                task = asyncio.create_task(manager.container_management_loop())
                await asyncio.sleep(0.05)
                manager._running = False

                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

                # Verify recovery was called (container loop only does crash recovery now)
                assert mock_recover.called

    def test_scan_with_invalid_metadata(self, tmp_path):
        """Test scanning with invalid agent metadata."""
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        nginx_dir = tmp_path / "nginx"
        nginx_dir.mkdir()

        config = CIRISManagerConfig(
            manager={"agents_directory": str(agents_dir)}, nginx={"config_dir": str(nginx_dir)}
        )

        # Create agent directory
        agent_dir = agents_dir / "test"
        agent_dir.mkdir()
        compose_file = agent_dir / "docker-compose.yml"
        compose_file.write_text("version: '3.8'\n")

        # Create invalid metadata
        metadata_file = agents_dir / "metadata.json"
        metadata_file.write_text("invalid json")

        # Mock Docker dependencies
        with (
            patch("ciris_manager.nginx_manager.NginxManager"),
            patch("ciris_manager.multi_server_docker.MultiServerDockerClient"),
            patch("ciris_manager.manager.DockerImageCleanup"),
            patch("ciris_manager.docker_discovery.DockerAgentDiscovery"),
        ):
            # Should handle gracefully
            CIRISManager(config)
            # No exception raised
