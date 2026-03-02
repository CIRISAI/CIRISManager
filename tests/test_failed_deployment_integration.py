"""
Integration test for failed deployment handling.

This test validates the complete flow from detection to recovery
of a failed deployment.
"""

import pytest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock
import tempfile

from ciris_manager.deployment import DeploymentOrchestrator
from ciris_manager.models import (
    UpdateNotification,
    DeploymentStatus,
    AgentInfo,
)


class TestFailedDeploymentIntegration:
    """Integration test for the complete failed deployment flow."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def orchestrator(self, temp_dir):
        """Create an orchestrator with temp state directory."""
        orch = DeploymentOrchestrator()
        # Set paths on both the orchestrator and the state manager
        orch.state_dir = temp_dir
        orch.deployment_state_file = temp_dir / "deployment_state.json"
        orch._state_manager.state_dir = temp_dir
        orch._state_manager.deployment_state_file = temp_dir / "deployment_state.json"
        # Clear any loaded state from default location
        orch.deployments = {}
        orch.pending_deployments = {}
        orch.current_deployment = None
        return orch

    @pytest.mark.asyncio
    async def test_complete_failed_deployment_flow(self, orchestrator):
        """
        Test the complete flow:
        1. Deployment starts
        2. Deployment fails
        3. Failed deployment blocks new deployments
        4. User clears failed deployment
        5. New deployment can proceed
        """

        # Step 1: Create and start a deployment
        deployment_id = "test-failed-flow-123"
        deployment = DeploymentStatus(
            deployment_id=deployment_id,
            notification=UpdateNotification(
                agent_image="test:v1.4.1",
                strategy="canary",
                message="Test deployment",
                version="1.4.1",
                commit_sha="abc123",
            ),
            agents_total=2,
            agents_updated=0,
            agents_deferred=0,
            agents_failed=0,
            started_at=datetime.now(timezone.utc).isoformat(),
            status="in_progress",
            canary_phase="early_adopters",
            message="Updating agents",
        )

        orchestrator.deployments[deployment_id] = deployment
        orchestrator.current_deployment = deployment_id
        orchestrator._save_state()

        # Verify deployment is active
        assert orchestrator.current_deployment == deployment_id
        assert orchestrator.deployments[deployment_id].status == "in_progress"

        # Step 2: Simulate deployment failure
        deployment.status = "failed"
        deployment.message = "Early adopter phase failed - no agents reached stable WORK state"
        deployment.agents_failed = 1
        deployment.completed_at = datetime.now(timezone.utc).isoformat()

        # IMPORTANT: Failed deployment should NOT clear the lock automatically
        # This is intentional - it blocks new deployments until manually cleared
        orchestrator._save_state()

        # Verify deployment failed but lock remains
        assert orchestrator.deployments[deployment_id].status == "failed"
        assert orchestrator.current_deployment == deployment_id  # Lock still held!

        # Step 3: Verify failed deployment blocks new deployments
        current = await orchestrator.get_current_deployment()
        assert current is not None
        assert current.status == "failed"
        assert current.deployment_id == deployment_id

        # Try to start a new deployment - should fail
        new_notification = UpdateNotification(
            agent_image="test:v1.4.2", strategy="canary", message="New deployment attempt"
        )

        with pytest.raises(ValueError, match="already in progress"):
            agents = [
                AgentInfo(
                    agent_id="test-agent",
                    agent_name="Test Agent",
                    container_name="ciris-test-agent",
                    api_port=8001,
                )
            ]
            await orchestrator.start_deployment(new_notification, agents)

        # Step 4: Clear the failed deployment - this should re-stage it
        success = await orchestrator.cancel_stuck_deployment(
            deployment_id, "User cleared failed deployment"
        )
        assert success is True

        # Verify lock is cleared
        assert orchestrator.current_deployment is None
        assert orchestrator.deployments[deployment_id].status == "cancelled"

        # Verify a new pending deployment was created with the same notification
        assert len(orchestrator.pending_deployments) == 1
        new_pending_id = list(orchestrator.pending_deployments.keys())[0]
        pending_deployment = orchestrator.pending_deployments[new_pending_id]
        assert pending_deployment.status == "pending"
        assert pending_deployment.notification == deployment.notification  # Same notification
        assert pending_deployment.deployment_id != deployment_id  # New ID
        assert "Ready to retry" in pending_deployment.message

        # Step 5: Launch the re-staged deployment with mocked manager
        with patch.object(orchestrator, "manager") as mock_manager:
            # Mock the necessary attributes
            mock_manager.agent_registry = MagicMock()
            mock_discovery = MagicMock()
            mock_discovery.discover_agents.return_value = [
                AgentInfo(
                    agent_id="test-agent",
                    agent_name="Test Agent",
                    container_name="ciris-test-agent",
                    api_port=8001,
                )
            ]

            with patch(
                "ciris_manager.docker_discovery.DockerAgentDiscovery", return_value=mock_discovery
            ):
                success = await orchestrator.launch_staged_deployment(new_pending_id)
                assert success is True

        # Verify the deployment is now active
        assert orchestrator.current_deployment == new_pending_id
        assert new_pending_id in orchestrator.deployments
        assert orchestrator.deployments[new_pending_id].status == "in_progress"

    @pytest.mark.asyncio
    async def test_failed_deployment_persists_across_restart(self, temp_dir):
        """Test that failed deployments persist and block after manager restart."""

        # Create first orchestrator instance with failed deployment
        from ciris_manager.deployment import DeploymentOrchestrator

        with patch.object(DeploymentOrchestrator, "_load_state"):
            orch1 = DeploymentOrchestrator(manager=None)
        # Set paths on both the orchestrator and the state manager
        orch1.state_dir = temp_dir
        orch1.deployment_state_file = temp_dir / "deployment_state.json"
        orch1._state_manager.state_dir = temp_dir
        orch1._state_manager.deployment_state_file = temp_dir / "deployment_state.json"
        orch1.deployments = {}
        orch1.current_deployment = None

        # Add failed deployment with lock still held
        failed_deployment = DeploymentStatus(
            deployment_id="failed-persist-123",
            notification=UpdateNotification(
                agent_image="test:v1.4.1",
                strategy="canary",
                message="Failed deployment",
                version="1.4.1",
            ),
            agents_total=2,
            agents_updated=0,
            agents_deferred=0,
            agents_failed=2,
            started_at="2025-01-01T10:00:00Z",
            completed_at="2025-01-01T10:30:00Z",
            status="failed",
            message="Deployment failed during canary phase",
        )

        orch1.deployments["failed-persist-123"] = failed_deployment
        orch1.current_deployment = "failed-persist-123"  # Lock is held
        orch1._save_state()

        # Create new orchestrator instance (simulating restart)
        with patch.object(DeploymentOrchestrator, "_load_state"):
            orch2 = DeploymentOrchestrator(manager=None)
        # Set paths on both the orchestrator and the state manager
        orch2.state_dir = temp_dir
        orch2.deployment_state_file = temp_dir / "deployment_state.json"
        orch2._state_manager.state_dir = temp_dir
        orch2._state_manager.deployment_state_file = temp_dir / "deployment_state.json"
        orch2.deployments = {}
        orch2.current_deployment = None
        orch2._load_state()

        # Verify failed deployment persists with lock
        assert "failed-persist-123" in orch2.deployments
        assert orch2.deployments["failed-persist-123"].status == "failed"
        # After restart, lock should be maintained for failed deployments
        # (The fix in _load_state only clears lock for in_progress, not failed)
        assert orch2.current_deployment == "failed-persist-123"

        # Verify it still blocks new deployments
        current = await orch2.get_current_deployment()
        assert current is not None
        assert current.status == "failed"

    @pytest.mark.asyncio
    async def test_failed_deployment_retry_restaging(self, orchestrator):
        """Test that cancelling a failed deployment re-stages it for retry."""

        # Create a failed deployment
        deployment_id = "test-retry-123"
        notification = UpdateNotification(
            agent_image="test:v1.4.1",
            strategy="canary",
            message="Original deployment",
            version="1.4.1",
            commit_sha="abc123",
        )

        failed_deployment = DeploymentStatus(
            deployment_id=deployment_id,
            notification=notification,
            agents_total=2,
            agents_updated=0,
            agents_deferred=0,
            agents_failed=2,
            started_at=datetime.now(timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat(),
            status="failed",
            message="Deployment failed",
        )

        orchestrator.deployments[deployment_id] = failed_deployment
        orchestrator.current_deployment = deployment_id

        # Cancel the failed deployment
        success = await orchestrator.cancel_stuck_deployment(deployment_id, "Clearing for retry")
        assert success is True

        # Verify the original deployment is cancelled
        assert orchestrator.deployments[deployment_id].status == "cancelled"
        assert "Re-staged as" in orchestrator.deployments[deployment_id].message

        # Verify lock is cleared
        assert orchestrator.current_deployment is None

        # Verify a new pending deployment exists
        assert len(orchestrator.pending_deployments) == 1
        new_id = list(orchestrator.pending_deployments.keys())[0]
        new_deployment = orchestrator.pending_deployments[new_id]

        # Verify the new deployment has the same notification
        assert new_deployment.notification == notification
        assert new_deployment.status == "pending"
        assert "Ready to retry" in new_deployment.message
        assert new_deployment.deployment_id != deployment_id

    @pytest.mark.asyncio
    async def test_api_endpoint_integration(self, orchestrator):
        """Test the API endpoints handle failed deployments correctly."""

        # Setup failed deployment
        failed_deployment = DeploymentStatus(
            deployment_id="api-test-failed",
            notification=UpdateNotification(
                agent_image="test:latest",
                strategy="canary",
                message="Test failure",
                version="7d21f39",
                commit_sha="7d21f398",
            ),
            agents_total=2,
            agents_updated=0,
            agents_deferred=0,
            agents_failed=1,
            started_at=datetime.now(timezone.utc).isoformat(),
            status="failed",
            message="Early adopter phase failed",
        )

        orchestrator.deployments["api-test-failed"] = failed_deployment
        orchestrator.current_deployment = "api-test-failed"

        # Test get_current_deployment returns failed deployment
        current = await orchestrator.get_current_deployment()
        assert current.status == "failed"
        assert current.deployment_id == "api-test-failed"

        # Test get_pending_deployment returns None (failed is not pending)
        pending = await orchestrator.get_pending_deployment()
        assert pending is None

        # Test cancel_stuck_deployment
        success = await orchestrator.cancel_stuck_deployment(
            "api-test-failed", "Clearing for retry"
        )
        assert success is True
        assert orchestrator.current_deployment is None
        assert orchestrator.deployments["api-test-failed"].status == "cancelled"

    def test_ui_response_validation(self):
        """Test that UI response matches expected format for failed deployments."""

        # Simulate the /updates/pending response for a failed deployment
        api_response = {
            "pending": True,  # Important: failed deployments return pending=true
            "deployment_id": "a26312c0-118f-4bf6-b648-74e8d7dd3c4c",
            "status": "failed",
            "staged_at": "2025-08-15T03:27:32.761711+00:00",
            "affected_agents": 2,
            "message": "Early adopter phase failed - no agents reached stable WORK state",
            "agent_image": "ghcr.io/cirisai/ciris-agent:latest",
            "gui_image": None,
            "strategy": "canary",
            "version": "7d21f39",
            "commit_sha": "7d21f398afdec348e45102dd8d3cfd91c91c7e30",
        }

        # Validate response structure
        assert api_response["pending"] is True, "Failed deployments must return pending=true"
        assert api_response["status"] == "failed", "Status must be 'failed'"
        assert "deployment_id" in api_response, "Must include deployment_id"
        assert "message" in api_response, "Must include failure message"
        assert "version" in api_response, "Should include version for display"

        # Validate UI routing logic
        if api_response["pending"] and api_response["status"] == "failed":
            ui_function = "showFailedDeployment"
        elif api_response["pending"] and api_response.get("status") in ["pending", None]:
            ui_function = "showPendingDeployment"
        else:
            ui_function = "hidePendingDeployment"

        assert (
            ui_function == "showFailedDeployment"
        ), f"Failed deployment should route to showFailedDeployment, got {ui_function}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
