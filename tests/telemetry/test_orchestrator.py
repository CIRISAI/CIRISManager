"""
Unit tests for the telemetry orchestrator.

Tests the main orchestrator that coordinates all collectors.
"""

import pytest
import asyncio
from datetime import datetime, timezone
from unittest.mock import Mock, AsyncMock, patch
import uuid

from ciris_manager.telemetry.orchestrator import (
    TelemetryOrchestrator,
    ContinuousTelemetryCollector,
)
from ciris_manager.telemetry.schemas import (
    TelemetrySnapshot,
    SystemSummary,
    ContainerMetrics,
    ContainerResources,
    ContainerStatus,
    HealthStatus,
    AgentOperationalMetrics,
    CognitiveState,
    DeploymentMetrics,
    DeploymentStatus,
    DeploymentPhase,
    VersionState,
    VersionInfo,
    ComponentType,
    AgentVersionAdoption,
)


class TestTelemetryOrchestrator:
    """Test TelemetryOrchestrator functionality."""

    @pytest.fixture
    def mock_agent_registry(self):
        """Create mock agent registry."""
        registry = Mock()
        registry.get_all_agents.return_value = {}
        return registry

    @pytest.fixture
    def orchestrator(self, mock_agent_registry, tmp_path):
        """Create orchestrator instance with mocked dependencies."""
        return TelemetryOrchestrator(
            agent_registry=mock_agent_registry,
            state_dir=str(tmp_path / "state"),
            versions_dir=str(tmp_path / "versions"),
        )

    @pytest.fixture
    def sample_snapshot(self):
        """Create a sample telemetry snapshot for testing."""
        now = datetime.now(timezone.utc)

        # Sample container metrics
        container = ContainerMetrics(
            container_id="abc123def456",  # Must be at least 12 chars
            container_name="ciris-agent-test",
            image="test:latest",
            status=ContainerStatus.RUNNING,
            health=HealthStatus.HEALTHY,
            restart_count=0,
            resources=ContainerResources(
                cpu_percent=25.5,
                memory_mb=256,
                memory_limit_mb=512,
                memory_percent=50.0,
                disk_read_mb=10,
                disk_write_mb=20,
                network_rx_mb=5,
                network_tx_mb=10,
            ),
            created_at=now,
            started_at=now,
        )

        # Sample agent metrics
        agent = AgentOperationalMetrics(
            agent_id="test-123",
            agent_name="Test",
            version="1.4.0",
            cognitive_state=CognitiveState.WORK,
            api_healthy=True,
            api_response_time_ms=100,
            uptime_seconds=3600,
            incident_count_24h=2,
            message_count_24h=1000,
            cost_cents_24h=250,
            api_port=8080,
            oauth_configured=False,
            oauth_providers=[],
        )

        # Sample deployment
        deployment = DeploymentMetrics(
            deployment_id="deploy-123",
            status=DeploymentStatus.IN_PROGRESS,
            phase=DeploymentPhase.EXPLORERS,
            agent_image="test:v1.4.0",
            agents_total=1,
            agents_staged=1,
            agents_updated=0,
            agents_failed=0,
            agents_deferred=0,
            created_at=now,
            started_at=now,
        )

        # Sample version state
        version_state = VersionState(
            component_type=ComponentType.AGENT,
            current=VersionInfo(
                image="test:v1.4.0",
                tag="v1.4.0",
                deployed_at=now,
                deployment_id="deploy-123",
            ),
            previous=VersionInfo(
                image="test:v1.3.0",
                tag="v1.3.0",
                deployed_at=now,
                deployment_id="deploy-122",
            ),
            last_updated=now,
        )

        # Sample adoption
        adoption = AgentVersionAdoption(
            agent_id="test-123",
            agent_name="Test",
            current_version="v1.4.0",
            deployment_group="explorers",
        )

        return TelemetrySnapshot(
            snapshot_id=str(uuid.uuid4()),
            timestamp=now,
            containers=[container],
            agents=[agent],
            deployments=[deployment],
            versions=[version_state],
            adoption=[adoption],
            collection_duration_ms=100,
            errors=[],
        )

    def test_initialization(self, orchestrator):
        """Test orchestrator initialization."""
        assert orchestrator.name == "TelemetryOrchestrator"
        assert len(orchestrator.collectors) == 4  # docker, agents, deployments, versions
        assert "docker" in orchestrator.collectors
        assert "agents" in orchestrator.collectors
        assert "deployments" in orchestrator.collectors
        assert "versions" in orchestrator.collectors

    @pytest.mark.asyncio
    async def test_collect_snapshot_success(self, orchestrator, sample_snapshot):
        """Test successful snapshot collection."""
        # Mock collector results
        from unittest.mock import AsyncMock

        with patch.object(
            orchestrator, "collect_all_parallel", new_callable=AsyncMock
        ) as mock_collect:
            # Make collect_all_parallel return data directly
            mock_collect.return_value = {
                "docker": sample_snapshot.containers,
                "agents": sample_snapshot.agents,
                "deployments": sample_snapshot.deployments,
                "versions": (sample_snapshot.versions, sample_snapshot.adoption),
            }

            snapshot = await orchestrator.collect_snapshot()

            assert snapshot is not None
            assert len(snapshot.containers) == 1
            assert len(snapshot.agents) == 1
            assert len(snapshot.deployments) == 1
            assert len(snapshot.versions) == 1
            assert len(snapshot.adoption) == 1
            assert snapshot.collection_duration_ms >= 0  # Changed to >= 0 since timing can be fast

    @pytest.mark.asyncio
    async def test_collect_snapshot_with_errors(self, orchestrator):
        """Test snapshot collection with partial failures."""
        with patch.object(orchestrator, "collect_all_parallel") as mock_collect:
            mock_collect.return_value = {
                "docker": [],  # Failed to collect
                "agents": [],  # Failed to collect
                "deployments": [],
                "versions": ([], []),
            }

            snapshot = await orchestrator.collect_snapshot()

            assert snapshot is not None
            assert len(snapshot.containers) == 0
            assert len(snapshot.agents) == 0
            assert len(snapshot.errors) > 0
            assert "docker collector returned no data" in snapshot.errors
            assert "agents collector returned no data" in snapshot.errors

    @pytest.mark.asyncio
    async def test_collect_method(self, orchestrator, sample_snapshot):
        """Test the collect method returns list for base class compatibility."""
        with patch.object(orchestrator, "collect_snapshot") as mock_collect:
            mock_collect.return_value = sample_snapshot

            result = await orchestrator.collect()

            assert isinstance(result, list)
            assert len(result) == 1
            assert result[0] == sample_snapshot

    @pytest.mark.asyncio
    async def test_is_available(self, orchestrator):
        """Test availability check."""
        # Mock at least one collector as available
        mock_collector = Mock()
        mock_collector.is_available = AsyncMock(return_value=True)
        orchestrator.collectors["docker"] = mock_collector

        is_available = await orchestrator.is_available()
        assert is_available is True

        # All collectors unavailable - need to mock all collectors
        for collector in orchestrator.collectors.values():
            collector.is_available = AsyncMock(return_value=False)
        is_available = await orchestrator.is_available()
        assert is_available is False

    def test_calculate_summary(self, orchestrator, sample_snapshot):
        """Test summary calculation from snapshot."""
        summary = orchestrator.calculate_summary(sample_snapshot)

        assert isinstance(summary, SystemSummary)
        assert summary.timestamp == sample_snapshot.timestamp

        # Agent stats
        assert summary.agents_total == 1
        assert summary.agents_healthy == 1
        assert summary.agents_down == 0

        # Cognitive state
        assert summary.agents_in_work == 1
        assert summary.agents_in_dream == 0

        # Resources
        assert summary.total_cpu_percent == 25.5
        assert summary.total_memory_mb == 256

        # Activity
        assert summary.total_messages_24h == 1000
        assert summary.total_incidents_24h == 2
        assert summary.total_cost_cents_24h == 250

        # Deployments
        assert summary.active_deployments == 1
        assert summary.staged_deployments == 0

        # Version adoption
        assert summary.agents_on_latest == 1
        assert summary.agents_on_previous == 0
        assert summary.agents_on_older == 0

    def test_calculate_summary_empty_snapshot(self, orchestrator):
        """Test summary calculation with empty snapshot."""
        empty_snapshot = TelemetrySnapshot(
            snapshot_id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc),
            containers=[],
            agents=[],
            deployments=[],
            versions=[],
            adoption=[],
            collection_duration_ms=10,
            errors=[],
        )

        summary = orchestrator.calculate_summary(empty_snapshot)

        assert summary.agents_total == 0
        assert summary.total_cpu_percent == 0.0
        assert summary.total_messages_24h == 0
        assert summary.agents_on_latest == 0

    def test_calculate_summary_multiple_agents(self, orchestrator):
        """Test summary calculation with multiple agents in different states."""
        now = datetime.now(timezone.utc)

        agents = [
            AgentOperationalMetrics(
                agent_id=f"agent-{i}",
                agent_name=f"Agent{i}",
                version="1.4.0",
                cognitive_state=CognitiveState.WORK if i % 2 == 0 else CognitiveState.DREAM,
                api_healthy=i != 2,  # Third agent unhealthy
                api_response_time_ms=100,
                uptime_seconds=3600,
                incident_count_24h=i,
                message_count_24h=100 * i,
                cost_cents_24h=50 * i,
                api_port=8080 + i,
                oauth_configured=False,
                oauth_providers=[],
            )
            for i in range(5)
        ]

        snapshot = TelemetrySnapshot(
            snapshot_id=str(uuid.uuid4()),
            timestamp=now,
            containers=[],
            agents=agents,
            deployments=[],
            versions=[],
            adoption=[],
            collection_duration_ms=50,
            errors=[],
        )

        summary = orchestrator.calculate_summary(snapshot)

        assert summary.agents_total == 5
        assert summary.agents_healthy == 4  # One unhealthy
        assert summary.agents_down == 1
        assert summary.agents_in_work == 3  # Even indices: 0, 2, 4
        assert summary.agents_in_dream == 2  # Odd indices: 1, 3
        assert summary.total_messages_24h == 1000  # 0 + 100 + 200 + 300 + 400
        assert summary.total_incidents_24h == 10  # 0 + 1 + 2 + 3 + 4
        assert summary.total_cost_cents_24h == 500  # 0 + 50 + 100 + 150 + 200

    def test_get_public_summary(self, orchestrator):
        """Test public summary generation."""
        summary = SystemSummary(
            timestamp=datetime.now(timezone.utc),
            agents_total=5,
            agents_healthy=4,
            agents_degraded=0,
            agents_down=1,
            agents_in_work=2,
            agents_in_dream=1,
            agents_in_solitude=1,
            agents_in_play=1,
            total_cpu_percent=150.5,
            total_memory_mb=2048,
            total_cost_cents_24h=500,
            total_messages_24h=5000,
            total_incidents_24h=10,
            active_deployments=1,
            staged_deployments=0,
            agents_on_latest=3,
            agents_on_previous=1,
            agents_on_older=1,
        )

        public = orchestrator.get_public_summary(summary)

        assert isinstance(public, dict)
        assert public["total_agents"] == 5
        assert public["healthy_percentage"] == 80.0
        assert public["messages_24h"] == 5000
        assert public["incidents_24h"] == 10
        assert public["agents_working"] == 2
        assert public["agents_dreaming"] == 1

        # Ensure no sensitive data
        assert "cost" not in str(public).lower()
        assert "agent_id" not in str(public)
        assert "agent_name" not in str(public)


