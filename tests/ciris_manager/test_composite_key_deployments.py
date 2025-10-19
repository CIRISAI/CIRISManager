"""
Integration tests for composite key support in deployments.

These tests ensure that the composite key changes don't break any deployment mechanisms:
- Agent creation with occurrence_id
- Deployment orchestrator with composite keys
- Multi-instance deployments (same agent_id, different occurrence_id)
- Container operations with composite keys
- Agent discovery with composite keys
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch

from ciris_manager.deployment_orchestrator import DeploymentOrchestrator
from ciris_manager.models import (
    UpdateNotification,
    AgentInfo,
    DeploymentStatus,
)
from ciris_manager.agent_registry import AgentRegistry


class TestCompositeKeyDeployments:
    """Test deployment functionality with composite keys."""

    @pytest.fixture
    def registry(self, tmp_path):
        """Create agent registry."""
        return AgentRegistry(tmp_path / "metadata.json")

    @pytest.fixture
    def orchestrator(self, registry, tmp_path):
        """Create deployment orchestrator with registry."""
        mock_manager = Mock()
        mock_manager.agent_registry = registry

        orchestrator = DeploymentOrchestrator(manager=mock_manager)
        orchestrator.state_dir = tmp_path / "state"
        orchestrator.state_dir.mkdir(exist_ok=True)
        orchestrator.deployment_state_file = orchestrator.state_dir / "deployment_state.json"
        orchestrator.deployments = {}
        orchestrator.current_deployment = None
        orchestrator.registry_client = Mock()
        orchestrator.registry_client.resolve_image_digest = AsyncMock(return_value="sha256:test123")
        return orchestrator

    @pytest.fixture
    def update_notification(self):
        """Create sample update notification."""
        return UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:v2.0",
            message="Update with composite keys",
            strategy="immediate",
        )

    def test_register_agent_with_occurrence_id(self, registry):
        """Test registering agent with occurrence_id."""
        # Register agent with occurrence_id
        agent = registry.register_agent(
            agent_id="scout-abc123",
            name="Scout LB 1",
            port=8080,
            template="scout",
            compose_file="/path/to/compose.yml",
            occurrence_id="scout_lb_1",
            server_id="main",
        )

        assert agent.occurrence_id == "scout_lb_1"
        assert agent.agent_id == "scout-abc123"
        assert agent.server_id == "main"

        # Verify composite key was used
        composite_key = "scout-abc123-scout_lb_1-main"
        assert composite_key in registry.agents

    def test_register_multiple_instances_same_agent_id(self, registry):
        """Test registering multiple instances with same agent_id for load balancing."""
        # Register first instance
        agent1 = registry.register_agent(
            agent_id="scout-abc123",
            name="Scout LB 1",
            port=8080,
            template="scout",
            compose_file="/path/to/compose1.yml",
            occurrence_id="scout_lb_1",
            server_id="main",
        )

        # Register second instance with same agent_id but different occurrence_id
        agent2 = registry.register_agent(
            agent_id="scout-abc123",
            name="Scout LB 2",
            port=8081,
            template="scout",
            compose_file="/path/to/compose2.yml",
            occurrence_id="scout_lb_2",
            server_id="main",
        )

        # Both should be registered
        assert len(registry.agents) == 2
        assert agent1.occurrence_id == "scout_lb_1"
        assert agent2.occurrence_id == "scout_lb_2"

        # Verify both have the same agent_id
        assert agent1.agent_id == agent2.agent_id == "scout-abc123"

    @pytest.mark.asyncio
    async def test_deployment_with_occurrence_id_agents(
        self, orchestrator, registry, update_notification
    ):
        """Test deployment to agents with occurrence_id."""
        # Register agents with occurrence_id
        registry.register_agent(
            agent_id="scout-abc123",
            name="Scout LB 1",
            port=8080,
            template="scout",
            compose_file="/path/to/compose1.yml",
            occurrence_id="scout_lb_1",
            server_id="main",
            service_token="token1",
        )

        registry.register_agent(
            agent_id="scout-abc123",
            name="Scout LB 2",
            port=8081,
            template="scout",
            compose_file="/path/to/compose2.yml",
            occurrence_id="scout_lb_2",
            server_id="main",
            service_token="token2",
        )

        # Create agent info objects
        agents = [
            AgentInfo(
                agent_id="scout-abc123",
                agent_name="Scout LB 1",
                container_name="ciris-scout-abc123",
                api_port=8080,
                status="running",
            ),
            AgentInfo(
                agent_id="scout-abc123",
                agent_name="Scout LB 2",
                container_name="ciris-scout-abc123",
                api_port=8081,
                status="running",
            ),
        ]

        # Mock image operations
        orchestrator._pull_images = AsyncMock(
            return_value={"success": True, "agent_image": update_notification.agent_image}
        )
        orchestrator._get_local_image_digest = AsyncMock(return_value="sha256:new123")
        orchestrator._get_container_image_digest = AsyncMock(return_value="sha256:old456")

        # Start deployment
        status = await orchestrator.start_deployment(update_notification, agents)

        assert status.deployment_id is not None
        assert status.agents_total == 2  # Both instances should be included
        assert status.status in ["in_progress", "completed"]

    @pytest.mark.asyncio
    async def test_update_agent_with_composite_key_lookup(
        self, orchestrator, registry, update_notification
    ):
        """Test updating an agent using composite key lookup."""
        # Register agent with occurrence_id
        registry.register_agent(
            agent_id="scout-xyz789",
            name="Scout Instance",
            port=8082,
            template="scout",
            compose_file="/tmp/scout/docker-compose.yml",
            occurrence_id="scout_prod_1",
            server_id="main",
            service_token="test-token",
        )

        agent = AgentInfo(
            agent_id="scout-xyz789",
            agent_name="Scout Instance",
            container_name="ciris-scout-xyz789",
            api_port=8082,
            status="running",
        )

        # Mock operations
        orchestrator._wait_for_container_stop = AsyncMock(return_value=True)
        orchestrator._recreate_agent_container = AsyncMock(return_value=True)

        # Create deployment
        deployment = DeploymentStatus(
            deployment_id="test-deployment",
            agents_total=1,
            agents_updated=0,
            status="in_progress",
            message="Test",
            agents_pending_restart=[],
            agents_in_progress={},
        )
        orchestrator.deployments["test-deployment"] = deployment

        # Mock agent auth
        mock_auth = Mock()
        mock_auth.get_auth_headers.return_value = {"Authorization": "Bearer test"}

        with patch("ciris_manager.agent_auth.get_agent_auth", return_value=mock_auth):
            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.json.return_value = {"decision": "accept"}
                mock_client.post.return_value = mock_response
                mock_client_class.return_value.__aenter__.return_value = mock_client

                response = await orchestrator._update_single_agent(
                    "test-deployment", update_notification, agent
                )

        # Verify agent was found and updated
        assert response.agent_id == "scout-xyz789"
        assert response.decision == "accept"

    @pytest.mark.asyncio
    async def test_canary_deployment_with_composite_keys(
        self, orchestrator, registry, update_notification
    ):
        """Test canary deployment with multi-instance agents."""
        # Register multiple instances with canary groups
        registry.register_agent(
            agent_id="scout-lb-001",
            name="Scout LB 1",
            port=8080,
            template="scout",
            compose_file="/path/compose1.yml",
            occurrence_id="scout_lb_1",
            server_id="main",
        )
        registry.set_canary_group(
            "scout-lb-001", "explorer", occurrence_id="scout_lb_1", server_id="main"
        )

        registry.register_agent(
            agent_id="scout-lb-002",
            name="Scout LB 2",
            port=8081,
            template="scout",
            compose_file="/path/compose2.yml",
            occurrence_id="scout_lb_2",
            server_id="main",
        )
        registry.set_canary_group(
            "scout-lb-002", "general", occurrence_id="scout_lb_2", server_id="main"
        )

        agents = [
            AgentInfo(
                agent_id="scout-lb-001",
                agent_name="Scout LB 1",
                container_name="ciris-scout-lb-001",
                api_port=8080,
                status="running",
            ),
            AgentInfo(
                agent_id="scout-lb-002",
                agent_name="Scout LB 2",
                container_name="ciris-scout-lb-002",
                api_port=8081,
                status="running",
            ),
        ]

        # Mock operations
        orchestrator._pull_images = AsyncMock(
            return_value={"success": True, "agent_image": update_notification.agent_image}
        )
        orchestrator._get_local_image_digest = AsyncMock(return_value="sha256:new123")
        orchestrator._get_container_image_digest = AsyncMock(return_value="sha256:old456")

        # Update to use canary strategy
        canary_notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:v2.0",
            message="Canary update",
            strategy="canary",
        )

        status = await orchestrator.start_deployment(canary_notification, agents)

        assert status.deployment_id is not None
        assert status.agents_total == 2
        assert status.canary_phase == "explorers"

    @pytest.mark.asyncio
    async def test_deployment_state_persistence_with_composite_keys(
        self, orchestrator, registry, update_notification
    ):
        """Test that deployment state persists correctly with composite keys."""
        # Register agents with occurrence_id
        registry.register_agent(
            agent_id="datum-123",
            name="Datum",
            port=8001,
            template="base",
            compose_file="/path/datum.yml",
            occurrence_id="datum_prod_1",
            server_id="main",
        )

        agent = AgentInfo(
            agent_id="datum-123",
            agent_name="Datum",
            container_name="ciris-datum-123",
            api_port=8001,
            status="running",
        )

        # Mock operations
        orchestrator._pull_images = AsyncMock(
            return_value={"success": True, "agent_image": update_notification.agent_image}
        )
        orchestrator._get_local_image_digest = AsyncMock(return_value="sha256:new123")
        orchestrator._get_container_image_digest = AsyncMock(return_value="sha256:old456")

        # Start deployment
        status = await orchestrator.start_deployment(update_notification, [agent])

        # Save and reload state
        orchestrator._save_state()

        # Create new orchestrator to simulate restart
        new_orchestrator = DeploymentOrchestrator(manager=orchestrator.manager)
        new_orchestrator.state_dir = orchestrator.state_dir
        new_orchestrator.deployment_state_file = orchestrator.deployment_state_file
        new_orchestrator._load_state()

        # Verify deployment was reloaded
        assert status.deployment_id in new_orchestrator.deployments
        reloaded = new_orchestrator.deployments[status.deployment_id]
        assert reloaded.agents_total == 1

    def test_backward_compatibility_agents_without_occurrence_id(self, registry):
        """Test that agents without occurrence_id still work (backward compatibility)."""
        # Register agent without occurrence_id (old style)
        agent = registry.register_agent(
            agent_id="legacy-agent",
            name="Legacy Agent",
            port=9000,
            template="base",
            compose_file="/path/legacy.yml",
            server_id="main",
        )

        assert agent.occurrence_id is None
        assert agent.agent_id == "legacy-agent"

        # Should use simpler composite key format
        composite_key = "legacy-agent-main"
        assert composite_key in registry.agents

        # Can retrieve without occurrence_id
        retrieved = registry.get_agent("legacy-agent")
        assert retrieved is not None
        assert retrieved.agent_id == "legacy-agent"

    @pytest.mark.asyncio
    async def test_deployment_to_mixed_agents(self, orchestrator, registry, update_notification):
        """Test deployment to mix of agents with and without occurrence_id."""
        # Register mix of agents
        registry.register_agent(
            agent_id="new-agent",
            name="New Agent",
            port=8080,
            template="scout",
            compose_file="/path/new.yml",
            occurrence_id="new_inst_1",
            server_id="main",
        )

        registry.register_agent(
            agent_id="legacy-agent",
            name="Legacy Agent",
            port=8081,
            template="base",
            compose_file="/path/legacy.yml",
            server_id="main",
            # No occurrence_id
        )

        agents = [
            AgentInfo(
                agent_id="new-agent",
                agent_name="New Agent",
                container_name="ciris-new-agent",
                api_port=8080,
                status="running",
            ),
            AgentInfo(
                agent_id="legacy-agent",
                agent_name="Legacy Agent",
                container_name="ciris-legacy-agent",
                api_port=8081,
                status="running",
            ),
        ]

        # Mock operations
        orchestrator._pull_images = AsyncMock(
            return_value={"success": True, "agent_image": update_notification.agent_image}
        )
        orchestrator._get_local_image_digest = AsyncMock(return_value="sha256:new123")
        orchestrator._get_container_image_digest = AsyncMock(return_value="sha256:old456")

        status = await orchestrator.start_deployment(update_notification, agents)

        assert status.agents_total == 2
        assert status.status in ["in_progress", "completed"]

    def test_get_agents_by_agent_id_for_load_balancer(self, registry):
        """Test getting all instances of a load-balanced agent."""
        # Register multiple instances for load balancing
        registry.register_agent(
            agent_id="scout-lb",
            name="Scout LB 1",
            port=8080,
            template="scout",
            compose_file="/path/1.yml",
            occurrence_id="scout_lb_1",
            server_id="scoutapi",
        )

        registry.register_agent(
            agent_id="scout-lb",
            name="Scout LB 2",
            port=8081,
            template="scout",
            compose_file="/path/2.yml",
            occurrence_id="scout_lb_2",
            server_id="scoutapi2",
        )

        registry.register_agent(
            agent_id="datum",
            name="Datum",
            port=8001,
            template="base",
            compose_file="/path/datum.yml",
            server_id="main",
        )

        # Get all scout-lb instances
        scout_instances = registry.get_agents_by_agent_id("scout-lb")
        assert len(scout_instances) == 2

        # Verify both have same agent_id but different occurrence_id
        assert all(a.agent_id == "scout-lb" for a in scout_instances)
        occurrence_ids = {a.occurrence_id for a in scout_instances}
        assert occurrence_ids == {"scout_lb_1", "scout_lb_2"}

        # datum should only have one instance
        datum_instances = registry.get_agents_by_agent_id("datum")
        assert len(datum_instances) == 1

    @pytest.mark.asyncio
    async def test_container_recreation_with_occurrence_id(self, orchestrator, registry):
        """Test container recreation for agents with occurrence_id."""
        # Register agent with occurrence_id
        registry.register_agent(
            agent_id="test-123",
            name="Test Instance",
            port=8080,
            template="scout",
            compose_file="/opt/ciris/agents/test-123/docker-compose.yml",
            occurrence_id="test_inst_1",
            server_id="main",
        )

        # Mock compose file exists and subprocess execution
        with patch("pathlib.Path.exists", return_value=True):
            with patch("asyncio.create_subprocess_exec") as mock_subprocess:
                # Need two different mock processes: one for docker-compose, one for docker inspect
                mock_compose_process = AsyncMock()
                mock_compose_process.returncode = 0
                mock_compose_process.communicate.return_value = (b"Container started", b"")

                mock_inspect_process = AsyncMock()
                mock_inspect_process.returncode = 0
                mock_inspect_process.communicate.return_value = (b"running", b"")

                # Return different mocks based on the command
                def subprocess_side_effect(*args, **kwargs):
                    if "docker-compose" in args:
                        return mock_compose_process
                    elif "docker" in args and "inspect" in args:
                        return mock_inspect_process
                    return mock_compose_process

                mock_subprocess.side_effect = subprocess_side_effect

                result = await orchestrator._recreate_agent_container("test-123")

        assert result is True

    def test_registry_metadata_persistence_with_occurrence_id(self, tmp_path):
        """Test that occurrence_id persists across registry reloads."""
        metadata_file = tmp_path / "metadata.json"

        # Create registry and add agent with occurrence_id
        registry1 = AgentRegistry(metadata_file)
        registry1.register_agent(
            agent_id="persistent-agent",
            name="Persistent",
            port=8080,
            template="scout",
            compose_file="/path/compose.yml",
            occurrence_id="persist_1",
            server_id="main",
        )

        # Load in new registry instance
        registry2 = AgentRegistry(metadata_file)

        # Verify occurrence_id was persisted
        agent = registry2.get_agent("persistent-agent", occurrence_id="persist_1", server_id="main")
        assert agent is not None
        assert agent.occurrence_id == "persist_1"
        assert agent.agent_id == "persistent-agent"

    @pytest.mark.asyncio
    async def test_deployment_to_agents_on_different_servers(
        self, orchestrator, registry, update_notification
    ):
        """Test deployment to agents with same agent_id on different servers."""
        # Register same agent_id on different servers
        registry.register_agent(
            agent_id="scout-multi",
            name="Scout Main",
            port=8080,
            template="scout",
            compose_file="/path/main.yml",
            occurrence_id="scout_main_1",
            server_id="main",
        )

        registry.register_agent(
            agent_id="scout-multi",
            name="Scout Remote",
            port=8080,
            template="scout",
            compose_file="/path/remote.yml",
            occurrence_id="scout_remote_1",
            server_id="scout",
        )

        agents = [
            AgentInfo(
                agent_id="scout-multi",
                agent_name="Scout Main",
                container_name="ciris-scout-multi",
                api_port=8080,
                status="running",
            ),
            AgentInfo(
                agent_id="scout-multi",
                agent_name="Scout Remote",
                container_name="ciris-scout-multi",
                api_port=8080,
                status="running",
            ),
        ]

        # Mock operations
        orchestrator._pull_images = AsyncMock(
            return_value={"success": True, "agent_image": update_notification.agent_image}
        )
        orchestrator._get_local_image_digest = AsyncMock(return_value="sha256:new123")
        orchestrator._get_container_image_digest = AsyncMock(return_value="sha256:old456")

        status = await orchestrator.start_deployment(update_notification, agents)

        assert status.agents_total == 2
        # Both should be deployable even though they share agent_id

    def test_unregister_specific_instance_among_multiple(self, registry):
        """Test unregistering a specific instance when multiple exist with same agent_id."""
        # Register multiple instances
        registry.register_agent(
            agent_id="multi-inst",
            name="Instance 1",
            port=8080,
            template="scout",
            compose_file="/path/1.yml",
            occurrence_id="inst_1",
            server_id="main",
        )

        registry.register_agent(
            agent_id="multi-inst",
            name="Instance 2",
            port=8081,
            template="scout",
            compose_file="/path/2.yml",
            occurrence_id="inst_2",
            server_id="main",
        )

        registry.register_agent(
            agent_id="multi-inst",
            name="Instance 3",
            port=8082,
            template="scout",
            compose_file="/path/3.yml",
            occurrence_id="inst_3",
            server_id="main",
        )

        assert len(registry.agents) == 3

        # Unregister just instance 2
        removed = registry.unregister_agent("multi-inst", occurrence_id="inst_2", server_id="main")

        assert removed is not None
        assert removed.occurrence_id == "inst_2"
        assert len(registry.agents) == 2

        # Verify instance 1 and 3 still exist
        inst1 = registry.get_agent("multi-inst", occurrence_id="inst_1", server_id="main")
        inst3 = registry.get_agent("multi-inst", occurrence_id="inst_3", server_id="main")

        assert inst1 is not None
        assert inst3 is not None


class TestCompositeKeyAgentCreation:
    """Test agent creation with occurrence_id."""

    @pytest.mark.asyncio
    async def test_create_agent_with_occurrence_id(self, tmp_path):
        """Test creating agent with occurrence_id through manager."""
        from ciris_manager.agent_registry import AgentRegistry

        registry = AgentRegistry(tmp_path / "metadata.json")

        # Simulate what manager.create_agent does
        agent_id = "new-scout-abc123"
        occurrence_id = "scout_lb_1"

        agent = registry.register_agent(
            agent_id=agent_id,
            name="Scout LB 1",
            port=8080,
            template="scout",
            compose_file="/path/compose.yml",
            occurrence_id=occurrence_id,
            server_id="main",
        )

        assert agent.occurrence_id == occurrence_id
        assert agent.agent_id == agent_id

        # Verify it can be retrieved
        retrieved = registry.get_agent(agent_id, occurrence_id=occurrence_id, server_id="main")
        assert retrieved is not None
        assert retrieved.occurrence_id == occurrence_id

    def test_create_multiple_agents_same_id_different_occurrence(self, tmp_path):
        """Test creating multiple agents with same ID but different occurrence_id."""
        from ciris_manager.agent_registry import AgentRegistry

        registry = AgentRegistry(tmp_path / "metadata.json")

        # Create first instance
        agent1 = registry.register_agent(
            agent_id="scout-shared",
            name="Scout 1",
            port=8080,
            template="scout",
            compose_file="/path/1.yml",
            occurrence_id="scout_1",
            server_id="main",
        )

        # Create second instance with same agent_id
        agent2 = registry.register_agent(
            agent_id="scout-shared",
            name="Scout 2",
            port=8081,
            template="scout",
            compose_file="/path/2.yml",
            occurrence_id="scout_2",
            server_id="main",
        )

        # Both should succeed
        assert agent1.agent_id == agent2.agent_id == "scout-shared"
        assert agent1.occurrence_id == "scout_1"
        assert agent2.occurrence_id == "scout_2"
        assert len(registry.agents) == 2
