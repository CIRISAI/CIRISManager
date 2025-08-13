"""
Unit tests for deployment and version tracking collectors.

Tests the DeploymentCollector and VersionCollector implementations.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, AsyncMock

from ciris_manager.telemetry.collectors.deployment_collector import (
    DeploymentCollector,
    VersionCollector,
)
from ciris_manager.telemetry.schemas import (
    DeploymentStatus,
    DeploymentPhase,
    ComponentType,
)


class TestDeploymentCollector:
    """Test DeploymentCollector functionality."""

    @pytest.fixture
    def mock_deployment_state(self):
        """Create mock deployment state matching DeploymentStatus from models."""
        now = datetime.now(timezone.utc)

        state = Mock()
        state.deployment_id = "deploy-123"
        state.status = "in_progress"
        state.canary_phase = "explorers"  # Matches actual field name
        state.agent_image = "ghcr.io/cirisai/ciris-agent:v1.4.0"
        state.gui_image = "ghcr.io/cirisai/ciris-gui:v1.2.0"
        state.agents_total = 5
        state.agents_staged = 5
        state.agents_updated = 2
        state.agents_failed = 0
        state.agents_deferred = 1
        state.created_at = now.isoformat()
        state.staged_at = now.isoformat()
        state.started_at = now.isoformat()
        state.completed_at = None
        state.initiated_by = "github-actions"
        state.message = "Deployment in progress"
        state.is_rollback = False
        state.rollback_from_deployment = None

        return state

    @pytest.fixture
    def mock_manager(self, mock_deployment_state):
        """Create a mock manager with deployment orchestrator."""
        manager = Mock()

        # Mock deployment orchestrator
        orchestrator = Mock()
        orchestrator.current_deployment = "deploy-123"
        orchestrator.deployments = {"deploy-123": mock_deployment_state}
        orchestrator.pending_deployments = {}

        manager.deployment_orchestrator = orchestrator

        return manager

    @pytest.mark.asyncio
    async def test_initialization(self, mock_manager):
        """Test collector initialization."""
        collector = DeploymentCollector(mock_manager)

        assert collector.name == "DeploymentCollector"
        assert collector.timeout_seconds == 5
        assert collector.manager == mock_manager

    @pytest.mark.asyncio
    async def test_is_available(self, mock_manager):
        """Test availability check."""
        # With proper manager
        collector = DeploymentCollector(mock_manager)
        is_available = await collector.is_available()
        assert is_available is True

        # Without manager
        collector = DeploymentCollector(None)
        is_available = await collector.is_available()
        assert is_available is False

        # With manager but no orchestrator
        manager_no_orch = Mock(spec=[])  # Empty spec means no attributes
        collector = DeploymentCollector(manager_no_orch)
        is_available = await collector.is_available()
        assert is_available is False

    @pytest.mark.asyncio
    async def test_collect_active_deployment(self, mock_manager):
        """Test collecting active deployment metrics."""
        collector = DeploymentCollector(mock_manager)

        metrics = await collector.collect()

        assert len(metrics) == 1
        metric = metrics[0]

        assert metric.deployment_id == "deploy-123"
        assert metric.status == DeploymentStatus.IN_PROGRESS
        assert metric.phase == DeploymentPhase.EXPLORERS
        assert metric.agent_image == "ghcr.io/cirisai/ciris-agent:v1.4.0"
        assert metric.gui_image == "ghcr.io/cirisai/ciris-gui:v1.2.0"
        assert metric.agents_total == 5
        assert metric.agents_updated == 2
        assert metric.agents_deferred == 1

    @pytest.mark.asyncio
    async def test_collect_no_deployment(self):
        """Test collecting when no active deployment."""
        manager = Mock()
        orchestrator = Mock()
        orchestrator.current_deployment = None
        orchestrator.deployments = {}
        orchestrator.pending_deployments = {}
        manager.deployment_orchestrator = orchestrator

        collector = DeploymentCollector(manager)
        metrics = await collector.collect()

        assert metrics == []

    @pytest.mark.asyncio
    async def test_collect_completed_deployment(self, mock_manager):
        """Test collecting completed deployment."""
        now = datetime.now(timezone.utc)

        # Modify the deployment to be completed
        deployment = mock_manager.deployment_orchestrator.deployments["deploy-123"]
        deployment.status = "completed"
        deployment.canary_phase = "complete"
        deployment.completed_at = now.isoformat()
        deployment.agents_updated = 5

        collector = DeploymentCollector(mock_manager)
        metrics = await collector.collect()

        assert len(metrics) == 1
        assert metrics[0].status == DeploymentStatus.COMPLETED
        assert metrics[0].phase == DeploymentPhase.COMPLETE
        assert metrics[0].agents_updated == 5

    @pytest.mark.asyncio
    async def test_collect_rollback_deployment(self, mock_manager):
        """Test collecting rollback deployment."""
        # Modify deployment to be a rollback
        deployment = mock_manager.deployment_orchestrator.deployments["deploy-123"]
        deployment.status = "rolling_back"
        deployment.is_rollback = True
        deployment.rollback_from_deployment = "deploy-122"
        deployment.agent_image = "ghcr.io/cirisai/ciris-agent:v1.3.0"

        collector = DeploymentCollector(mock_manager)
        metrics = await collector.collect()

        assert len(metrics) == 1
        assert metrics[0].status == DeploymentStatus.ROLLING_BACK
        assert metrics[0].is_rollback is True
        assert metrics[0].rollback_from_deployment == "deploy-122"

    @pytest.mark.asyncio
    async def test_handle_missing_fields(self, mock_manager):
        """Test handling deployment with missing fields."""
        # Create deployment with minimal fields
        minimal_deployment = Mock()
        minimal_deployment.deployment_id = "deploy-minimal"
        minimal_deployment.status = "pending"
        minimal_deployment.canary_phase = None
        minimal_deployment.agent_image = "ghcr.io/cirisai/ciris-agent:latest"
        minimal_deployment.gui_image = None
        minimal_deployment.agents_total = 0
        minimal_deployment.agents_staged = 0  # Added missing field
        minimal_deployment.agents_updated = 0
        minimal_deployment.agents_failed = 0  # Added missing field
        minimal_deployment.agents_deferred = 0
        minimal_deployment.created_at = datetime.now(timezone.utc).isoformat()
        minimal_deployment.started_at = None
        minimal_deployment.completed_at = None
        minimal_deployment.initiated_by = None
        minimal_deployment.message = None
        minimal_deployment.is_rollback = False
        minimal_deployment.rollback_from_deployment = None

        mock_manager.deployment_orchestrator.current_deployment = "deploy-minimal"
        mock_manager.deployment_orchestrator.deployments = {"deploy-minimal": minimal_deployment}

        collector = DeploymentCollector(mock_manager)
        metrics = await collector.collect()

        assert len(metrics) == 1
        assert metrics[0].deployment_id == "deploy-minimal"
        assert metrics[0].status == DeploymentStatus.PENDING

    @pytest.mark.asyncio
    async def test_collect_with_pending_deployments(self, mock_manager):
        """Test collecting with pending deployments."""
        # Add a pending deployment
        pending = Mock()
        pending.deployment_id = "deploy-pending"
        pending.status = "pending"
        pending.canary_phase = None
        pending.agent_image = "ghcr.io/cirisai/ciris-agent:v1.5.0"
        pending.gui_image = "ghcr.io/cirisai/ciris-gui:v1.3.0"
        pending.agents_total = 3
        pending.agents_staged = 3
        pending.agents_updated = 0
        pending.agents_failed = 0
        pending.agents_deferred = 0
        pending.created_at = datetime.now(timezone.utc).isoformat()
        pending.staged_at = None
        pending.started_at = None
        pending.completed_at = None
        pending.initiated_by = "operator"
        pending.message = "Pending deployment"
        pending.is_rollback = False
        pending.rollback_from_deployment = None

        mock_manager.deployment_orchestrator.pending_deployments = {"deploy-pending": pending}

        collector = DeploymentCollector(mock_manager)
        metrics = await collector.collect()

        # Should have both active and pending
        assert len(metrics) == 2
        deployment_ids = {m.deployment_id for m in metrics}
        assert "deploy-123" in deployment_ids
        assert "deploy-pending" in deployment_ids

    @pytest.mark.asyncio
    async def test_collect_recent_deployments(self, mock_manager):
        """Test collecting recent deployments from last 24 hours."""
        now = datetime.now(timezone.utc)

        # Add a recent completed deployment
        recent = Mock()
        recent.deployment_id = "deploy-recent"
        recent.status = "completed"
        recent.canary_phase = "complete"
        recent.agent_image = "ghcr.io/cirisai/ciris-agent:v1.3.5"
        recent.gui_image = "ghcr.io/cirisai/ciris-gui:v1.2.5"
        recent.agents_total = 4
        recent.agents_updated = 4
        recent.agents_deferred = 0
        recent.agents_failed = 0
        recent.agents_staged = 4
        recent.created_at = (now - timedelta(hours=2)).isoformat()
        recent.started_at = (now - timedelta(hours=2)).isoformat()
        recent.completed_at = (now - timedelta(hours=1)).isoformat()
        recent.initiated_by = "cd-pipeline"
        recent.message = "Deployment completed"
        recent.is_rollback = False
        recent.rollback_from_deployment = None

        # Add an old deployment (should be excluded)
        old = Mock()
        old.deployment_id = "deploy-old"
        old.status = "completed"
        old.started_at = (now - timedelta(hours=48)).isoformat()

        mock_manager.deployment_orchestrator.deployments.update(
            {"deploy-recent": recent, "deploy-old": old}
        )

        collector = DeploymentCollector(mock_manager)
        metrics = await collector.collect()

        # Should have current + recent, but not old
        deployment_ids = {m.deployment_id for m in metrics}
        assert "deploy-123" in deployment_ids
        assert "deploy-recent" in deployment_ids
        assert "deploy-old" not in deployment_ids


class TestVersionCollector:
    """Test VersionCollector functionality."""

    @pytest.fixture
    def mock_version_tracker(self):
        """Create mock version tracker."""
        tracker = AsyncMock()

        # Mock get_rollback_options
        tracker.get_rollback_options = AsyncMock(
            return_value={
                "agents": {
                    "current": {
                        "image": "ghcr.io/cirisai/ciris-agent:v1.4.0",
                        "deployed_at": datetime.now(timezone.utc).isoformat(),
                        "deployment_id": "deploy-123",
                    },
                    "n_minus_1": {
                        "image": "ghcr.io/cirisai/ciris-agent:v1.3.0",
                        "deployed_at": (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(),
                        "deployment_id": "deploy-122",
                    },
                    "n_minus_2": {
                        "image": "ghcr.io/cirisai/ciris-agent:v1.2.0",
                        "deployed_at": (
                            datetime.now(timezone.utc) - timedelta(days=14)
                        ).isoformat(),
                        "deployment_id": "deploy-121",
                    },
                    "staged": None,
                },
                "gui": {
                    "current": {
                        "image": "ghcr.io/cirisai/ciris-gui:v1.2.0",
                        "deployed_at": datetime.now(timezone.utc).isoformat(),
                        "deployment_id": "deploy-123",
                    },
                    "n_minus_1": None,
                    "n_minus_2": None,
                    "staged": None,
                },
            }
        )

        return tracker

    @pytest.fixture
    def mock_agent_registry(self):
        """Create mock agent registry."""
        registry = Mock()

        # Mock list_agents with proper agent attributes
        agents = [
            Mock(agent_id="agent-1", agent_name="Agent 1", version="1.4.0"),
            Mock(agent_id="agent-2", agent_name="Agent 2", version="1.4.0"),
            Mock(agent_id="agent-3", agent_name="Agent 3", version="1.3.0"),
        ]
        registry.list_agents = Mock(return_value=agents)

        return registry

    @pytest.fixture
    def mock_manager_with_versions(self, mock_version_tracker, mock_agent_registry):
        """Create mock manager with version tracker and agent registry."""
        manager = Mock()
        manager.version_tracker = mock_version_tracker
        manager.agent_registry = mock_agent_registry
        return manager

    @pytest.mark.asyncio
    async def test_initialization(self, mock_manager_with_versions):
        """Test collector initialization."""
        collector = VersionCollector(mock_manager_with_versions)

        assert collector.name == "VersionCollector"
        assert collector.timeout_seconds == 5
        assert collector.manager == mock_manager_with_versions

    @pytest.mark.asyncio
    async def test_collect_version_states(self, mock_manager_with_versions):
        """Test collecting version state metrics."""
        collector = VersionCollector(mock_manager_with_versions)

        states = await collector.collect_version_states()

        # Should have states for agents and gui
        assert len(states) == 2

        # Check agents state
        agent_state = next(s for s in states if s.component_type == ComponentType.AGENT)
        assert agent_state.current.tag == "v1.4.0"  # Changed from .version to .tag
        assert agent_state.previous.tag == "v1.3.0"  # Changed from n_minus_1 to previous
        assert agent_state.fallback.tag == "v1.2.0"  # Changed from n_minus_2 to fallback
        assert agent_state.staged is None

        # Check GUI state
        gui_state = next(s for s in states if s.component_type == ComponentType.GUI)
        assert gui_state.current.tag == "v1.2.0"  # Changed from .version to .tag
        assert gui_state.previous is None  # Changed from n_minus_1 to previous

    @pytest.mark.asyncio
    async def test_collect_agent_adoptions(self, mock_manager_with_versions):
        """Test collecting agent version adoption metrics."""
        collector = VersionCollector(mock_manager_with_versions)

        adoptions = await collector.collect_agent_adoptions()

        # Should have one adoption entry per agent (3 agents total)
        assert len(adoptions) == 3

        # Check that we have the right agents
        agent_ids = {a.agent_id for a in adoptions}
        assert "agent-1" in agent_ids
        assert "agent-2" in agent_ids
        assert "agent-3" in agent_ids

        # Check versions
        agent1 = next(a for a in adoptions if a.agent_id == "agent-1")
        assert agent1.current_version == "1.4.0"

        agent2 = next(a for a in adoptions if a.agent_id == "agent-2")
        assert agent2.current_version == "1.4.0"

        agent3 = next(a for a in adoptions if a.agent_id == "agent-3")
        assert agent3.current_version == "1.3.0"

    @pytest.mark.asyncio
    async def test_collect_with_staged_version(self, mock_manager_with_versions):
        """Test collecting when there's a staged version."""
        # Add staged version
        mock_manager_with_versions.version_tracker.get_rollback_options.return_value["agents"][
            "staged"
        ] = {
            "image": "ghcr.io/cirisai/ciris-agent:v1.5.0",
            "deployed_at": datetime.now(timezone.utc).isoformat(),
            "deployment_id": "deploy-124",
        }

        collector = VersionCollector(mock_manager_with_versions)
        states = await collector.collect_version_states()

        agent_state = next(s for s in states if s.component_type == ComponentType.AGENT)
        assert agent_state.staged is not None
        assert agent_state.staged.tag == "v1.5.0"  # Changed from .version to .tag

    @pytest.mark.asyncio
    async def test_handle_missing_version_tracker(self):
        """Test handling when version tracker is not available."""
        manager = Mock(spec=["agent_registry"])
        manager.agent_registry = Mock()
        manager.agent_registry.list_agents = Mock(return_value=[])

        collector = VersionCollector(manager)

        # Should return empty lists
        states = await collector.collect_version_states()
        assert states == []

        adoptions = await collector.collect_agent_adoptions()
        assert adoptions == []

    @pytest.mark.asyncio
    async def test_handle_malformed_version_data(self, mock_manager_with_versions):
        """Test handling malformed version data."""
        # Return malformed data
        mock_manager_with_versions.version_tracker.get_rollback_options.return_value = {
            "agents": {
                "current": {"image": "invalid"},  # Missing required fields
                "n_minus_1": None,
                "n_minus_2": None,
                "staged": None,
            }
        }

        collector = VersionCollector(mock_manager_with_versions)
        states = await collector.collect_version_states()

        # Should handle gracefully
        assert len(states) == 1
        agent_state = states[0]
        assert agent_state.component_type == ComponentType.AGENT
        assert (
            agent_state.current.tag == "unknown"
        )  # Changed from .version to .tag - Default when parsing fails

    @pytest.mark.asyncio
    async def test_is_available(self, mock_manager_with_versions):
        """Test availability check."""
        collector = VersionCollector(mock_manager_with_versions)

        # Should be available with version tracker
        is_available = await collector.is_available()
        assert is_available is True

        # Not available without version tracker
        manager_no_tracker = Mock(spec=[])
        collector = VersionCollector(manager_no_tracker)
        is_available = await collector.is_available()
        assert is_available is False