class TestContinuousTelemetryCollector:
    """Test ContinuousTelemetryCollector functionality."""

    @pytest.fixture
    def mock_orchestrator(self):
        """Create mock orchestrator."""
        orchestrator = Mock(spec=TelemetryOrchestrator)
        orchestrator.name = "TelemetryOrchestrator"
        orchestrator.collect_snapshot = AsyncMock()
        orchestrator.calculate_summary = Mock()
        return orchestrator

    @pytest.fixture
    def mock_storage(self):
        """Create mock storage backend."""
        storage = Mock()
        storage.store_snapshot = AsyncMock()
        storage.store_summary = AsyncMock()
        return storage

    @pytest.fixture
    def continuous_collector(self, mock_orchestrator, mock_storage):
        """Create continuous collector with mocked dependencies."""
        return ContinuousTelemetryCollector(
            orchestrator=mock_orchestrator,
            storage_backend=mock_storage,
            interval_seconds=1,
        )

    @pytest.mark.asyncio
    async def test_start_stop(self, continuous_collector):
        """Test starting and stopping continuous collection."""
        assert not continuous_collector.is_running

        await continuous_collector.start()
        assert continuous_collector.is_running
        assert continuous_collector._task is not None

        # Let it run briefly
        await asyncio.sleep(0.1)

        await continuous_collector.stop()
        assert not continuous_collector.is_running

    @pytest.mark.asyncio
    async def test_store_data(self, continuous_collector, mock_orchestrator, mock_storage):
        """Test data storage during collection."""
        sample_snapshot = TelemetrySnapshot(
            snapshot_id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc),
            containers=[],
            agents=[],
            deployments=[],
            versions=[],
            adoption=[],
            collection_duration_ms=10,
            errors=[],
        )

        sample_summary = SystemSummary(
            timestamp=sample_snapshot.timestamp,
            agents_total=0,
            agents_healthy=0,
            agents_degraded=0,
            agents_down=0,
            agents_in_work=0,
            agents_in_dream=0,
            agents_in_solitude=0,
            agents_in_play=0,
            total_cpu_percent=0.0,
            total_memory_mb=0,
            total_cost_cents_24h=0,
            total_messages_24h=0,
            total_incidents_24h=0,
            active_deployments=0,
            staged_deployments=0,
            agents_on_latest=0,
            agents_on_previous=0,
            agents_on_older=0,
        )

        mock_orchestrator.calculate_summary.return_value = sample_summary

        await continuous_collector._store_data([sample_snapshot])

        # Verify storage methods called
        mock_storage.store_snapshot.assert_called_once_with(sample_snapshot)
        mock_storage.store_summary.assert_called_once_with(sample_summary)

        # Verify summary cached
        assert continuous_collector._last_summary == sample_summary

    def test_get_last_summary(self, continuous_collector):
        """Test retrieving last summary."""
        assert continuous_collector.get_last_summary() is None

        sample_summary = Mock(spec=SystemSummary)
        continuous_collector._last_summary = sample_summary

        assert continuous_collector.get_last_summary() == sample_summary

    def test_get_public_status(self, continuous_collector, mock_orchestrator):
        """Test getting public status."""
        assert continuous_collector.get_public_status() is None

        sample_summary = Mock(spec=SystemSummary)
        continuous_collector._last_summary = sample_summary

        mock_orchestrator.get_public_summary.return_value = {
            "total_agents": 5,
            "healthy_percentage": 80.0,
            "messages_24h": 1000,
            "incidents_24h": 5,
        }

        public_status = continuous_collector.get_public_status()

        assert public_status is not None
        assert public_status["total_agents"] == 5
        assert public_status["healthy_percentage"] == 80.0
