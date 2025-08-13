"""
Unit tests for deployment and version tracking collectors.

Tests the DeploymentCollector and VersionCollector implementations.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock
from pathlib import Path
import json

from ciris_manager.telemetry.collectors.deployment_collector import (
    DeploymentCollector,
    VersionCollector,
)
from ciris_manager.telemetry.schemas import (
    DeploymentStatus,
    DeploymentPhase,
    ComponentType,
)
# DeploymentState doesn't exist in models, we'll use a Mock instead


class TestDeploymentCollector:
    """Test DeploymentCollector functionality."""

    @pytest.fixture
    def mock_deployment_state(self):
        """Create mock deployment state."""
        now = datetime.now(timezone.utc)

        state = Mock()
        state.deployment_id = "deploy-123"
        state.status = "in_progress"
        state.phase = "explorers"
        state.agent_image = "ghcr.io/cirisai/ciris-agent:v1.4.0"
        state.gui_image = "ghcr.io/cirisai/ciris-gui:v1.2.0"
        state.agents_total = 5
        state.agents_staged = 5
        state.agents_updated = 2
        state.agents_failed = 0
        state.agents_deferred = 1
        state.created_at = now
        state.staged_at = now
        state.started_at = now
        state.completed_at = None
        state.initiated_by = "github-actions"

        return state

    @pytest.fixture
    def mock_deployment_file(self, tmp_path, mock_deployment_state):
        """Create mock deployment state file."""
        state_file = tmp_path / "deployment_state.json"
        state_file.write_text(
            json.dumps(
                {
                    "deployment_id": mock_deployment_state.deployment_id,
                    "status": mock_deployment_state.status,
                    "phase": mock_deployment_state.phase,
                    "agent_image": mock_deployment_state.agent_image,
                    "gui_image": mock_deployment_state.gui_image,
                    "agents_total": mock_deployment_state.agents_total,
                    "agents_staged": mock_deployment_state.agents_staged,
                    "agents_updated": mock_deployment_state.agents_updated,
                    "agents_failed": mock_deployment_state.agents_failed,
                    "agents_deferred": mock_deployment_state.agents_deferred,
                    "created_at": mock_deployment_state.created_at.isoformat(),
                    "staged_at": mock_deployment_state.staged_at.isoformat(),
                    "started_at": mock_deployment_state.started_at.isoformat(),
                    "initiated_by": mock_deployment_state.initiated_by,
                }
            )
        )
        return state_file

    @pytest.mark.asyncio
    async def test_initialization(self, tmp_path):
        """Test collector initialization."""
        collector = DeploymentCollector(str(tmp_path))

        assert collector.name == "DeploymentCollector"
        assert collector.timeout_seconds == 5
        assert collector.state_dir == Path(tmp_path)

    @pytest.mark.asyncio
    async def test_is_available(self, tmp_path):
        """Test availability check."""
        collector = DeploymentCollector(str(tmp_path))

        # Should be available if directory exists
        is_available = await collector.is_available()
        assert is_available is True

        # Not available if directory doesn't exist
        collector.state_dir = Path("/nonexistent/path")
        is_available = await collector.is_available()
        assert is_available is False

    @pytest.mark.asyncio
    async def test_collect_active_deployment(self, tmp_path, mock_deployment_file):
        """Test collecting active deployment metrics."""
        collector = DeploymentCollector(str(tmp_path))

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
    async def test_collect_no_deployment(self, tmp_path):
        """Test collecting when no active deployment."""
        collector = DeploymentCollector(str(tmp_path))

        metrics = await collector.collect()

        assert metrics == []

    @pytest.mark.asyncio
    async def test_collect_completed_deployment(self, tmp_path):
        """Test collecting completed deployment."""
        now = datetime.now(timezone.utc)
        state_file = tmp_path / "deployment_state.json"
        state_file.write_text(
            json.dumps(
                {
                    "deployment_id": "deploy-complete",
                    "status": "completed",
                    "phase": "complete",
                    "agent_image": "ghcr.io/cirisai/ciris-agent:v1.4.0",
                    "agents_total": 5,
                    "agents_updated": 5,
                    "created_at": (now - timedelta(hours=1)).isoformat(),
                    "completed_at": now.isoformat(),
                }
            )
        )

        collector = DeploymentCollector(str(tmp_path))
        metrics = await collector.collect()

        assert len(metrics) == 1
        assert metrics[0].status == DeploymentStatus.COMPLETED
        assert metrics[0].phase == DeploymentPhase.COMPLETE
        assert metrics[0].agents_updated == 5

    @pytest.mark.asyncio
    async def test_collect_rollback_deployment(self, tmp_path):
        """Test collecting rollback deployment."""
        now = datetime.now(timezone.utc)
        state_file = tmp_path / "deployment_state.json"
        state_file.write_text(
            json.dumps(
                {
                    "deployment_id": "rollback-456",
                    "status": "rolling_back",
                    "agent_image": "ghcr.io/cirisai/ciris-agent:v1.3.0",
                    "agents_total": 5,
                    "created_at": now.isoformat(),
                    "started_at": now.isoformat(),
                    "initiated_by": "operator",
                    "is_rollback": True,
                    "rollback_from_deployment": "deploy-123",
                }
            )
        )

        collector = DeploymentCollector(str(tmp_path))
        metrics = await collector.collect()

        assert len(metrics) == 1
        assert metrics[0].status == DeploymentStatus.ROLLING_BACK
        assert metrics[0].is_rollback is True
        assert metrics[0].rollback_from_deployment == "deploy-123"

    @pytest.mark.asyncio
    async def test_handle_malformed_state_file(self, tmp_path):
        """Test handling malformed deployment state file."""
        state_file = tmp_path / "deployment_state.json"
        state_file.write_text("not valid json")

        collector = DeploymentCollector(str(tmp_path))
        metrics = await collector.collect()

        # Should return empty list on error
        assert metrics == []

    @pytest.mark.asyncio
    async def test_handle_missing_fields(self, tmp_path):
        """Test handling state file with missing fields."""
        state_file = tmp_path / "deployment_state.json"
        state_file.write_text(
            json.dumps(
                {
                    "deployment_id": "partial",
                    "status": "pending",
                    # Missing required fields
                }
            )
        )

        collector = DeploymentCollector(str(tmp_path))
        metrics = await collector.collect()

        # Should handle gracefully
        assert len(metrics) == 1
        assert metrics[0].deployment_id == "partial"
        assert metrics[0].status == DeploymentStatus.PENDING
        assert metrics[0].agents_total == 0


class TestVersionCollector:
    """Test VersionCollector functionality."""

    @pytest.fixture
    def mock_version_state(self):
        """Create mock version state files."""
        now = datetime.now(timezone.utc)

        return {
            "agent": {
                "current": {
                    "image": "ghcr.io/cirisai/ciris-agent:v1.4.0",
                    "digest": "sha256:current",
                    "tag": "v1.4.0",
                    "deployed_at": now.isoformat(),
                    "deployment_id": "deploy-3",
                },
                "previous": {
                    "image": "ghcr.io/cirisai/ciris-agent:v1.3.0",
                    "digest": "sha256:previous",
                    "tag": "v1.3.0",
                    "deployed_at": (now - timedelta(days=1)).isoformat(),
                    "deployment_id": "deploy-2",
                },
                "fallback": {
                    "image": "ghcr.io/cirisai/ciris-agent:v1.2.0",
                    "digest": "sha256:fallback",
                    "tag": "v1.2.0",
                    "deployed_at": (now - timedelta(days=2)).isoformat(),
                    "deployment_id": "deploy-1",
                },
            },
            "gui": {
                "current": {
                    "image": "ghcr.io/cirisai/ciris-gui:v1.2.0",
                    "digest": "sha256:gui-current",
                    "tag": "v1.2.0",
                    "deployed_at": now.isoformat(),
                    "deployment_id": "deploy-3",
                }
            },
        }

    @pytest.fixture
    def mock_adoption_data(self):
        """Create mock agent adoption data."""
        now = datetime.now(timezone.utc)

        return {
            "datum": {
                "agent_id": "datum-abc123",
                "agent_name": "Datum",
                "current_version": "v1.4.0",
                "last_transition_at": now.isoformat(),
                "deployment_group": "explorers",
            },
            "sage": {
                "agent_id": "sage-def456",
                "agent_name": "Sage",
                "current_version": "v1.3.0",
                "last_transition_at": (now - timedelta(hours=1)).isoformat(),
                "deployment_group": "early_adopters",
            },
            "echo": {
                "agent_id": "echo-ghi789",
                "agent_name": "Echo",
                "current_version": "v1.4.0",
                "last_transition_at": (now - timedelta(minutes=30)).isoformat(),
                "deployment_group": "general",
            },
        }

    @pytest.fixture
    def mock_version_files(self, tmp_path, mock_version_state, mock_adoption_data):
        """Create mock version tracking files."""
        versions_dir = tmp_path / "versions"
        versions_dir.mkdir()

        # Write version state files
        for component, versions in mock_version_state.items():
            file_path = versions_dir / f"{component}_versions.json"
            file_path.write_text(json.dumps(versions))

        # Write adoption file
        adoption_file = versions_dir / "agent_adoption.json"
        adoption_file.write_text(json.dumps(mock_adoption_data))

        return versions_dir

    @pytest.mark.asyncio
    async def test_initialization(self, tmp_path):
        """Test collector initialization."""
        collector = VersionCollector(str(tmp_path))

        assert collector.name == "VersionCollector"
        assert collector.timeout_seconds == 5
        assert collector.versions_dir == Path(tmp_path)

    @pytest.mark.asyncio
    async def test_collect_version_states(self, mock_version_files):
        """Test collecting version state information."""
        collector = VersionCollector(str(mock_version_files))

        states, adoptions = await collector.collect()

        # Check version states
        assert len(states) == 2  # agent and gui

        agent_state = next(s for s in states if s.component_type == ComponentType.AGENT)
        assert agent_state.current.tag == "v1.4.0"
        assert agent_state.previous.tag == "v1.3.0"
        assert agent_state.fallback.tag == "v1.2.0"

        gui_state = next(s for s in states if s.component_type == ComponentType.GUI)
        assert gui_state.current.tag == "v1.2.0"
        assert gui_state.previous is None
        assert gui_state.fallback is None

    @pytest.mark.asyncio
    async def test_collect_agent_adoptions(self, mock_version_files):
        """Test collecting agent version adoption data."""
        collector = VersionCollector(str(mock_version_files))

        states, adoptions = await collector.collect()

        # Check adoptions
        assert len(adoptions) == 3

        datum = next(a for a in adoptions if a.agent_name == "Datum")
        assert datum.current_version == "v1.4.0"
        assert datum.deployment_group == "explorers"

        sage = next(a for a in adoptions if a.agent_name == "Sage")
        assert sage.current_version == "v1.3.0"
        assert sage.deployment_group == "early_adopters"

        echo = next(a for a in adoptions if a.agent_name == "Echo")
        assert echo.current_version == "v1.4.0"
        assert echo.deployment_group == "general"

    @pytest.mark.asyncio
    async def test_collect_with_staged_version(self, tmp_path):
        """Test collecting with staged version present."""
        versions_dir = tmp_path / "versions"
        versions_dir.mkdir()

        now = datetime.now(timezone.utc)

        # Version with staged
        agent_versions = {
            "current": {
                "image": "ghcr.io/cirisai/ciris-agent:v1.4.0",
                "tag": "v1.4.0",
                "deployed_at": now.isoformat(),
            },
            "staged": {
                "image": "ghcr.io/cirisai/ciris-agent:v1.5.0",
                "tag": "v1.5.0",
                "deployed_at": now.isoformat(),
            },
        }

        file_path = versions_dir / "agent_versions.json"
        file_path.write_text(json.dumps(agent_versions))

        # Empty adoption file
        adoption_file = versions_dir / "agent_adoption.json"
        adoption_file.write_text(json.dumps({}))

        collector = VersionCollector(str(versions_dir))
        states, adoptions = await collector.collect()

        assert len(states) == 1
        agent_state = states[0]
        assert agent_state.current.tag == "v1.4.0"
        assert agent_state.staged.tag == "v1.5.0"

    @pytest.mark.asyncio
    async def test_handle_missing_files(self, tmp_path):
        """Test handling missing version files."""
        versions_dir = tmp_path / "versions"
        versions_dir.mkdir()

        collector = VersionCollector(str(versions_dir))
        states, adoptions = await collector.collect()

        # Should return empty lists
        assert states == []
        assert adoptions == []

    @pytest.mark.asyncio
    async def test_handle_malformed_files(self, tmp_path):
        """Test handling malformed version files."""
        versions_dir = tmp_path / "versions"
        versions_dir.mkdir()

        # Write malformed JSON
        file_path = versions_dir / "agent_versions.json"
        file_path.write_text("not valid json")

        adoption_file = versions_dir / "agent_adoption.json"
        adoption_file.write_text("{}")

        collector = VersionCollector(str(versions_dir))
        states, adoptions = await collector.collect()

        # Should handle gracefully
        assert states == []
        assert adoptions == []

    @pytest.mark.asyncio
    async def test_is_available(self, tmp_path):
        """Test availability check."""
        versions_dir = tmp_path / "versions"

        collector = VersionCollector(str(versions_dir))

        # Not available if directory doesn't exist
        is_available = await collector.is_available()
        assert is_available is False

        # Available if directory exists
        versions_dir.mkdir()
        is_available = await collector.is_available()
        assert is_available is True
