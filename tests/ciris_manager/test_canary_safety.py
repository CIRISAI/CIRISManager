"""
Tests for canary deployment safety features.

Tests the safety mechanisms that ensure canary deployments only proceed
when agents reach WORK state and are stable without incidents.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timezone
import httpx

from ciris_manager.deployment_orchestrator import DeploymentOrchestrator
from ciris_manager.models import (
    UpdateNotification,
    AgentInfo,
    DeploymentStatus,
)


class TestCanaryGroupHealth:
    """Test the _check_canary_group_health method."""

    @pytest.fixture
    def orchestrator(self, tmp_path):
        """Create deployment orchestrator."""
        from ciris_manager.agent_registry import AgentRegistry

        mock_manager = Mock()
        mock_manager.agent_registry = AgentRegistry(tmp_path / "metadata.json")

        orchestrator = DeploymentOrchestrator(manager=mock_manager)
        orchestrator.registry_client = Mock()
        orchestrator.registry_client.resolve_image_digest = AsyncMock(return_value="sha256:test123")
        return orchestrator

    @pytest.fixture
    def sample_agent(self):
        """Create a sample agent."""
        agent = Mock(spec=AgentInfo)
        agent.agent_id = "test-agent"
        agent.name = "Test Agent"
        agent.api_port = 8080
        agent.is_running = True
        return agent

    @pytest.mark.asyncio
    async def test_agent_reaches_work_state_quickly(self, orchestrator, sample_agent):
        """Test successful case where agent reaches WORK state quickly."""
        deployment_id = "test-deploy-1"

        # Register agent with service token so auth works
        orchestrator.manager.agent_registry.register_agent(
            sample_agent.agent_id,
            sample_agent.name,
            sample_agent.api_port,
            "test",
            "test.yml",
            service_token="test-token-123",
        )

        # Mock sleep to speed up tests
        with patch("asyncio.sleep", new_callable=AsyncMock):
            # Mock HTTP responses
            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client_class.return_value.__aenter__.return_value = mock_client

                # Mock auth
                with patch("ciris_manager.agent_auth.get_agent_auth") as mock_auth:
                    mock_auth.return_value.get_auth_headers.return_value = {
                        "Authorization": "Bearer test"
                    }

                    # Create a sequence of responses
                    call_count = 0

                    async def mock_get(url, *args, **kwargs):
                        nonlocal call_count
                        call_count += 1

                        # Check if this is a telemetry call
                        if "telemetry" in url:
                            # Telemetry check - no incidents
                            return Mock(
                                status_code=200, json=lambda: {"data": {"recent_incidents": []}}
                            )

                        # Health checks
                        if call_count == 1:
                            # First health check - WAKEUP
                            return Mock(
                                status_code=200,
                                json=lambda: {
                                    "data": {"cognitive_state": "wakeup", "version": "2.0.0"}
                                },
                            )
                        else:
                            # All subsequent health checks - WORK
                            return Mock(
                                status_code=200,
                                json=lambda: {
                                    "data": {"cognitive_state": "work", "version": "2.0.0"}
                                },
                            )

                    mock_client.get = mock_get

                    # Run health check with short timeouts for testing
                    result = await orchestrator._check_canary_group_health(
                        deployment_id,
                        [sample_agent],
                        "test",
                        wait_for_work_minutes=0.1,  # 6 seconds
                        stability_minutes=0.01,  # 0.6 seconds
                    )

                    assert result[0] is True  # First element is success boolean
                    assert result[1]["successful_agent"] == "test-agent"
                    assert call_count >= 3

    @pytest.mark.asyncio
    async def test_agent_never_reaches_work_state(self, orchestrator, sample_agent):
        """Test timeout when agent never reaches WORK state."""
        deployment_id = "test-deploy-2"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with patch("ciris_manager.agent_auth.get_agent_auth") as mock_auth:
                mock_auth.return_value.get_auth_headers.return_value = {
                    "Authorization": "Bearer test"
                }

                # Always return WAKEUP state
                mock_client.get.return_value = Mock(
                    status_code=200,
                    json=lambda: {"data": {"cognitive_state": "wakeup", "version": "2.0.0"}},
                )

                # Use very short timeout for testing
                result = await orchestrator._check_canary_group_health(
                    deployment_id,
                    [sample_agent],
                    "test",
                    wait_for_work_minutes=0.05,  # 3 seconds
                    stability_minutes=0.01,
                )

                assert result[0] is False  # First element is success boolean

    @pytest.mark.asyncio
    async def test_agent_has_critical_incident_during_stability(self, orchestrator, sample_agent):
        """Test failure when agent has critical incident during stability period."""
        deployment_id = "test-deploy-3"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with patch("ciris_manager.agent_auth.get_agent_auth") as mock_auth:
                mock_auth.return_value.get_auth_headers.return_value = {
                    "Authorization": "Bearer test"
                }

                current_time = datetime.now(timezone.utc)

                # Mock responses
                mock_client.get.side_effect = [
                    # Health check - WORK state
                    Mock(
                        status_code=200,
                        json=lambda: {"data": {"cognitive_state": "work", "version": "2.0.0"}},
                    ),
                    # Telemetry check - has critical incident
                    Mock(
                        status_code=200,
                        json=lambda: {
                            "data": {
                                "recent_incidents": [
                                    {
                                        "severity": "critical",
                                        "timestamp": current_time.isoformat(),
                                        "message": "Memory exhaustion",
                                    }
                                ]
                            }
                        },
                    ),
                ]

                result = await orchestrator._check_canary_group_health(
                    deployment_id,
                    [sample_agent],
                    "test",
                    wait_for_work_minutes=0.1,
                    stability_minutes=0.01,
                )

                # Should fail due to critical incident
                assert result[0] is False  # First element is success boolean

    @pytest.mark.asyncio
    async def test_agent_leaves_work_state(self, orchestrator, sample_agent):
        """Test when agent reaches WORK but then leaves it."""
        deployment_id = "test-deploy-4"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with patch("ciris_manager.agent_auth.get_agent_auth") as mock_auth:
                mock_auth.return_value.get_auth_headers.return_value = {
                    "Authorization": "Bearer test"
                }

                # Sequence: WORK -> SHUTDOWN -> timeout
                call_count = 0

                def get_response(*args, **kwargs):
                    nonlocal call_count
                    call_count += 1

                    if call_count == 1:
                        # First call - WORK state
                        return Mock(
                            status_code=200,
                            json=lambda: {"data": {"cognitive_state": "work", "version": "2.0.0"}},
                        )
                    else:
                        # Subsequent calls - SHUTDOWN state
                        return Mock(
                            status_code=200,
                            json=lambda: {
                                "data": {"cognitive_state": "shutdown", "version": "2.0.0"}
                            },
                        )

                mock_client.get.side_effect = get_response

                result = await orchestrator._check_canary_group_health(
                    deployment_id,
                    [sample_agent],
                    "test",
                    wait_for_work_minutes=0.05,
                    stability_minutes=0.02,
                )

                # Should fail because agent left WORK state
                assert result[0] is False  # First element is success boolean

    @pytest.mark.asyncio
    async def test_network_error_handling(self, orchestrator, sample_agent):
        """Test graceful handling of network errors."""
        deployment_id = "test-deploy-5"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with patch("ciris_manager.agent_auth.get_agent_auth") as mock_auth:
                mock_auth.return_value.get_auth_headers.return_value = {
                    "Authorization": "Bearer test"
                }

                # Simulate network error
                mock_client.get.side_effect = httpx.ConnectError("Connection refused")

                result = await orchestrator._check_canary_group_health(
                    deployment_id,
                    [sample_agent],
                    "test",
                    wait_for_work_minutes=0.05,
                    stability_minutes=0.01,
                )

                # Should fail gracefully
                assert result[0] is False  # First element is success boolean

    @pytest.mark.asyncio
    async def test_multiple_agents_one_succeeds(self, orchestrator):
        """Test with multiple agents where only one reaches WORK state."""
        deployment_id = "test-deploy-6"

        # Create multiple agents
        agent1 = Mock(spec=AgentInfo)
        agent1.agent_id = "agent-1"
        agent1.name = "Agent 1"
        agent1.api_port = 8081
        agent1.is_running = True

        agent2 = Mock(spec=AgentInfo)
        agent2.agent_id = "agent-2"
        agent2.name = "Agent 2"
        agent2.api_port = 8082
        agent2.is_running = True

        # Register agents with service tokens
        orchestrator.manager.agent_registry.register_agent(
            agent1.agent_id,
            agent1.name,
            agent1.api_port,
            "test",
            "test.yml",
            service_token="token1",
        )
        orchestrator.manager.agent_registry.register_agent(
            agent2.agent_id,
            agent2.name,
            agent2.api_port,
            "test",
            "test.yml",
            service_token="token2",
        )

        # Mock asyncio.sleep to speed up test
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client_class.return_value.__aenter__.return_value = mock_client

                with patch("ciris_manager.agent_auth.get_agent_auth") as mock_auth:
                    mock_auth.return_value.get_auth_headers.return_value = {
                        "Authorization": "Bearer test"
                    }

                    def get_response(url, *args, **kwargs):
                        if "8081" in url:
                            # Agent 1 stays in WAKEUP
                            return Mock(
                                status_code=200,
                                json=lambda: {
                                    "data": {"cognitive_state": "wakeup", "version": "2.0.0"}
                                },
                            )
                        elif "8082" in url:
                            if "telemetry" in url:
                                # Agent 2 telemetry - no incidents
                                return Mock(
                                    status_code=200, json=lambda: {"data": {"recent_incidents": []}}
                                )
                            else:
                                # Agent 2 reaches WORK
                                return Mock(
                                    status_code=200,
                                    json=lambda: {
                                        "data": {"cognitive_state": "work", "version": "2.0.0"}
                                    },
                                )

                    mock_client.get.side_effect = get_response

                    result = await orchestrator._check_canary_group_health(
                        deployment_id,
                        [agent1, agent2],
                        "test",
                        wait_for_work_minutes=0.1,
                        stability_minutes=0.01,
                    )

                    # Should succeed because at least one agent reached WORK
                    assert result[0] is True  # First element is success boolean


class TestCanaryDeploymentFlow:
    """Test the complete canary deployment flow with safety checks."""

    @pytest.fixture
    def orchestrator(self, tmp_path):
        """Create deployment orchestrator with mocked dependencies."""
        from ciris_manager.agent_registry import AgentRegistry

        mock_manager = Mock()
        mock_manager.agent_registry = AgentRegistry(tmp_path / "metadata.json")

        orchestrator = DeploymentOrchestrator(manager=mock_manager)
        orchestrator.registry_client = Mock()
        orchestrator.registry_client.resolve_image_digest = AsyncMock(return_value="sha256:test123")

        # Mock the update_agent_group method
        orchestrator._update_agent_group = AsyncMock()

        return orchestrator

    @pytest.fixture
    def canary_agents(self, tmp_path):
        """Create agents in different canary groups."""
        from ciris_manager.agent_registry import AgentRegistry

        registry = AgentRegistry(tmp_path / "metadata.json")

        # Create explorer agent
        explorer = Mock(spec=AgentInfo)
        explorer.agent_id = "explorer-1"
        explorer.name = "Explorer 1"
        explorer.api_port = 8081
        explorer.is_running = True
        explorer.metadata = {"canary_group": "explorer"}

        # Create early adopter agent
        early_adopter = Mock(spec=AgentInfo)
        early_adopter.agent_id = "early-1"
        early_adopter.name = "Early 1"
        early_adopter.api_port = 8082
        early_adopter.is_running = True
        early_adopter.metadata = {"canary_group": "early_adopter"}

        # Create general agent
        general = Mock(spec=AgentInfo)
        general.agent_id = "general-1"
        general.name = "General 1"
        general.api_port = 8083
        general.is_running = True
        general.metadata = {"canary_group": "general"}

        # Register agents
        registry.register_agent(
            explorer.agent_id,
            explorer.name,
            explorer.api_port,
            explorer.metadata.get("template", "test"),
            explorer.metadata.get("compose_file", "test.yml"),
        )
        registry.set_canary_group(explorer.agent_id, "explorer")

        registry.register_agent(
            early_adopter.agent_id,
            early_adopter.name,
            early_adopter.api_port,
            early_adopter.metadata.get("template", "test"),
            early_adopter.metadata.get("compose_file", "test.yml"),
        )
        registry.set_canary_group(early_adopter.agent_id, "early_adopter")

        registry.register_agent(
            general.agent_id,
            general.name,
            general.api_port,
            general.metadata.get("template", "test"),
            general.metadata.get("compose_file", "test.yml"),
        )
        registry.set_canary_group(general.agent_id, "general")

        return [explorer, early_adopter, general], registry

    @pytest.mark.asyncio
    async def test_deployment_aborts_on_explorer_failure(self, orchestrator, canary_agents):
        """Test that deployment aborts if explorer phase fails."""
        agents, registry = canary_agents
        orchestrator.manager.agent_registry = registry

        notification = UpdateNotification(
            agent_image="test:v2", message="Test update", strategy="canary"
        )

        # Mock health check to always fail
        orchestrator._check_canary_group_health = AsyncMock(return_value=False)

        # Mock audit
        with patch("ciris_manager.audit.audit_deployment_action"):
            # Start deployment
            deployment_id = "test-deploy"
            orchestrator.deployments[deployment_id] = DeploymentStatus(
                deployment_id=deployment_id,
                notification=notification,
                status="in_progress",
                message="Starting deployment",
                agents_total=3,
                agents_updated=0,
                agents_deferred=0,
                agents_failed=0,
                started_at=datetime.now(timezone.utc).isoformat(),
            )

            await orchestrator._run_canary_deployment(deployment_id, notification, agents)

            # Check that deployment failed
            status = orchestrator.deployments[deployment_id]
            assert status.status == "failed"
            assert "Explorer phase failed" in status.message

            # Verify health check was called for explorers only
            orchestrator._check_canary_group_health.assert_called_once()
            call_args = orchestrator._check_canary_group_health.call_args[0]
            assert len(call_args[1]) == 1  # Only explorer agent
            assert call_args[1][0].agent_id == "explorer-1"

    @pytest.mark.asyncio
    async def test_deployment_aborts_on_early_adopter_failure(self, orchestrator, canary_agents):
        """Test that deployment aborts if early adopter phase fails."""
        agents, registry = canary_agents
        orchestrator.manager.agent_registry = registry

        notification = UpdateNotification(
            agent_image="test:v2", message="Test update", strategy="canary"
        )

        # Mock health check: explorer succeeds, early adopter fails
        orchestrator._check_canary_group_health = AsyncMock(
            side_effect=[True, False]  # Explorer succeeds, early adopter fails
        )

        with patch("ciris_manager.audit.audit_deployment_action"):
            deployment_id = "test-deploy"
            orchestrator.deployments[deployment_id] = DeploymentStatus(
                deployment_id=deployment_id,
                notification=notification,
                status="in_progress",
                message="Starting deployment",
                agents_total=3,
                agents_updated=0,
                agents_deferred=0,
                agents_failed=0,
                started_at=datetime.now(timezone.utc).isoformat(),
            )

            await orchestrator._run_canary_deployment(deployment_id, notification, agents)

            # Check that deployment failed at early adopter phase
            status = orchestrator.deployments[deployment_id]
            assert status.status == "failed"
            assert "Early adopter phase failed" in status.message

            # Verify both explorer and early adopter health checks were called
            assert orchestrator._check_canary_group_health.call_count == 2

    @pytest.mark.asyncio
    async def test_deployment_continues_on_general_failure(self, orchestrator, canary_agents):
        """Test that deployment continues even if general phase fails."""
        agents, registry = canary_agents
        orchestrator.manager.agent_registry = registry

        notification = UpdateNotification(
            agent_image="test:v2", message="Test update", strategy="canary"
        )

        # Mock health check: explorer and early adopter succeed, general fails
        orchestrator._check_canary_group_health = AsyncMock(
            side_effect=[True, True, False]  # Explorer and early adopter succeed, general fails
        )

        with patch("ciris_manager.audit.audit_deployment_action"):
            deployment_id = "test-deploy"
            orchestrator.deployments[deployment_id] = DeploymentStatus(
                deployment_id=deployment_id,
                notification=notification,
                status="in_progress",
                message="Starting deployment",
                agents_total=3,
                agents_updated=0,
                agents_deferred=0,
                agents_failed=0,
                started_at=datetime.now(timezone.utc).isoformat(),
            )

            await orchestrator._run_canary_deployment(deployment_id, notification, agents)

            # Check that deployment did NOT fail
            status = orchestrator.deployments[deployment_id]
            assert status.status != "failed"

            # Verify all three health checks were called
            assert orchestrator._check_canary_group_health.call_count == 3

    @pytest.mark.asyncio
    async def test_successful_canary_deployment(self, orchestrator, canary_agents):
        """Test successful progression through all canary phases."""
        agents, registry = canary_agents
        orchestrator.manager.agent_registry = registry

        notification = UpdateNotification(
            agent_image="test:v2", message="Test update", strategy="canary"
        )

        # Mock health check to always succeed
        orchestrator._check_canary_group_health = AsyncMock(return_value=True)

        with patch("ciris_manager.audit.audit_deployment_action"):
            deployment_id = "test-deploy"
            orchestrator.deployments[deployment_id] = DeploymentStatus(
                deployment_id=deployment_id,
                notification=notification,
                status="in_progress",
                message="Starting deployment",
                agents_total=3,
                agents_updated=0,
                agents_deferred=0,
                agents_failed=0,
                started_at=datetime.now(timezone.utc).isoformat(),
            )

            await orchestrator._run_canary_deployment(deployment_id, notification, agents)

            # Check that deployment succeeded
            status = orchestrator.deployments[deployment_id]
            assert status.status != "failed"

            # Verify all three phases were checked
            assert orchestrator._check_canary_group_health.call_count == 3

            # Verify update_agent_group was called for all phases
            assert orchestrator._update_agent_group.call_count == 3

    @pytest.mark.asyncio
    async def test_empty_canary_groups(self, orchestrator):
        """Test deployment with no agents assigned to canary groups."""
        notification = UpdateNotification(
            agent_image="test:v2", message="Test update", strategy="canary"
        )

        # Create agents with no canary group assignments
        agents = [
            Mock(spec=AgentInfo, agent_id="agent-1", is_running=True, metadata={}),
            Mock(spec=AgentInfo, agent_id="agent-2", is_running=True, metadata={}),
        ]

        with patch("ciris_manager.audit.audit_deployment_action"):
            deployment_id = "test-deploy"
            orchestrator.deployments[deployment_id] = DeploymentStatus(
                deployment_id=deployment_id,
                notification=notification,
                status="in_progress",
                message="Starting deployment",
                agents_total=3,
                agents_updated=0,
                agents_deferred=0,
                agents_failed=0,
                started_at=datetime.now(timezone.utc).isoformat(),
            )

            await orchestrator._run_canary_deployment(deployment_id, notification, agents)

            # Check that deployment failed due to no canary groups
            status = orchestrator.deployments[deployment_id]
            assert status.status == "failed"
            assert "No agents assigned to canary groups" in status.message
