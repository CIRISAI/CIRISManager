"""
Tests for deployment orchestrator.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
import asyncio
from datetime import datetime, timezone

from ciris_manager.deployment_orchestrator import DeploymentOrchestrator
from ciris_manager.models import (
    UpdateNotification,
    AgentInfo,
    DeploymentStatus,
)


class TestDeploymentOrchestrator:
    """Test deployment orchestration."""

    @pytest.fixture
    def orchestrator(self, tmp_path):
        """Create deployment orchestrator."""
        from ciris_manager.agent_registry import AgentRegistry

        # Create a mock manager with agent registry
        mock_manager = Mock()
        mock_manager.agent_registry = AgentRegistry(tmp_path / "metadata.json")

        orchestrator = DeploymentOrchestrator(manager=mock_manager)
        # Mock the registry client to avoid real network calls
        orchestrator.registry_client = Mock()
        orchestrator.registry_client.resolve_image_digest = AsyncMock(return_value="sha256:test123")
        return orchestrator

    @pytest.fixture
    def update_notification(self):
        """Create sample update notification."""
        return UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:v2.0",
            gui_image="ghcr.io/cirisai/ciris-gui:v2.0",
            message="Security update",
            strategy="canary",
            metadata={"version": "2.0"},
        )

    @pytest.fixture
    def sample_agents(self):
        """Create sample agents."""
        agents = []
        for i in range(10):
            agents.append(
                AgentInfo(
                    agent_id=f"agent-{i}",
                    agent_name=f"Agent {i}",
                    container_name=f"ciris-agent-{i}",
                    api_port=8080 + i,
                    status="running",  # This makes is_running property return True
                )
            )
        return agents

    @pytest.mark.asyncio
    async def test_start_deployment(self, orchestrator, update_notification, sample_agents):
        """Test starting a deployment."""
        # Mock the image pull operation
        orchestrator._pull_images = AsyncMock(
            return_value={
                "success": True,
                "agent_image": "ghcr.io/cirisai/ciris-agent:v2.0",
                "gui_image": "ghcr.io/cirisai/ciris-gui:v2.0",
            }
        )

        # Mock the local image digest checks to indicate images have changed
        orchestrator._get_local_image_digest = AsyncMock(return_value="sha256:newdigest123")
        orchestrator._get_container_image_digest = AsyncMock(return_value="sha256:olddigest456")

        # Mock registry client to return different digests (indicating images changed)
        orchestrator.registry_client.resolve_image_digest = AsyncMock(
            side_effect=[
                "sha256:newagent123",  # New agent image
                "sha256:newgui456",  # New GUI image
            ]
        )

        status = await orchestrator.start_deployment(update_notification, sample_agents)

        assert status.deployment_id is not None
        assert status.agents_total == 10
        assert status.status == "in_progress"
        assert status.message == "Security update"
        assert status.canary_phase == "explorers"
        assert orchestrator.current_deployment == status.deployment_id

    @pytest.mark.asyncio
    async def test_concurrent_deployment_rejected(
        self, orchestrator, update_notification, sample_agents
    ):
        """Test that concurrent deployments are rejected."""
        # Mock the image pull operation
        orchestrator._pull_images = AsyncMock(
            return_value={
                "success": True,
                "agent_image": "ghcr.io/cirisai/ciris-agent:v2.0",
                "gui_image": "ghcr.io/cirisai/ciris-gui:v2.0",
            }
        )
        orchestrator._get_local_image_digest = AsyncMock(return_value="sha256:newdigest123")
        orchestrator._get_container_image_digest = AsyncMock(return_value="sha256:olddigest456")

        # Start first deployment
        await orchestrator.start_deployment(update_notification, sample_agents)

        # Try to start second deployment
        with pytest.raises(ValueError, match="already in progress"):
            await orchestrator.start_deployment(update_notification, sample_agents)

    @pytest.mark.asyncio
    async def test_get_deployment_status(self, orchestrator, update_notification, sample_agents):
        """Test getting deployment status."""
        # Mock the image pull operation
        orchestrator._pull_images = AsyncMock(
            return_value={
                "success": True,
                "agent_image": "ghcr.io/cirisai/ciris-agent:v2.0",
                "gui_image": "ghcr.io/cirisai/ciris-gui:v2.0",
            }
        )
        orchestrator._get_local_image_digest = AsyncMock(return_value="sha256:newdigest123")
        orchestrator._get_container_image_digest = AsyncMock(return_value="sha256:olddigest456")

        status = await orchestrator.start_deployment(update_notification, sample_agents)
        deployment_id = status.deployment_id

        # Get by ID
        retrieved = await orchestrator.get_deployment_status(deployment_id)
        assert retrieved is not None
        assert retrieved.deployment_id == deployment_id

        # Get current
        current = await orchestrator.get_current_deployment()
        assert current is not None
        assert current.deployment_id == deployment_id

    @pytest.mark.asyncio
    async def test_canary_deployment_phases(self, orchestrator, update_notification, sample_agents):
        """Test canary deployment phases."""
        # Mock the image pull operation
        orchestrator._pull_images = AsyncMock(
            return_value={
                "success": True,
                "agent_image": "ghcr.io/cirisai/ciris-agent:v2.0",
                "gui_image": "ghcr.io/cirisai/ciris-gui:v2.0",
            }
        )
        orchestrator._get_local_image_digest = AsyncMock(return_value="sha256:newdigest123")
        orchestrator._get_container_image_digest = AsyncMock(return_value="sha256:olddigest456")

        # Pre-assign agents to canary groups
        registry = orchestrator.manager.agent_registry

        # Register and assign agents to groups
        for i, agent in enumerate(sample_agents):
            registry.register_agent(
                agent_id=agent.agent_id,
                name=agent.agent_name,
                port=agent.api_port,
                template="base",
                compose_file=f"/path/to/{agent.agent_id}.yml",
            )

            # Assign to groups: first 2 to explorer, next 3 to early_adopter, rest to general
            if i < 2:
                registry.set_canary_group(agent.agent_id, "explorer")
            elif i < 5:
                registry.set_canary_group(agent.agent_id, "early_adopter")
            else:
                registry.set_canary_group(agent.agent_id, "general")

        with patch.object(
            orchestrator, "_update_agent_group", new_callable=AsyncMock
        ) as mock_update:
            # Mock the update method to complete immediately
            mock_update.return_value = None

            await orchestrator.start_deployment(update_notification, sample_agents)

            # Wait a bit for background task to start
            await asyncio.sleep(0.1)

            # Should have called update_agent_group for each phase that has agents
            # Note: This is a simplified test - in reality we'd need to wait for phases
            assert mock_update.call_count >= 1  # At least explorers phase

    @pytest.mark.asyncio
    async def test_immediate_deployment(self, orchestrator, sample_agents):
        """Test immediate deployment strategy."""
        # Mock the image pull operation
        orchestrator._pull_images = AsyncMock(
            return_value={"success": True, "agent_image": "ghcr.io/cirisai/ciris-agent:v2.0"}
        )
        orchestrator._get_local_image_digest = AsyncMock(return_value="sha256:newdigest123")
        orchestrator._get_container_image_digest = AsyncMock(return_value="sha256:olddigest456")

        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:v2.0",
            message="Emergency update",
            strategy="immediate",
        )

        with patch.object(
            orchestrator, "_update_agent_group", new_callable=AsyncMock
        ) as mock_update:
            mock_update.return_value = None

            status = await orchestrator.start_deployment(notification, sample_agents)

            # Wait for background task
            await asyncio.sleep(0.1)

            # Should update all agents at once
            assert status.canary_phase is None  # No phases for immediate
            assert mock_update.call_count == 1

    @pytest.mark.asyncio
    async def test_agent_update_success(self, orchestrator):
        """Test successful agent update."""
        agent = AgentInfo(
            agent_id="test-agent",
            agent_name="Test",
            container_name="ciris-test",
            api_port=8080,
            status="running",
        )

        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:v2.0",
            message="Update",
        )

        # Register agent in registry for auth with service token
        registry = orchestrator.manager.agent_registry
        registry.register_agent(
            agent_id="test-agent",
            name="Test",
            port=8080,
            template="base",
            compose_file="/path/to/test.yml",
            service_token="test-token-123",  # Add service token
        )

        # Mock agent_auth to bypass encryption
        mock_auth = Mock()
        mock_auth.get_auth_headers.return_value = {"Authorization": "Bearer service:test-token"}

        # Mock container operations
        orchestrator._wait_for_container_stop = AsyncMock(return_value=True)
        orchestrator._recreate_agent_container = AsyncMock(return_value=True)

        with patch("ciris_manager.agent_auth.get_agent_auth", return_value=mock_auth):
            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.json.return_value = {"decision": "accept"}
                mock_client.post.return_value = mock_response
                mock_client_class.return_value.__aenter__.return_value = mock_client

                response = await orchestrator._update_single_agent(
                    "deployment-123", notification, agent
                )

            assert response.agent_id == "test-agent"
            assert response.decision == "accept"  # Should be accept when container is recreated

    @pytest.mark.asyncio
    async def test_agent_update_defer(self, orchestrator):
        """Test agent rejecting update via non-200 response."""
        agent = AgentInfo(
            agent_id="busy-agent",
            agent_name="Busy",
            container_name="ciris-busy",
            api_port=8081,
            status="running",
        )

        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:v2.0",
            message="Update",
        )

        # Register agent in registry with service token
        registry = orchestrator.manager.agent_registry
        registry.register_agent(
            agent_id="busy-agent",
            name="Busy",
            port=8081,
            template="base",
            compose_file="/path/to/busy.yml",
            service_token="busy-token-456",  # Add service token
        )

        # Mock agent_auth to bypass encryption
        mock_auth = Mock()
        mock_auth.get_auth_headers.return_value = {"Authorization": "Bearer service:test-token"}
        with patch("ciris_manager.agent_auth.get_agent_auth", return_value=mock_auth):
            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_response = Mock()
                # Non-200 response means agent rejects shutdown
                mock_response.status_code = 503
                mock_response.text = "Service busy, cannot shutdown now"
                mock_client.post.return_value = mock_response
                mock_client_class.return_value.__aenter__.return_value = mock_client

                response = await orchestrator._update_single_agent(
                    "deployment-123", notification, agent
                )

            assert response.agent_id == "busy-agent"
            assert response.decision == "reject"
            assert response.reason == "HTTP 503"
            assert response.ready_at is None

    @pytest.mark.asyncio
    async def test_agent_unreachable(self, orchestrator):
        """Test handling unreachable agent."""
        agent = AgentInfo(
            agent_id="offline-agent",
            agent_name="Offline",
            container_name="ciris-offline",
            api_port=8082,
            status="running",
        )

        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:v2.0",
            message="Update",
        )

        # Register agent in registry with service token
        registry = orchestrator.manager.agent_registry
        registry.register_agent(
            agent_id="offline-agent",
            name="Offline",
            port=8082,
            template="base",
            compose_file="/path/to/offline.yml",
            service_token="offline-token-789",  # Add service token
        )

        # Mock agent_auth to bypass encryption
        mock_auth = Mock()
        mock_auth.get_auth_headers.return_value = {"Authorization": "Bearer service:test-token"}
        with patch("ciris_manager.agent_auth.get_agent_auth", return_value=mock_auth):
            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client.post.side_effect = Exception("Connection refused")
                mock_client_class.return_value.__aenter__.return_value = mock_client

                response = await orchestrator._update_single_agent(
                    "deployment-123", notification, agent
                )

            assert response.agent_id == "offline-agent"
            assert response.decision == "reject"
            assert "Connection refused" in response.reason

    @pytest.mark.asyncio
    async def test_canary_deployment_with_manual_groups(self, orchestrator, update_notification):
        """Test that canary deployment only uses manually assigned groups."""
        # Mock registry client to return different digests (indicating images changed)
        orchestrator.registry_client.resolve_image_digest = AsyncMock(
            return_value="sha256:newagent123"
        )

        # Create test agents
        agents = []
        for i in range(10):
            agents.append(
                AgentInfo(
                    agent_id=f"agent-{i}",
                    agent_name=f"Agent {i}",
                    container_name=f"ciris-agent-{i}",
                    api_port=8080 + i,
                    status="running",
                )
            )

        # Register agents but only assign some to canary groups
        registry = orchestrator.manager.agent_registry

        for i, agent in enumerate(agents):
            registry.register_agent(
                agent_id=agent.agent_id,
                name=agent.agent_name,
                port=agent.api_port,
                template="base",
                compose_file=f"/path/to/{agent.agent_id}.yml",
            )

            # Only assign first 3 agents to groups, leave rest unassigned
            if i == 0:
                registry.set_canary_group(agent.agent_id, "explorer")
            elif i == 1:
                registry.set_canary_group(agent.agent_id, "early_adopter")
            elif i == 2:
                registry.set_canary_group(agent.agent_id, "general")
            # agents 3-9 remain unassigned

        # Mock the health check to always succeed
        orchestrator._check_canary_group_health = AsyncMock(return_value=True)
        
        with patch.object(
            orchestrator, "_update_agent_group", new_callable=AsyncMock
        ) as mock_update:
            mock_update.return_value = None

            # Call _run_canary_deployment directly instead of through background task
            deployment_id = "test-deployment-123"
            orchestrator.deployments[deployment_id] = DeploymentStatus(
                deployment_id=deployment_id,
                agents_total=10,
                agents_updated=0,
                agents_deferred=0,
                agents_failed=0,
                started_at=datetime.now(timezone.utc).isoformat(),
                completed_at=None,
                status="in_progress",
                message="Test",
                canary_phase="explorers",
            )

            # Mock asyncio.sleep to avoid waiting
            with patch(
                "ciris_manager.deployment_orchestrator.asyncio.sleep", new_callable=AsyncMock
            ) as mock_sleep:
                mock_sleep.return_value = None

                await orchestrator._run_canary_deployment(
                    deployment_id, update_notification, agents
                )

                # Verify that only 3 agents (the ones with assigned groups) were updated
                # Should be called 3 times (once for each phase with 1 agent each)
                assert mock_update.call_count == 3

                # Check that each call only had 1 agent (the assigned one)
                for call in mock_update.call_args_list:
                    agents_in_call = call[0][2]  # Third argument is the agent list
                    assert len(agents_in_call) == 1

    @pytest.mark.asyncio
    async def test_canary_deployment_no_groups_assigned(
        self, orchestrator, update_notification, sample_agents
    ):
        """Test that canary deployment fails gracefully when no agents have groups assigned."""
        # Mock the image pull operation
        orchestrator._pull_images = AsyncMock(
            return_value={
                "success": True,
                "agent_image": "ghcr.io/cirisai/ciris-agent:v2.0",
                "gui_image": "ghcr.io/cirisai/ciris-gui:v2.0",
            }
        )
        orchestrator._get_local_image_digest = AsyncMock(return_value="sha256:newdigest123")
        orchestrator._get_container_image_digest = AsyncMock(return_value="sha256:olddigest456")

        # Register agents but don't assign any to canary groups
        registry = orchestrator.manager.agent_registry

        for agent in sample_agents:
            registry.register_agent(
                agent_id=agent.agent_id,
                name=agent.agent_name,
                port=agent.api_port,
                template="base",
                compose_file=f"/path/to/{agent.agent_id}.yml",
            )
            # Don't assign any canary groups

        status = await orchestrator.start_deployment(update_notification, sample_agents)

        # Wait for deployment to complete
        await asyncio.sleep(0.1)

        # Should fail because no agents are in canary groups
        final_status = await orchestrator.get_deployment_status(status.deployment_id)
        assert final_status.status == "failed"
        assert "No agents assigned to canary groups" in final_status.message

    @pytest.mark.asyncio
    async def test_no_running_agents(self, orchestrator):
        """Test deployment with no running agents."""
        # Mock the image pull operation
        orchestrator._pull_images = AsyncMock(
            return_value={"success": True, "agent_image": "ghcr.io/cirisai/ciris-agent:v2.0"}
        )
        orchestrator._get_local_image_digest = AsyncMock(return_value="sha256:newdigest123")
        orchestrator._get_container_image_digest = AsyncMock(return_value="sha256:olddigest456")

        stopped_agents = [
            AgentInfo(
                agent_id="stopped-1",
                agent_name="Stopped 1",
                container_name="ciris-stopped-1",
                api_port=8080,
                status="stopped",
            )
        ]

        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:v2.0",
            message="Update",
            strategy="canary",
        )

        # Register the stopped agent in registry (but it won't be included since it's not running)
        registry = orchestrator.manager.agent_registry
        registry.register_agent(
            agent_id="stopped-1",
            name="Stopped 1",
            port=8080,
            template="base",
            compose_file="/path/to/stopped.yml",
        )
        registry.set_canary_group("stopped-1", "explorer")

        status = await orchestrator.start_deployment(notification, stopped_agents)

        # Wait for deployment to complete
        await asyncio.sleep(0.1)

        # Get final status - should fail because no running agents in canary groups
        final_status = await orchestrator.get_deployment_status(status.deployment_id)
        assert final_status.status == "failed"
        assert "No agents assigned to canary groups" in final_status.message

    @pytest.mark.asyncio
    async def test_container_recreation_after_shutdown(self, orchestrator):
        """Test that containers are recreated after successful shutdown."""
        agent = AgentInfo(
            agent_id="test-agent",
            agent_name="Test",
            container_name="ciris-test-agent",
            api_port=8080,
            status="running",
        )

        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:v2.0",
            message="Update with recreation",
        )

        # Register agent in registry
        registry = orchestrator.manager.agent_registry
        registry.register_agent(
            agent_id="test-agent",
            name="Test",
            port=8080,
            template="base",
            compose_file="/tmp/test-agent/docker-compose.yml",
            service_token="test-token-123",
        )

        # Mock the helper methods
        orchestrator._wait_for_container_stop = AsyncMock(return_value=True)
        orchestrator._recreate_agent_container = AsyncMock(return_value=True)

        # Mock agent_auth
        mock_auth = Mock()
        mock_auth.get_auth_headers.return_value = {"Authorization": "Bearer service:test-token"}
        with patch("ciris_manager.agent_auth.get_agent_auth", return_value=mock_auth):
            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_response = Mock()
                mock_response.status_code = 200  # Agent accepts shutdown
                mock_response.json.return_value = {"status": "shutdown initiated"}
                mock_client.post.return_value = mock_response
                mock_client_class.return_value.__aenter__.return_value = mock_client

                response = await orchestrator._update_single_agent(
                    "deployment-123", notification, agent
                )

                # Verify the sequence of calls
                orchestrator._wait_for_container_stop.assert_called_once_with(
                    "ciris-test-agent", timeout=60
                )
                orchestrator._recreate_agent_container.assert_called_once_with("test-agent")

                assert response.agent_id == "test-agent"
                assert response.decision == "accept"

    @pytest.mark.asyncio
    async def test_container_not_recreated_on_rejection(self, orchestrator):
        """Test that containers are NOT recreated when agent rejects shutdown."""
        agent = AgentInfo(
            agent_id="busy-agent",
            agent_name="Busy",
            container_name="ciris-busy-agent",
            api_port=8081,
            status="running",
        )

        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:v2.0",
            message="Update attempt",
        )

        # Register agent
        registry = orchestrator.manager.agent_registry
        registry.register_agent(
            agent_id="busy-agent",
            name="Busy",
            port=8081,
            template="base",
            compose_file="/tmp/busy-agent/docker-compose.yml",
            service_token="busy-token-456",
        )

        # Mock the helper methods
        orchestrator._wait_for_container_stop = AsyncMock(return_value=True)
        orchestrator._recreate_agent_container = AsyncMock(return_value=True)

        # Mock agent_auth
        mock_auth = Mock()
        mock_auth.get_auth_headers.return_value = {"Authorization": "Bearer service:test-token"}
        with patch("ciris_manager.agent_auth.get_agent_auth", return_value=mock_auth):
            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_response = Mock()
                mock_response.status_code = 503  # Agent rejects shutdown
                mock_response.text = "Service busy"
                mock_client.post.return_value = mock_response
                mock_client_class.return_value.__aenter__.return_value = mock_client

                response = await orchestrator._update_single_agent(
                    "deployment-123", notification, agent
                )

                # Verify recreation methods were NOT called
                orchestrator._wait_for_container_stop.assert_not_called()
                orchestrator._recreate_agent_container.assert_not_called()

                assert response.agent_id == "busy-agent"
                assert response.decision == "reject"

    @pytest.mark.asyncio
    async def test_wait_for_container_stop(self, orchestrator):
        """Test waiting for container to stop."""
        # Mock the subprocess call to docker inspect
        status_sequence = ["running", "running", "exited"]
        call_count = [0]

        async def mock_subprocess(*args, **kwargs):
            # Check if this is a docker inspect call
            if "docker" in args and "inspect" in args:
                mock_result = Mock()
                if call_count[0] < len(status_sequence):
                    status = status_sequence[call_count[0]]
                    call_count[0] += 1
                else:
                    status = status_sequence[-1]

                mock_result.returncode = 0
                mock_result.communicate = AsyncMock(return_value=(status.encode(), b""))
                return mock_result
            return Mock()

        with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess):
            # Mock asyncio.sleep to speed up test
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await orchestrator._wait_for_container_stop("test-container", timeout=10)

            assert result is True
            assert call_count[0] == 3  # Should have checked 3 times

    @pytest.mark.asyncio
    async def test_wait_for_container_stop_timeout(self, orchestrator):
        """Test timeout when waiting for container to stop."""

        # Mock subprocess to always return "running" status
        async def mock_subprocess(*args, **kwargs):
            if "docker" in args and "inspect" in args:
                mock_result = Mock()
                mock_result.returncode = 0
                mock_result.communicate = AsyncMock(return_value=(b"running", b""))
                return mock_result
            return Mock()

        with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess):
            # Mock time.time to simulate timeout - need more values for multiple calls
            with patch("time.time") as mock_time:
                # Provide enough values for all time.time() calls (including logging)
                mock_time.side_effect = [0, 1, 2, 3, 61, 61, 61, 61]  # Exceeds 60 second timeout

                with patch("asyncio.sleep", new_callable=AsyncMock):
                    result = await orchestrator._wait_for_container_stop(
                        "test-container", timeout=60
                    )

            assert result is False

    @pytest.mark.asyncio
    async def test_recreate_agent_container(self, orchestrator):
        """Test recreating an agent container."""
        # Set up agent in registry
        registry = orchestrator.manager.agent_registry
        registry.register_agent(
            agent_id="test-agent",
            name="Test Agent",
            port=8080,
            template="base",
            compose_file="/opt/ciris/agents/test-agent/docker-compose.yml",
        )

        # Mock Path.exists to return True for the compose file
        with patch("pathlib.Path.exists", return_value=True):
            with patch("asyncio.create_subprocess_exec") as mock_subprocess:
                mock_process = AsyncMock()
                mock_process.returncode = 0
                mock_process.communicate.return_value = (b"Container started", b"")
                mock_subprocess.return_value = mock_process

                # Mock docker inspect to show container is running
                with patch("asyncio.create_subprocess_exec") as mock_docker:

                    async def mock_subprocess_exec(*args, **kwargs):
                        if "docker-compose" in args:
                            return mock_process
                        elif "docker" in args and "inspect" in args:
                            mock_inspect = AsyncMock()
                            mock_inspect.returncode = 0
                            mock_inspect.communicate.return_value = (b"running", b"")
                            return mock_inspect
                        return mock_process

                    mock_docker.side_effect = mock_subprocess_exec

                    result = await orchestrator._recreate_agent_container("test-agent")

                assert result is True
                # Check that docker-compose was called
                compose_calls = [
                    call for call in mock_docker.call_args_list if "docker-compose" in call[0]
                ]
                assert len(compose_calls) > 0

    @pytest.mark.asyncio
    async def test_recreate_agent_container_failure(self, orchestrator):
        """Test handling failure when recreating container."""
        # Set up agent in registry
        registry = orchestrator.manager.agent_registry
        registry.register_agent(
            agent_id="test-agent",
            name="Test Agent",
            port=8080,
            template="base",
            compose_file="/opt/ciris/agents/test-agent/docker-compose.yml",
        )

        # Mock Path.exists to return True for the compose file
        with patch("pathlib.Path.exists", return_value=True):
            with patch("asyncio.create_subprocess_exec") as mock_subprocess:
                mock_process = AsyncMock()
                mock_process.returncode = 1
                mock_process.communicate.return_value = (b"", b"Error: Container failed to start")
                mock_subprocess.return_value = mock_process

                result = await orchestrator._recreate_agent_container("test-agent")

                assert result is False
