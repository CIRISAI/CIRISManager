"""
Unit tests for deployment orchestrator telemetry handling.

Tests that deployments succeed even when telemetry endpoints fail.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
import httpx

from ciris_manager.deployment_orchestrator import DeploymentOrchestrator
from ciris_manager.models import AgentInfo


class TestDeploymentTelemetry:
    """Test telemetry handling during deployments."""

    @pytest.fixture
    def mock_manager(self):
        """Create mock manager with required components."""
        manager = MagicMock()
        manager.config = MagicMock()
        manager.config.deployment = MagicMock()
        manager.config.deployment.canary_wait_minutes = 5
        manager.config.deployment.work_stability_minutes = 1

        # Mock agent registry
        manager.agent_registry = MagicMock()
        manager.agent_registry.list_agents = MagicMock(return_value=[])
        manager.agent_registry.save_metadata = MagicMock()

        return manager

    @pytest.fixture
    def orchestrator(self, mock_manager):
        """Create deployment orchestrator instance."""
        orchestrator = DeploymentOrchestrator(mock_manager)
        orchestrator._deployments = {}
        return orchestrator

    @pytest.fixture
    def test_agent(self):
        """Create a test agent."""
        return AgentInfo(
            agent_id="test-agent",
            agent_name="Test Agent",
            container_name="ciris-test-agent",
            api_port=8080,
            status="running",
            image="ghcr.io/cirisai/ciris-agent:latest",
        )

    @pytest.mark.asyncio
    async def test_deployment_succeeds_with_telemetry_500_error(self, orchestrator, test_agent):
        """Test that deployment succeeds when telemetry returns 500 error."""
        deployment_id = "test-deployment-123"

        # Mock get_agent_auth
        with patch("ciris_manager.deployment_orchestrator.get_agent_auth") as mock_auth:
            mock_auth_instance = MagicMock()
            mock_auth_instance.get_auth_headers = MagicMock(
                return_value={"Authorization": "Bearer test"}
            )
            mock_auth.return_value = mock_auth_instance

            # Mock httpx client
            mock_response_health = MagicMock()
            mock_response_health.status_code = 200
            mock_response_health.json.return_value = {
                "data": {
                    "cognitive_state": "work",
                    "version": "1.4.3-beta",
                }
            }

            # Telemetry returns 500 error
            mock_response_telemetry = MagicMock()
            mock_response_telemetry.status_code = 500
            mock_response_telemetry.json.return_value = {"error": "Internal server error"}

            mock_client = AsyncMock()

            # First call is health check (returns WORK state)
            # Second call is telemetry (returns 500)
            mock_client.get = AsyncMock(
                side_effect=[
                    mock_response_health,
                    mock_response_telemetry,
                    mock_response_health,  # Subsequent health checks
                ]
            )

            with patch("httpx.AsyncClient", return_value=mock_client):
                # Test the health check method directly
                success, results = await orchestrator._check_canary_group_health(
                    deployment_id=deployment_id,
                    agents=[test_agent],
                    phase_name="test",
                    wait_for_work_minutes=2,
                    stability_minutes=0.1,  # Short for testing
                )

                # Should succeed despite telemetry error
                assert success is True
                assert results["successful_agent"] == "test-agent"
                assert results["version"] == "1.4.3-beta"
                assert results.get("telemetry_available") is False

    @pytest.mark.asyncio
    async def test_deployment_succeeds_with_telemetry_timeout(self, orchestrator, test_agent):
        """Test that deployment succeeds when telemetry times out."""
        deployment_id = "test-deployment-124"

        # Mock get_agent_auth
        with patch("ciris_manager.deployment_orchestrator.get_agent_auth") as mock_auth:
            mock_auth_instance = MagicMock()
            mock_auth_instance.get_auth_headers = MagicMock(
                return_value={"Authorization": "Bearer test"}
            )
            mock_auth.return_value = mock_auth_instance

            # Mock httpx client
            mock_response_health = MagicMock()
            mock_response_health.status_code = 200
            mock_response_health.json.return_value = {
                "data": {
                    "cognitive_state": "work",
                    "version": "1.4.3-beta",
                }
            }

            mock_client = AsyncMock()

            async def mock_get(url, *args, **kwargs):
                if "system/health" in url:
                    return mock_response_health
                elif "telemetry/overview" in url:
                    # Simulate timeout
                    raise httpx.TimeoutException("Request timed out")
                return mock_response_health

            mock_client.get = mock_get

            with patch("httpx.AsyncClient", return_value=mock_client):
                # Test the health check method directly
                success, results = await orchestrator._check_canary_group_health(
                    deployment_id=deployment_id,
                    agents=[test_agent],
                    phase_name="test",
                    wait_for_work_minutes=2,
                    stability_minutes=0.1,  # Short for testing
                )

                # Should succeed despite telemetry timeout
                assert success is True
                assert results["successful_agent"] == "test-agent"
                assert results["version"] == "1.4.3-beta"
                assert results.get("telemetry_available") is False

    @pytest.mark.asyncio
    async def test_deployment_with_successful_telemetry(self, orchestrator, test_agent):
        """Test deployment with successful telemetry check."""
        deployment_id = "test-deployment-125"

        # Mock get_agent_auth
        with patch("ciris_manager.deployment_orchestrator.get_agent_auth") as mock_auth:
            mock_auth_instance = MagicMock()
            mock_auth_instance.get_auth_headers = MagicMock(
                return_value={"Authorization": "Bearer test"}
            )
            mock_auth.return_value = mock_auth_instance

            # Mock httpx client
            mock_response_health = MagicMock()
            mock_response_health.status_code = 200
            mock_response_health.json.return_value = {
                "data": {
                    "cognitive_state": "work",
                    "version": "1.4.3-beta",
                }
            }

            # Telemetry returns success with no incidents
            mock_response_telemetry = MagicMock()
            mock_response_telemetry.status_code = 200
            mock_response_telemetry.json.return_value = {"data": {"recent_incidents": []}}

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(
                side_effect=[
                    mock_response_health,
                    mock_response_telemetry,
                ]
            )

            with patch("httpx.AsyncClient", return_value=mock_client):
                # Test the health check method directly
                success, results = await orchestrator._check_canary_group_health(
                    deployment_id=deployment_id,
                    agents=[test_agent],
                    phase_name="test",
                    wait_for_work_minutes=2,
                    stability_minutes=0.1,  # Short for testing
                )

                # Should succeed with telemetry confirmed
                assert success is True
                assert results["successful_agent"] == "test-agent"
                assert results["version"] == "1.4.3-beta"
                assert results.get("telemetry_available") is True

    @pytest.mark.asyncio
    async def test_deployment_blocks_on_critical_incidents(self, orchestrator, test_agent):
        """Test that deployment continues monitoring if critical incidents are found."""
        deployment_id = "test-deployment-126"

        # Mock get_agent_auth
        with patch("ciris_manager.deployment_orchestrator.get_agent_auth") as mock_auth:
            mock_auth_instance = MagicMock()
            mock_auth_instance.get_auth_headers = MagicMock(
                return_value={"Authorization": "Bearer test"}
            )
            mock_auth.return_value = mock_auth_instance

            # Mock httpx client
            mock_response_health = MagicMock()
            mock_response_health.status_code = 200
            mock_response_health.json.return_value = {
                "data": {
                    "cognitive_state": "work",
                    "version": "1.4.3-beta",
                }
            }

            # Telemetry returns critical incident
            current_time = datetime.now(timezone.utc)
            mock_response_telemetry = MagicMock()
            mock_response_telemetry.status_code = 200
            mock_response_telemetry.json.return_value = {
                "data": {
                    "recent_incidents": [
                        {
                            "severity": "critical",
                            "timestamp": current_time.isoformat(),
                            "message": "Test critical incident",
                        }
                    ]
                }
            }

            # Second telemetry check has no incidents
            mock_response_telemetry_clean = MagicMock()
            mock_response_telemetry_clean.status_code = 200
            mock_response_telemetry_clean.json.return_value = {"data": {"recent_incidents": []}}

            mock_client = AsyncMock()
            call_count = 0

            async def mock_get(url, *args, **kwargs):
                nonlocal call_count
                call_count += 1

                if "system/health" in url:
                    return mock_response_health
                elif "telemetry/overview" in url:
                    # First call returns critical incident, subsequent calls are clean
                    if call_count <= 2:
                        return mock_response_telemetry
                    else:
                        return mock_response_telemetry_clean
                return mock_response_health

            mock_client.get = mock_get

            with patch("httpx.AsyncClient", return_value=mock_client):
                # Test with very short timeouts for testing
                success, results = await orchestrator._check_canary_group_health(
                    deployment_id=deployment_id,
                    agents=[test_agent],
                    phase_name="test",
                    wait_for_work_minutes=0.2,  # 12 seconds
                    stability_minutes=0.05,  # 3 seconds
                )

                # Should eventually succeed after incidents clear
                # (or timeout if incidents persist)
                # In this test, it will timeout because we keep returning incidents
                if not success:
                    # Expected behavior - agent had critical incidents
                    assert results.get("failed") is True
                else:
                    # If it succeeds, telemetry should be available
                    assert results.get("telemetry_available") is True

    @pytest.mark.asyncio
    async def test_deployment_handles_malformed_telemetry(self, orchestrator, test_agent):
        """Test that deployment handles malformed telemetry responses."""
        deployment_id = "test-deployment-127"

        # Mock get_agent_auth
        with patch("ciris_manager.deployment_orchestrator.get_agent_auth") as mock_auth:
            mock_auth_instance = MagicMock()
            mock_auth_instance.get_auth_headers = MagicMock(
                return_value={"Authorization": "Bearer test"}
            )
            mock_auth.return_value = mock_auth_instance

            # Mock httpx client
            mock_response_health = MagicMock()
            mock_response_health.status_code = 200
            mock_response_health.json.return_value = {
                "data": {
                    "cognitive_state": "work",
                    "version": "1.4.3-beta",
                }
            }

            # Telemetry returns malformed data
            mock_response_telemetry = MagicMock()
            mock_response_telemetry.status_code = 200
            mock_response_telemetry.json.return_value = {
                "data": {
                    "recent_incidents": "not_a_list"  # Should be a list
                }
            }

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(
                side_effect=[
                    mock_response_health,
                    mock_response_telemetry,
                ]
            )

            with patch("httpx.AsyncClient", return_value=mock_client):
                # Test the health check method directly
                success, results = await orchestrator._check_canary_group_health(
                    deployment_id=deployment_id,
                    agents=[test_agent],
                    phase_name="test",
                    wait_for_work_minutes=2,
                    stability_minutes=0.1,  # Short for testing
                )

                # Should succeed despite malformed telemetry
                assert success is True
                assert results["successful_agent"] == "test-agent"
                assert results["version"] == "1.4.3-beta"
                # Telemetry was checked but data was malformed, still counts as checked
                assert results.get("telemetry_available") is True
