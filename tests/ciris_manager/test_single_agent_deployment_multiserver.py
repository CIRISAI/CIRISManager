"""
Test single-agent deployment with multi-server Docker image pulling.

This test module specifically covers the bug fix where single-agent deployments
were pulling Docker images on the local (main) server instead of on the target
server where the agent container runs.

REGRESSION TEST: Ensures images are always pulled on the correct server.
"""

import pytest
from unittest.mock import Mock, patch

from ciris_manager.models import UpdateNotification, AgentInfo


class TestSingleAgentDeploymentMultiServer:
    """
    Test single-agent deployments pull images on correct servers.

    These tests focus specifically on the image pulling behavior to prevent
    regression of the bug where images were pulled on main server for all agents.
    """

    @pytest.mark.asyncio
    async def test_remote_agent_pulls_image_on_remote_server(self, orchestrator, mock_manager):
        """
        CRITICAL TEST: Verify images are pulled on the agent's server, not main.

        This is the core regression test for the bug where scout agents on remote
        servers had images pulled on main server, causing deployments to fail.
        """
        # Create remote agent on scout server
        remote_agent = AgentInfo(
            agent_id="scout-remote-xyz",
            agent_name="Scout Remote",
            container_name="ciris-scout-remote-xyz",
            api_port=8000,
            status="running",
            server_id="scout",  # KEY: This agent is on scout server
        )

        # Mock agent discovery
        with patch("ciris_manager.docker_discovery.DockerAgentDiscovery") as mock_discovery_class:
            mock_discovery = Mock()
            mock_discovery.discover_agents = Mock(return_value=[remote_agent])
            mock_discovery_class.return_value = mock_discovery

            notification = UpdateNotification(
                agent_image="ghcr.io/cirisai/ciris-agent:1.5.1",
                message="Update to 1.5.1",
                strategy="docker",
            )

            # Call the method - we only care about the image pull, not full deployment
            try:
                await orchestrator.start_single_agent_deployment(
                    notification=notification, agent=remote_agent
                )
            except Exception:
                # Deployment may fail in background, but image pull happens first
                pass

            # CRITICAL ASSERTION: Image was pulled on scout server
            scout_client = mock_manager.docker_client._clients["scout"]
            scout_client.images.pull.assert_called_once_with("ghcr.io/cirisai/ciris-agent:1.5.1")

            # CRITICAL ASSERTION: Image was NOT pulled on main server
            main_client = mock_manager.docker_client._clients["main"]
            main_client.images.pull.assert_not_called()

    @pytest.mark.asyncio
    async def test_local_agent_pulls_image_on_main_server(self, orchestrator, mock_manager):
        """Verify local agents (server_id=main) pull images on main server."""
        local_agent = AgentInfo(
            agent_id="datum",
            agent_name="Datum",
            container_name="ciris-datum",
            api_port=8001,
            status="running",
            server_id="main",  # Local server
        )

        with patch("ciris_manager.docker_discovery.DockerAgentDiscovery") as mock_discovery_class:
            mock_discovery = Mock()
            mock_discovery.discover_agents = Mock(return_value=[local_agent])
            mock_discovery_class.return_value = mock_discovery

            notification = UpdateNotification(
                agent_image="ghcr.io/cirisai/ciris-agent:1.5.1",
                message="Update to 1.5.1",
                strategy="docker",
            )

            try:
                await orchestrator.start_single_agent_deployment(
                    notification=notification, agent=local_agent
                )
            except Exception:
                pass

            # Verify image was pulled on main server
            main_client = mock_manager.docker_client._clients["main"]
            main_client.images.pull.assert_called_once_with("ghcr.io/cirisai/ciris-agent:1.5.1")

            # Verify scout server was NOT used
            scout_client = mock_manager.docker_client._clients["scout"]
            scout_client.images.pull.assert_not_called()

    @pytest.mark.asyncio
    async def test_image_pull_failure_returns_failed_status(self, orchestrator, mock_manager):
        """Verify image pull failures on remote servers are handled properly."""
        remote_agent = AgentInfo(
            agent_id="scout2-agent",
            agent_name="Scout2 Agent",
            container_name="ciris-scout2-agent",
            api_port=8002,
            status="running",
            server_id="scout2",
        )

        # Make image pull fail on scout2
        scout2_client = mock_manager.docker_client._clients["scout2"]
        scout2_client.images.pull.side_effect = Exception("Network timeout")

        with patch("ciris_manager.docker_discovery.DockerAgentDiscovery") as mock_discovery_class:
            mock_discovery = Mock()
            mock_discovery.discover_agents = Mock(return_value=[remote_agent])
            mock_discovery_class.return_value = mock_discovery

            notification = UpdateNotification(
                agent_image="ghcr.io/cirisai/ciris-agent:1.5.1",
                message="Update to 1.5.1",
                strategy="docker",
            )

            status = await orchestrator.start_single_agent_deployment(
                notification=notification, agent=remote_agent
            )

            # Verify image pull was attempted on scout2
            scout2_client.images.pull.assert_called_once_with("ghcr.io/cirisai/ciris-agent:1.5.1")

            # Verify deployment failed immediately
            assert status.status == "failed"
            assert status.agents_updated == 0
            assert status.agents_failed == 1
            assert "Failed to pull image on server scout2" in status.message

    @pytest.mark.asyncio
    async def test_multiple_agents_same_id_different_servers(
        self, orchestrator, mock_manager, sample_agents
    ):
        """
        REGRESSION TEST: When multiple agents share agent_id but are on different
        servers, each deployment must pull images on the correct server.

        This prevents the bug where ALL agents got images pulled on main.
        """
        # Create two scout agents on different servers
        scout_on_main = AgentInfo(
            agent_id="scout-test",
            agent_name="Scout Test Main",
            container_name="ciris-scout-test",
            api_port=8000,
            status="running",
            server_id="main",
        )

        scout_on_remote = AgentInfo(
            agent_id="scout-test",
            agent_name="Scout Test Remote",
            container_name="ciris-scout-test",
            api_port=8000,
            status="running",
            server_id="scout",
            occurrence_id="001",
        )

        with patch("ciris_manager.docker_discovery.DockerAgentDiscovery") as mock_discovery_class:
            mock_discovery = Mock()
            mock_discovery.discover_agents = Mock(return_value=[scout_on_main, scout_on_remote])
            mock_discovery_class.return_value = mock_discovery

            notification = UpdateNotification(
                agent_image="ghcr.io/cirisai/ciris-agent:1.5.1",
                message="Update to 1.5.1",
                strategy="docker",
            )

            # Deploy to remote scout
            try:
                await orchestrator.start_single_agent_deployment(
                    notification=notification, agent=scout_on_remote
                )
            except Exception:
                pass

            # Verify correct server was used
            scout_client = mock_manager.docker_client._clients["scout"]
            scout_client.images.pull.assert_called_once_with("ghcr.io/cirisai/ciris-agent:1.5.1")

            # Verify main was NOT used even though an agent with same ID exists there
            main_client = mock_manager.docker_client._clients["main"]
            main_client.images.pull.assert_not_called()

    @pytest.mark.asyncio
    async def test_scout2_server_pulls_on_scout2(self, orchestrator, mock_manager):
        """Test third server (scout2) also pulls images correctly."""
        scout2_agent = AgentInfo(
            agent_id="scout2-test",
            agent_name="Scout2 Test",
            container_name="ciris-scout2-test",
            api_port=8100,
            status="running",
            server_id="scout2",
        )

        with patch("ciris_manager.docker_discovery.DockerAgentDiscovery") as mock_discovery_class:
            mock_discovery = Mock()
            mock_discovery.discover_agents = Mock(return_value=[scout2_agent])
            mock_discovery_class.return_value = mock_discovery

            notification = UpdateNotification(
                agent_image="ghcr.io/cirisai/ciris-agent:1.5.1",
                message="Update to 1.5.1",
                strategy="docker",
            )

            try:
                await orchestrator.start_single_agent_deployment(
                    notification=notification, agent=scout2_agent
                )
            except Exception:
                pass

            # Verify scout2 client was used
            scout2_client = mock_manager.docker_client._clients["scout2"]
            scout2_client.images.pull.assert_called_once_with("ghcr.io/cirisai/ciris-agent:1.5.1")

            # Verify other servers were not used
            main_client = mock_manager.docker_client._clients["main"]
            main_client.images.pull.assert_not_called()

            scout_client = mock_manager.docker_client._clients["scout"]
            scout_client.images.pull.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_client_called_with_correct_server_id(self, orchestrator, mock_manager):
        """
        Verify get_client() is called with agent.server_id parameter.

        This is the direct test of the fix: ensuring we use agent.server_id
        instead of assuming 'main' or using a default.
        """
        remote_agent = AgentInfo(
            agent_id="test-agent",
            agent_name="Test Agent",
            container_name="ciris-test-agent",
            api_port=8000,
            status="running",
            server_id="scout",  # Remote server
        )

        with patch("ciris_manager.docker_discovery.DockerAgentDiscovery") as mock_discovery_class:
            mock_discovery = Mock()
            mock_discovery.discover_agents = Mock(return_value=[remote_agent])
            mock_discovery_class.return_value = mock_discovery

            notification = UpdateNotification(
                agent_image="ghcr.io/cirisai/ciris-agent:1.5.1",
                message="Update",
                strategy="docker",
            )

            try:
                await orchestrator.start_single_agent_deployment(
                    notification=notification, agent=remote_agent
                )
            except Exception:
                pass

            # Verify get_client was called with 'scout', not 'main'
            mock_manager.docker_client.get_client.assert_any_call("scout")
