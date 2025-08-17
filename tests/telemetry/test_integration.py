"""
Integration tests for the complete telemetry system.

Tests the full flow from collection through storage to API retrieval.
"""

import pytest
import asyncio
from datetime import datetime, timezone
from unittest.mock import Mock, AsyncMock, patch
import tempfile
from pathlib import Path

from ciris_manager.telemetry.service import TelemetryService
from ciris_manager.telemetry.api import TelemetryAPI
from ciris_manager.telemetry.schemas import (
    SystemSummary,
    PublicStatus,
    ContainerMetrics,
    ContainerResources,
    ContainerStatus,
    HealthStatus,
    AgentOperationalMetrics,
    CognitiveState,
)


class TestTelemetryIntegration:
    """Test complete telemetry system integration."""

    @pytest.fixture
    def mock_agent_registry(self):
        """Create mock agent registry."""
        registry = Mock()
        registry.get_all_agents.return_value = {
            "test": Mock(
                agent_id="test-123",
                name="Test",
                port=8080,
                container_name="ciris-agent-test",
                deployment_group="explorers",
                oauth_providers=[],
                metadata={"version": "1.4.0"},
            )
        }
        return registry

    @pytest.fixture
    def temp_dirs(self):
        """Create temporary directories for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            state_dir = base / "state"
            state_dir.mkdir()
            versions_dir = base / "versions"
            versions_dir.mkdir()
            yield str(state_dir), str(versions_dir)

    @pytest.fixture
    async def telemetry_service(self, mock_agent_registry, temp_dirs):
        """Create telemetry service without database."""
        state_dir, versions_dir = temp_dirs
        service = TelemetryService(
            agent_registry=mock_agent_registry,
            database_url=None,  # No database for integration test
            state_dir=state_dir,
            versions_dir=versions_dir,
            collection_interval=1,
            enable_storage=False,
        )
        await service.initialize()
        yield service
        if service.is_running:
            await service.stop()

    @pytest.mark.asyncio
    async def test_full_collection_cycle(self, telemetry_service):
        """Test complete collection cycle without storage."""
        # Mock Docker collector
        mock_docker = Mock()
        docker_metrics = [
            ContainerMetrics(
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
                created_at=datetime.now(timezone.utc),
                started_at=datetime.now(timezone.utc),
            )
        ]
        mock_docker.collect = AsyncMock(return_value=docker_metrics)
        mock_docker.collect_with_timeout = AsyncMock(return_value=docker_metrics)
        mock_docker.is_available = AsyncMock(return_value=True)
        mock_docker.get_stats = Mock(return_value={"name": "docker", "available": True})

        # Mock Agent collector
        mock_agents = Mock()
        agent_metrics = [
            AgentOperationalMetrics(
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
                carbon_24h_grams=150,
                api_port=8080,
                oauth_configured=False,
                oauth_providers=[],
            )
        ]
        mock_agents.collect = AsyncMock(return_value=agent_metrics)
        mock_agents.collect_with_timeout = AsyncMock(return_value=agent_metrics)
        mock_agents.is_available = AsyncMock(return_value=True)
        mock_agents.get_stats = Mock(return_value={"name": "agents", "available": True})

        # Replace collectors in orchestrator
        telemetry_service.orchestrator.collectors["docker"] = mock_docker
        telemetry_service.orchestrator.collectors["agents"] = mock_agents

        # Perform single collection
        summary = await telemetry_service.collect_once()

        assert summary is not None
        assert isinstance(summary, SystemSummary)
        assert summary.agents_total == 1
        assert summary.agents_healthy == 1
        assert summary.total_cpu_percent == 25.5
        assert summary.total_memory_mb == 256
        assert summary.total_messages_24h == 1000

    @pytest.mark.asyncio
    async def test_continuous_collection(self, telemetry_service):
        """Test continuous collection loop."""
        # Mock collectors as in previous test
        mock_docker = Mock()
        mock_docker.collect = AsyncMock(return_value=[])
        mock_docker.collect_with_timeout = AsyncMock(return_value=[])
        mock_docker.is_available = AsyncMock(return_value=True)
        mock_docker.get_stats = Mock(return_value={"name": "docker", "available": True})

        mock_agents = Mock()
        mock_agents.collect = AsyncMock(return_value=[])
        mock_agents.collect_with_timeout = AsyncMock(return_value=[])
        mock_agents.is_available = AsyncMock(return_value=True)
        mock_agents.get_stats = Mock(return_value={"name": "agents", "available": True})

        telemetry_service.orchestrator.collectors["docker"] = mock_docker
        telemetry_service.orchestrator.collectors["agents"] = mock_agents

        # Start service (store task to prevent garbage collection)
        start_task = asyncio.create_task(telemetry_service.start())
        _ = start_task  # Keep reference to prevent GC

        # Let it run for a bit
        await asyncio.sleep(2.5)  # Should complete 2 collection cycles

        # Stop service - will re-raise CancelledError now
        with pytest.raises(asyncio.CancelledError):
            await telemetry_service.stop()

        # Verify collections happened (check collect_with_timeout calls)
        assert mock_docker.collect_with_timeout.call_count >= 2
        assert mock_agents.collect_with_timeout.call_count >= 2

    @pytest.mark.asyncio
    async def test_public_api_safety(self, telemetry_service):
        """Test that public API properly sanitizes data."""
        # Perform collection with sensitive data
        await self._mock_collection_with_sensitive_data(telemetry_service)

        # Get public status
        public_status = telemetry_service.get_public_status()

        assert public_status is not None

        # Verify no sensitive data exposed
        public_str = str(public_status)
        assert "test-123" not in public_str  # No agent IDs
        assert "Test" not in public_str  # No agent names
        assert "8080" not in public_str  # No ports
        assert "cost" not in public_str.lower()  # No cost data

        # Verify public data is present
        assert isinstance(public_status, PublicStatus)
        assert public_status.total_agents == 1
        assert public_status.healthy_percentage > 0

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="TypedDict compatibility issue with Python 3.11")
    async def test_api_endpoints(self, telemetry_service):
        """Test API endpoint integration."""
        # Create API instance
        api = TelemetryAPI(telemetry_service)

        # Mock a collection
        await self._mock_collection_with_sensitive_data(telemetry_service)

        # Test status endpoint
        status = await api.get_status()
        assert isinstance(status, SystemSummary)
        assert status.agents_total == 1

        # Test public status endpoint
        public_status = await api.get_public_status()
        assert isinstance(public_status, PublicStatus)
        assert public_status.total_agents == 1

        # Test trigger collection
        result = await api.trigger_collection()
        assert result["status"] in ["success", "error"]

    @pytest.mark.asyncio
    async def test_error_recovery(self, telemetry_service):
        """Test system recovery from collector failures."""
        # Make Docker collector fail
        mock_docker = Mock()
        mock_docker.collect = AsyncMock(side_effect=Exception("Docker API error"))
        mock_docker.collect_with_timeout = AsyncMock(side_effect=Exception("Docker API error"))
        mock_docker.is_available = AsyncMock(return_value=False)
        mock_docker.get_stats = Mock(return_value={"name": "docker", "available": False})

        # Agent collector works
        mock_agents = Mock()
        agent_metrics = [
            AgentOperationalMetrics(
                agent_id="test-123",
                agent_name="Test",
                version="1.4.0",
                cognitive_state=CognitiveState.WORK,
                api_healthy=True,
                api_response_time_ms=100,
                uptime_seconds=3600,
                incident_count_24h=0,
                message_count_24h=100,
                cost_cents_24h=10,
                carbon_24h_grams=5,
                api_port=8080,
                oauth_configured=False,
                oauth_providers=[],
            )
        ]
        mock_agents.collect = AsyncMock(return_value=agent_metrics)
        mock_agents.collect_with_timeout = AsyncMock(return_value=agent_metrics)
        mock_agents.is_available = AsyncMock(return_value=True)
        mock_agents.get_stats = Mock(return_value={"name": "agents", "available": True})

        telemetry_service.orchestrator.collectors["docker"] = mock_docker
        telemetry_service.orchestrator.collectors["agents"] = mock_agents

        # Should still get partial data
        summary = await telemetry_service.collect_once()

        assert summary is not None
        assert summary.agents_total == 1  # Agent data collected
        assert summary.total_cpu_percent == 0.0  # No container data

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Flaky test - timing dependent")
    async def test_with_database_mock(self, mock_agent_registry, temp_dirs):
        """Test with mocked database storage."""
        state_dir, versions_dir = temp_dirs

        # Create service with mocked database URL
        service = TelemetryService(
            agent_registry=mock_agent_registry,
            database_url="postgresql://test:test@localhost/test",
            state_dir=state_dir,
            versions_dir=versions_dir,
            collection_interval=1,
            enable_storage=True,
        )

        # Mock the storage backend
        mock_storage = Mock()
        mock_storage.connect = AsyncMock()
        mock_storage.disconnect = AsyncMock()
        mock_storage.store_snapshot = AsyncMock()
        mock_storage.store_summary = AsyncMock()

        with patch(
            "ciris_manager.telemetry.service.TelemetryStorageBackend", return_value=mock_storage
        ):
            await service.initialize()

            # Verify storage was initialized
            assert service.storage == mock_storage
            mock_storage.connect.assert_called_once()

            # Start the service to set _running flag (store task to prevent garbage collection)
            start_task = asyncio.create_task(service.start())
            _ = start_task  # Keep reference to prevent GC
            await asyncio.sleep(0.1)  # Let it start

            # Mock collectors
            await self._mock_simple_collectors(service)

            # Perform collection
            summary = await service.collect_once()

            assert summary is not None

            # Verify storage methods called
            mock_storage.store_snapshot.assert_called_once()
            mock_storage.store_summary.assert_called_once_with(summary)

            # Cleanup
            await service.stop()
            mock_storage.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_data_aggregation(self, telemetry_service):
        """Test proper data aggregation across multiple agents."""
        # Mock multiple agents
        mock_agents = Mock()
        agent_metrics = [
            AgentOperationalMetrics(
                agent_id=f"agent-{i}",
                agent_name=f"Agent{i}",
                version="1.4.0",
                cognitive_state=CognitiveState.WORK if i % 2 == 0 else CognitiveState.DREAM,
                api_healthy=True,
                api_response_time_ms=100 * (i + 1),
                uptime_seconds=3600,
                incident_count_24h=i,
                message_count_24h=100 * i,
                cost_cents_24h=50 * i,
                carbon_24h_grams=25 * i,
                api_port=8080 + i,
                oauth_configured=False,
                oauth_providers=[],
            )
            for i in range(5)
        ]
        mock_agents.collect = AsyncMock(return_value=agent_metrics)
        mock_agents.collect_with_timeout = AsyncMock(return_value=agent_metrics)
        mock_agents.is_available = AsyncMock(return_value=True)
        mock_agents.get_stats = Mock(return_value={"name": "agents", "available": True})

        telemetry_service.orchestrator.collectors["agents"] = mock_agents

        # Perform collection
        summary = await telemetry_service.collect_once()

        assert summary.agents_total == 5
        assert summary.agents_in_work == 3  # 0, 2, 4
        assert summary.agents_in_dream == 2  # 1, 3
        assert summary.total_messages_24h == 1000  # 0+100+200+300+400
        assert summary.total_incidents_24h == 10  # 0+1+2+3+4
        assert summary.total_cost_cents_24h == 500  # 0+50+100+150+200

    async def _mock_collection_with_sensitive_data(self, telemetry_service):
        """Helper to mock collection with sensitive data."""
        mock_agents = Mock()
        agent_metrics = [
            AgentOperationalMetrics(
                agent_id="test-123",  # Sensitive
                agent_name="Test",  # Sensitive
                version="1.4.0",
                cognitive_state=CognitiveState.WORK,
                api_healthy=True,
                api_response_time_ms=100,
                uptime_seconds=3600,
                incident_count_24h=2,
                message_count_24h=1000,
                cost_cents_24h=250,  # Sensitive
                carbon_24h_grams=150,
                api_port=8080,  # Sensitive
                oauth_configured=False,
                oauth_providers=[],
            )
        ]
        mock_agents.collect = AsyncMock(return_value=agent_metrics)
        mock_agents.collect_with_timeout = AsyncMock(return_value=agent_metrics)
        mock_agents.is_available = AsyncMock(return_value=True)
        mock_agents.get_stats = Mock(return_value={"name": "agents", "available": True})

        telemetry_service.orchestrator.collectors["agents"] = mock_agents
        await telemetry_service.collect_once()

    async def _mock_simple_collectors(self, service):
        """Helper to set up simple mock collectors."""
        mock_docker = Mock()
        mock_docker.collect = AsyncMock(return_value=[])
        mock_docker.collect_with_timeout = AsyncMock(return_value=[])
        mock_docker.is_available = AsyncMock(return_value=True)
        mock_docker.get_stats = Mock(return_value={"name": "docker", "available": True})

        mock_agents = Mock()
        mock_agents.collect = AsyncMock(return_value=[])
        mock_agents.collect_with_timeout = AsyncMock(return_value=[])
        mock_agents.is_available = AsyncMock(return_value=True)
        mock_agents.get_stats = Mock(return_value={"name": "agents", "available": True})

        service.orchestrator.collectors["docker"] = mock_docker
        service.orchestrator.collectors["agents"] = mock_agents
