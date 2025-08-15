"""
Test deployment preview functionality.

Tests that deployments correctly show which agents need updates
and can handle scale with many agents.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from ciris_manager.deployment_orchestrator import DeploymentOrchestrator
from ciris_manager.models import (
    UpdateNotification,
    DeploymentStatus,
    AgentInfo,
)


class TestDeploymentPreview:
    """Test deployment preview functionality."""

    @pytest.mark.asyncio
    async def test_preview_shows_agents_needing_updates(self, tmp_path):
        """Test that preview correctly identifies which agents need updates."""
        orchestrator = DeploymentOrchestrator(tmp_path)

        # Mock manager and registry
        orchestrator.manager = MagicMock()
        orchestrator.manager.agent_registry = MagicMock()

        # Stage a deployment
        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:latest",
            gui_image="ghcr.io/cirisai/ciris-gui:latest",
            strategy="canary",
            message="Test update",
            version="1.4.2",
        )

        # Create deployment status directly since stage_deployment needs agents
        deployment_id = "test-preview-deployment"
        deployment_status = DeploymentStatus(
            deployment_id=deployment_id,
            notification=notification,
            agents_total=3,
            status="pending",
            message="Test deployment",
            staged_at=datetime.now(timezone.utc).isoformat(),
        )
        orchestrator.pending_deployments[deployment_id] = deployment_status

        # Mock agents with different update needs
        mock_agents = [
            AgentInfo(
                agent_id="datum",
                agent_name="Datum",
                container_name="ciris-datum",
                api_port=8001,
                is_running=True,
            ),
            AgentInfo(
                agent_id="sage",
                agent_name="Sage",
                container_name="ciris-sage",
                api_port=8002,
                is_running=True,
            ),
            AgentInfo(
                agent_id="nexus",
                agent_name="Nexus",
                container_name="ciris-nexus",
                api_port=8003,
                is_running=True,
            ),
        ]

        # Mock Docker discovery
        with patch("ciris_manager.docker_discovery.DockerAgentDiscovery") as MockDiscovery:
            mock_discovery = MockDiscovery.return_value
            mock_discovery.discover_agents.return_value = mock_agents

            # Mock auth
            with patch("ciris_manager.agent_auth.get_agent_auth") as mock_auth:
                mock_auth.return_value.get_auth_headers.return_value = {
                    "Authorization": "Bearer test"
                }

                # Mock agent health checks for versions
                with patch("httpx.AsyncClient") as MockClient:
                    mock_client = MockClient.return_value.__aenter__.return_value

                    async def mock_get(url, headers):
                        response = MagicMock()
                        response.status_code = 200

                        if "8001" in url:  # Datum
                            response.json.return_value = {
                                "data": {"version": "1.4.2", "cognitive_state": "work"}
                            }
                        elif "8002" in url:  # Sage
                            response.json.return_value = {
                                "data": {"version": "1.4.1", "cognitive_state": "work"}
                            }
                        else:  # Nexus
                            response.json.return_value = {
                                "data": {"version": "1.4.0", "cognitive_state": "work"}
                            }
                        return response

                    mock_client.get = mock_get

                    # Mock canary groups
                    with patch.object(orchestrator, "_get_agent_canary_group") as mock_group:

                        def get_canary_group(agent_id):
                            if agent_id == "datum":
                                return "early_adopter"
                            elif agent_id == "sage":
                                return "general"
                            else:
                                return "explorer"

                        mock_group.side_effect = get_canary_group

                        # Get preview
                        preview = await orchestrator.get_deployment_preview(deployment_id)

        # Verify preview structure
        assert "error" not in preview
        assert preview["deployment_id"] == deployment_id
        assert preview["version"] == "1.4.2"
        assert preview["total_agents"] == 3
        assert preview["agents_to_update"] == 2  # Sage and Nexus need updates

        # Verify agent details
        agent_details = preview["agent_details"]
        assert len(agent_details) == 3

        # Find each agent in details
        datum = next(a for a in agent_details if a["agent_id"] == "datum")
        sage = next(a for a in agent_details if a["agent_id"] == "sage")
        nexus = next(a for a in agent_details if a["agent_id"] == "nexus")

        # Datum is already updated
        assert datum["needs_update"] is False
        assert datum["status"] == "Up to date"
        assert datum["current_version"] == "1.4.2"
        assert datum["canary_group"] == "early_adopter"

        # Sage needs update
        assert sage["needs_update"] is True
        assert sage["status"] == "Needs update"
        assert sage["current_version"] == "1.4.1"
        assert sage["canary_group"] == "general"

        # Nexus needs update
        assert nexus["needs_update"] is True
        assert nexus["status"] == "Needs update"
        assert nexus["current_version"] == "1.4.0"
        assert nexus["canary_group"] == "explorer"

    @pytest.mark.asyncio
    async def test_preview_scalability_many_agents(self, tmp_path):
        """Test that preview handles many agents efficiently."""
        orchestrator = DeploymentOrchestrator(tmp_path)

        # Mock manager and registry
        orchestrator.manager = MagicMock()
        orchestrator.manager.agent_registry = MagicMock()

        # Stage a deployment
        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:latest",
            strategy="canary",
            message="Large scale update",
            version="2.0.0",
        )

        # Create deployment status directly since stage_deployment needs agents
        deployment_id = "test-preview-deployment"
        deployment_status = DeploymentStatus(
            deployment_id=deployment_id,
            notification=notification,
            agents_total=3,
            status="pending",
            message="Test deployment",
            staged_at=datetime.now(timezone.utc).isoformat(),
        )
        orchestrator.pending_deployments[deployment_id] = deployment_status

        # Create many mock agents (100 agents for scale test)
        mock_agents = []
        for i in range(100):
            mock_agents.append(
                AgentInfo(
                    agent_id=f"agent{i:03d}",
                    agent_name=f"Agent {i:03d}",
                    container_name=f"ciris-agent{i:03d}",
                    api_port=8000 + i,
                    is_running=True,
                )
            )

        # Mock Docker discovery
        with patch("ciris_manager.docker_discovery.DockerAgentDiscovery") as MockDiscovery:
            mock_discovery = MockDiscovery.return_value
            mock_discovery.discover_agents.return_value = mock_agents

            # Mock auth for all agents
            with patch("ciris_manager.agent_auth.get_agent_auth") as mock_auth:
                mock_auth.return_value.get_auth_headers.return_value = {
                    "Authorization": "Bearer test"
                }

                # Mock agent health checks - use fast timeout
                with patch("httpx.AsyncClient") as MockClient:
                    mock_client = MockClient.return_value.__aenter__.return_value

                    async def mock_get(url, headers):
                        response = MagicMock()
                        # Simulate some agents being unreachable
                        port = int(url.split(":")[2].split("/")[0])
                        agent_num = port - 8000

                        if agent_num % 10 == 0:  # Every 10th agent is unreachable
                            raise Exception("Connection timeout")

                        response.status_code = 200
                        response.json.return_value = {
                            "data": {
                                "version": "2.0.0" if agent_num < 30 else "1.9.0",
                                "cognitive_state": "work",
                            }
                        }
                        return response

                    mock_client.get = mock_get

                    # Mock canary groups - distribute agents
                    with patch.object(orchestrator, "_get_agent_canary_group") as mock_group:

                        def get_canary_group(agent_id):
                            num = int(agent_id.replace("agent", ""))
                            if num < 10:
                                return "explorer"
                            elif num < 30:
                                return "early_adopter"
                            else:
                                return "general"

                        mock_group.side_effect = get_canary_group

                        # Time the preview generation
                        import time

                        start = time.time()
                        preview = await orchestrator.get_deployment_preview(deployment_id)
                        elapsed = time.time() - start

        # Verify it completes quickly even with many agents
        assert elapsed < 5.0  # Should complete within 5 seconds

        # Verify preview correctness
        assert preview["total_agents"] == 100
        # 70 agents need updates (agents 30-99)
        # Plus 3 unreachable agents that are at version 2.0.0 (0, 10, 20) are counted as needing updates
        assert preview["agents_to_update"] == 73  # 70 actually need + 3 unreachable but up-to-date
        assert len(preview["agent_details"]) == 100

        # Verify sorting - agents needing updates should be first
        needs_update_count = sum(1 for a in preview["agent_details"][:73] if a["needs_update"])
        assert needs_update_count == 73

        # Verify unknown versions for unreachable agents
        unknown_versions = sum(
            1 for a in preview["agent_details"] if a["current_version"] == "unknown"
        )
        assert unknown_versions == 10  # Every 10th agent was unreachable

    @pytest.mark.asyncio
    async def test_preview_error_handling(self, tmp_path):
        """Test preview handles errors gracefully."""
        orchestrator = DeploymentOrchestrator(tmp_path)

        # Test with non-existent deployment
        preview = await orchestrator.get_deployment_preview("non-existent-id")
        assert preview["error"] == "Deployment not found"

        # Stage deployment but no manager
        notification = UpdateNotification(agent_image="test:latest", message="Test")
        # Create deployment status directly since stage_deployment needs agents
        deployment_id = "test-preview-deployment"
        deployment_status = DeploymentStatus(
            deployment_id=deployment_id,
            notification=notification,
            agents_total=3,
            status="pending",
            message="Test deployment",
            staged_at=datetime.now(timezone.utc).isoformat(),
        )
        orchestrator.pending_deployments[deployment_id] = deployment_status

        # Set manager to None to test error handling
        orchestrator.manager = None

        preview = await orchestrator.get_deployment_preview(deployment_id)
        assert preview["error"] == "Manager not available"

        # Test with manager but discovery fails
        orchestrator.manager = MagicMock()
        orchestrator.manager.agent_registry = MagicMock()

        with patch("ciris_manager.docker_discovery.DockerAgentDiscovery") as MockDiscovery:
            mock_discovery = MockDiscovery.return_value
            mock_discovery.discover_agents.side_effect = Exception("Docker error")

            with pytest.raises(Exception, match="Docker error"):
                await orchestrator.get_deployment_preview(deployment_id)

    @pytest.mark.asyncio
    async def test_preview_shows_canary_deployment_order(self, tmp_path):
        """Test that preview shows the correct deployment order based on canary groups."""
        orchestrator = DeploymentOrchestrator(tmp_path)

        # Mock manager and registry
        orchestrator.manager = MagicMock()
        orchestrator.manager.agent_registry = MagicMock()

        # Stage a deployment
        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:latest",
            strategy="canary",
            message="Test canary deployment",
            version="2.0.0",  # Target version different from current 1.0.0
        )

        # Create deployment status directly since stage_deployment needs agents
        deployment_id = "test-preview-deployment"
        deployment_status = DeploymentStatus(
            deployment_id=deployment_id,
            notification=notification,
            agents_total=3,
            status="pending",
            message="Test deployment",
            staged_at=datetime.now(timezone.utc).isoformat(),
        )
        orchestrator.pending_deployments[deployment_id] = deployment_status

        # Create agents in different canary groups
        mock_agents = [
            AgentInfo(
                agent_id="explorer1",
                agent_name="Explorer 1",
                container_name="ciris-explorer1",
                api_port=8001,
            ),
            AgentInfo(
                agent_id="explorer2",
                agent_name="Explorer 2",
                container_name="ciris-explorer2",
                api_port=8002,
            ),
            AgentInfo(
                agent_id="early1",
                agent_name="Early 1",
                container_name="ciris-early1",
                api_port=8003,
            ),
            AgentInfo(
                agent_id="early2",
                agent_name="Early 2",
                container_name="ciris-early2",
                api_port=8004,
            ),
            AgentInfo(
                agent_id="early3",
                agent_name="Early 3",
                container_name="ciris-early3",
                api_port=8005,
            ),
            AgentInfo(
                agent_id="general1",
                agent_name="General 1",
                container_name="ciris-general1",
                api_port=8006,
            ),
            AgentInfo(
                agent_id="general2",
                agent_name="General 2",
                container_name="ciris-general2",
                api_port=8007,
            ),
        ]

        with patch("ciris_manager.docker_discovery.DockerAgentDiscovery") as MockDiscovery:
            mock_discovery = MockDiscovery.return_value
            mock_discovery.discover_agents.return_value = mock_agents

            with patch("ciris_manager.agent_auth.get_agent_auth") as mock_auth:
                mock_auth.return_value.get_auth_headers.return_value = {
                    "Authorization": "Bearer test"
                }

                with patch("httpx.AsyncClient") as MockClient:
                    mock_client = MockClient.return_value.__aenter__.return_value
                    response = MagicMock()
                    response.status_code = 200
                    response.json.return_value = {
                        "data": {"version": "1.0.0", "cognitive_state": "work"}
                    }
                    mock_client.get = AsyncMock(return_value=response)

                    with patch.object(orchestrator, "_get_agent_canary_group") as mock_group:

                        def get_canary_group(agent_id):
                            if "explorer" in agent_id:
                                return "explorer"
                            elif "early" in agent_id:
                                return "early_adopter"
                            else:
                                return "general"

                        mock_group.side_effect = get_canary_group

                        preview = await orchestrator.get_deployment_preview(deployment_id)

        # Verify all agents need updates
        assert preview["agents_to_update"] == 7

        # Verify agent details are sorted by canary group
        agent_details = preview["agent_details"]

        # Explorers should be first
        assert agent_details[0]["canary_group"] == "explorer"
        assert agent_details[1]["canary_group"] == "explorer"

        # Then early adopters
        assert agent_details[2]["canary_group"] == "early_adopter"
        assert agent_details[3]["canary_group"] == "early_adopter"
        assert agent_details[4]["canary_group"] == "early_adopter"

        # Then general
        assert agent_details[5]["canary_group"] == "general"
        assert agent_details[6]["canary_group"] == "general"
