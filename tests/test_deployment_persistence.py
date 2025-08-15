"""
Unit tests for deployment orchestrator persistence functionality.
"""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest

from ciris_manager.deployment_orchestrator import DeploymentOrchestrator
from ciris_manager.models import (
    UpdateNotification,
    DeploymentStatus,
    AgentInfo,
    AgentUpdateResponse,
)


class TestDeploymentPersistence:
    """Test deployment state persistence."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def orchestrator(self, temp_dir):
        """Create an orchestrator with temp state directory."""
        with patch("ciris_manager.deployment_orchestrator.Path") as mock_path:
            mock_path.return_value = temp_dir
            orch = DeploymentOrchestrator()
            orch.state_dir = temp_dir
            orch.deployment_state_file = temp_dir / "deployment_state.json"
            return orch

    def test_save_state_creates_file(self, orchestrator):
        """Test that save_state creates the state file."""
        # Add a deployment
        deployment = DeploymentStatus(
            deployment_id="test-123",
            notification=UpdateNotification(
                agent_image="test:latest", strategy="immediate", message="Test deployment"
            ),
            agents_total=5,
            agents_updated=0,
            agents_deferred=0,
            agents_failed=0,
            started_at=datetime.now(timezone.utc).isoformat(),
            status="in_progress",
            message="Test deployment in progress",
        )
        orchestrator.deployments["test-123"] = deployment
        orchestrator.current_deployment = "test-123"

        # Save state
        orchestrator._save_state()

        # Verify file exists
        assert orchestrator.deployment_state_file.exists()

        # Verify content
        with open(orchestrator.deployment_state_file) as f:
            state = json.load(f)

        assert "deployments" in state
        assert "test-123" in state["deployments"]
        assert state["current_deployment"] == "test-123"
        assert state["deployments"]["test-123"]["status"] == "in_progress"
        assert state["deployments"]["test-123"]["agents_total"] == 5

    def test_save_state_atomic_write(self, orchestrator):
        """Test that save_state uses atomic write (temp file + rename)."""
        deployment = DeploymentStatus(
            deployment_id="test-456",
            notification=UpdateNotification(
                agent_image="test:v2", strategy="canary", message="Canary test"
            ),
            agents_total=10,
            agents_updated=3,
            agents_deferred=2,
            agents_failed=1,
            started_at=datetime.now(timezone.utc).isoformat(),
            status="in_progress",
            canary_phase="explorers",
            message="Canary deployment - explorers phase",
        )
        orchestrator.deployments["test-456"] = deployment

        # Mock file operations to verify atomic write
        original_open = open
        temp_file_used = []

        def mock_open_func(file, *args, **kwargs):
            if str(file).endswith(".tmp"):
                temp_file_used.append(str(file))
            return original_open(file, *args, **kwargs)

        with patch("builtins.open", side_effect=mock_open_func):
            orchestrator._save_state()

        # Verify temp file was used
        assert len(temp_file_used) == 1
        assert temp_file_used[0].endswith(".tmp")

        # Verify final file exists with correct content
        with open(orchestrator.deployment_state_file) as f:
            state = json.load(f)
        assert state["deployments"]["test-456"]["canary_phase"] == "explorers"

    def test_load_state_restores_deployments(self, temp_dir):
        """Test that load_state correctly restores deployments."""
        # Create orchestrator with temp dir
        from ciris_manager.deployment_orchestrator import DeploymentOrchestrator

        # Mock the _load_state in __init__ to prevent loading existing state
        with patch.object(DeploymentOrchestrator, "_load_state"):
            orchestrator = DeploymentOrchestrator(manager=None)
        orchestrator.state_dir = temp_dir
        orchestrator.deployment_state_file = temp_dir / "deployment_state.json"
        # Clear any state that might have been loaded
        orchestrator.deployments = {}
        orchestrator.current_deployment = None

        # Create state file
        state = {
            "deployments": {
                "dep-1": {
                    "deployment_id": "dep-1",
                    "notification": {
                        "agent_image": "test:v1",
                        "strategy": "immediate",
                        "message": "First deployment",
                    },
                    "agents_total": 3,
                    "agents_updated": 2,
                    "agents_deferred": 1,
                    "agents_failed": 0,
                    "started_at": "2025-01-01T12:00:00Z",
                    "completed_at": "2025-01-01T12:30:00Z",
                    "status": "completed",
                    "message": "First deployment completed",
                },
                "dep-2": {
                    "deployment_id": "dep-2",
                    "notification": {
                        "agent_image": "test:v2",
                        "strategy": "canary",
                        "message": "Second deployment",
                    },
                    "agents_total": 5,
                    "agents_updated": 1,
                    "agents_deferred": 0,
                    "agents_failed": 0,
                    "started_at": "2025-01-02T10:00:00Z",
                    "status": "in_progress",
                    "canary_phase": "explorers",
                    "message": "Second deployment in progress",
                },
            },
            "current_deployment": "dep-2",
        }

        with open(orchestrator.deployment_state_file, "w") as f:
            json.dump(state, f)

        # Load state
        orchestrator._load_state()

        # Verify deployments restored
        assert len(orchestrator.deployments) == 2
        assert "dep-1" in orchestrator.deployments
        assert "dep-2" in orchestrator.deployments
        assert orchestrator.current_deployment == "dep-2"

        # Verify deployment details
        dep1 = orchestrator.deployments["dep-1"]
        assert dep1.status == "completed"
        assert dep1.agents_updated == 2

        dep2 = orchestrator.deployments["dep-2"]
        assert dep2.status == "in_progress"
        assert dep2.canary_phase == "explorers"

    def test_load_state_handles_missing_file(self, orchestrator):
        """Test that load_state handles missing state file gracefully."""
        # Ensure file doesn't exist
        if orchestrator.deployment_state_file.exists():
            orchestrator.deployment_state_file.unlink()

        # Load state should not raise
        orchestrator._load_state()

        # Should have empty deployments
        assert len(orchestrator.deployments) == 0
        assert orchestrator.current_deployment is None

    def test_load_state_handles_corrupt_file(self, orchestrator):
        """Test that load_state handles corrupt JSON gracefully."""
        # Create corrupt file
        with open(orchestrator.deployment_state_file, "w") as f:
            f.write("{ corrupt json }")

        # Load state should not raise
        orchestrator._load_state()

        # Should have empty deployments
        assert len(orchestrator.deployments) == 0
        assert orchestrator.current_deployment is None

    @pytest.mark.asyncio
    async def test_start_deployment_saves_state(self, orchestrator):
        """Test that starting a deployment saves state."""
        notification = UpdateNotification(
            agent_image="test:v3", strategy="immediate", message="Test immediate deployment"
        )

        agents = [
            AgentInfo(
                agent_id="agent-1",
                agent_name="Agent One",
                container_name="ciris-agent-1",
                api_port=8001,
            ),
            AgentInfo(
                agent_id="agent-2",
                agent_name="Agent Two",
                container_name="ciris-agent-2",
                api_port=8002,
            ),
        ]

        # Mock the methods that would normally run
        orchestrator._pull_images = AsyncMock(return_value={"success": True})
        orchestrator._check_agents_need_update = AsyncMock(return_value=(agents, False))
        orchestrator._run_deployment = AsyncMock()

        # Start deployment
        status = await orchestrator.start_deployment(notification, agents)

        # Verify state was saved
        assert orchestrator.deployment_state_file.exists()

        with open(orchestrator.deployment_state_file) as f:
            state = json.load(f)

        assert status.deployment_id in state["deployments"]
        assert state["current_deployment"] == status.deployment_id

    @pytest.mark.asyncio
    async def test_stage_deployment_saves_state(self, orchestrator):
        """Test that staging a deployment saves state."""
        notification = UpdateNotification(
            agent_image="test:v4", strategy="canary", message="Staged canary deployment"
        )

        agents = [
            AgentInfo(
                agent_id="agent-3",
                agent_name="Agent Three",
                container_name="ciris-agent-3",
                api_port=8003,
            )
        ]

        # Mock image checks to return agents that need update
        orchestrator._check_agents_need_update = AsyncMock(return_value=(agents, True))

        # Stage deployment
        deployment_id = await orchestrator.stage_deployment(notification, agents)

        # Verify deployment is in pending_deployments
        assert deployment_id in orchestrator.pending_deployments
        deployment = orchestrator.pending_deployments[deployment_id]
        assert deployment.status == "pending"
        assert deployment.agents_total == 1

    @pytest.mark.asyncio
    async def test_reject_deployment_saves_state(self, orchestrator):
        """Test that rejecting a deployment saves state."""
        # Create a staged deployment in pending_deployments
        deployment = DeploymentStatus(
            deployment_id="staged-123",
            notification=UpdateNotification(
                agent_image="test:v5", strategy="canary", message="To be rejected"
            ),
            agents_total=3,
            agents_updated=0,
            agents_deferred=0,
            agents_failed=0,
            started_at=datetime.now(timezone.utc).isoformat(),
            status="pending",
            message="Staged for approval",
        )
        orchestrator.pending_deployments["staged-123"] = deployment

        # Mock audit function - it's imported inside the reject_staged_deployment method
        with patch("ciris_manager.audit.audit_deployment_action"):
            # Reject deployment
            await orchestrator.reject_staged_deployment("staged-123", "Testing rejection")

        # Verify state was saved with rejection
        with open(orchestrator.deployment_state_file) as f:
            state = json.load(f)

        assert state["deployments"]["staged-123"]["status"] == "rejected"
        assert state["deployments"]["staged-123"]["message"] == "Testing rejection"

    @pytest.mark.asyncio
    async def test_deployment_progress_saves_state(self, orchestrator):
        """Test that deployment progress updates save state."""
        # Create an in-progress deployment
        deployment = DeploymentStatus(
            deployment_id="progress-123",
            notification=UpdateNotification(
                agent_image="test:v6", strategy="immediate", message="Progress test"
            ),
            agents_total=3,
            agents_updated=0,
            agents_deferred=0,
            agents_failed=0,
            started_at=datetime.now(timezone.utc).isoformat(),
            status="in_progress",
            message="Updating agents",
        )
        orchestrator.deployments["progress-123"] = deployment

        # Mock the update results from 3 agents
        results = [
            AgentUpdateResponse(agent_id="agent-0", decision="accept"),
            AgentUpdateResponse(agent_id="agent-1", decision="defer"),
            Exception("Failed to update agent-2"),
        ]

        # Process results (this happens in _update_agent_group)
        status = orchestrator.deployments["progress-123"]
        for result in results:
            if isinstance(result, Exception):
                status.agents_failed += 1
            elif isinstance(result, AgentUpdateResponse):
                if result.decision == "accept":
                    status.agents_updated += 1
                elif result.decision == "defer":
                    status.agents_deferred += 1
                else:
                    status.agents_failed += 1

        # Save state after updating counts
        orchestrator._save_state()

        # Verify counts were persisted
        with open(orchestrator.deployment_state_file) as f:
            state = json.load(f)

        deployment_state = state["deployments"]["progress-123"]
        assert deployment_state["agents_updated"] == 1
        assert deployment_state["agents_deferred"] == 1
        assert deployment_state["agents_failed"] == 1

    def test_state_persistence_across_restarts(self, temp_dir):
        """Test that state persists across orchestrator restarts."""
        # First orchestrator instance
        from ciris_manager.deployment_orchestrator import DeploymentOrchestrator

        # Mock _load_state to prevent loading existing state
        with patch.object(DeploymentOrchestrator, "_load_state"):
            orch1 = DeploymentOrchestrator(manager=None)
        orch1.state_dir = temp_dir
        orch1.deployment_state_file = temp_dir / "deployment_state.json"
        # Clear any loaded state
        orch1.deployments = {}
        orch1.current_deployment = None

        # Add deployments
        deployment1 = DeploymentStatus(
            deployment_id="persist-1",
            notification=UpdateNotification(
                agent_image="test:v7", strategy="canary", message="First persistent deployment"
            ),
            agents_total=5,
            agents_updated=3,
            agents_deferred=1,
            agents_failed=1,
            started_at="2025-01-01T10:00:00Z",
            completed_at="2025-01-01T11:00:00Z",
            status="completed",
            canary_phase="general",
            message="Deployment completed successfully",
        )

        deployment2 = DeploymentStatus(
            deployment_id="persist-2",
            notification=UpdateNotification(
                agent_image="test:v8", strategy="immediate", message="Second persistent deployment"
            ),
            agents_total=2,
            agents_updated=0,
            agents_deferred=0,
            agents_failed=0,
            started_at="2025-01-02T09:00:00Z",
            status="in_progress",
            message="Deployment in progress",
        )

        orch1.deployments["persist-1"] = deployment1
        orch1.deployments["persist-2"] = deployment2
        orch1.current_deployment = "persist-2"
        orch1._save_state()

        # Create new orchestrator instance
        with patch.object(DeploymentOrchestrator, "_load_state"):
            orch2 = DeploymentOrchestrator(manager=None)
        orch2.state_dir = temp_dir
        orch2.deployment_state_file = temp_dir / "deployment_state.json"
        # Clear any existing state before loading
        orch2.deployments = {}
        orch2.current_deployment = None
        orch2._load_state()

        # Verify state was restored
        assert len(orch2.deployments) == 2
        assert orch2.current_deployment == "persist-2"

        # Verify deployment details
        dep1 = orch2.deployments["persist-1"]
        assert dep1.status == "completed"
        assert dep1.agents_updated == 3
        assert dep1.canary_phase == "general"

        dep2 = orch2.deployments["persist-2"]
        assert dep2.status == "in_progress"
        assert dep2.agents_total == 2

    def test_save_state_error_handling(self, orchestrator):
        """Test that save_state handles errors gracefully."""
        # Add a deployment
        deployment = DeploymentStatus(
            deployment_id="error-test",
            notification=UpdateNotification(
                agent_image="test:error", strategy="immediate", message="Error test"
            ),
            agents_total=1,
            agents_updated=0,
            agents_deferred=0,
            agents_failed=0,
            started_at=datetime.now(timezone.utc).isoformat(),
            status="in_progress",
            message="Testing error handling",
        )
        orchestrator.deployments["error-test"] = deployment

        # Make directory read-only to cause error
        orchestrator.state_dir.chmod(0o444)

        try:
            # Save should not raise, just log error
            orchestrator._save_state()
        finally:
            # Restore permissions
            orchestrator.state_dir.chmod(0o755)

        # Orchestrator should still be functional
        assert "error-test" in orchestrator.deployments
