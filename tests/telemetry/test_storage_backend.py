"""
Unit tests for the telemetry storage backend.

Tests PostgreSQL/TimescaleDB storage operations with mocked database.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import uuid

from ciris_manager.telemetry.storage.backend import TelemetryStorageBackend
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
    PublicHistoryEntry,
)


class TestTelemetryStorageBackend:
    """Test TelemetryStorageBackend functionality."""

    @pytest.fixture
    def storage(self):
        """Create storage backend with test DSN."""
        return TelemetryStorageBackend(
            dsn="postgresql://test:test@localhost/telemetry_test",
            pool_min_size=1,
            pool_max_size=5,
        )

    @pytest.fixture
    def mock_pool(self):
        """Create mock connection pool."""
        pool = Mock()
        pool.close = AsyncMock()
        return pool

    @pytest.fixture
    def mock_connection(self):
        """Create mock database connection."""
        conn = Mock()
        conn.execute = AsyncMock()
        conn.executemany = AsyncMock()
        conn.fetchrow = AsyncMock()
        conn.fetch = AsyncMock()
        conn.transaction = MagicMock()
        conn.transaction().__aenter__ = AsyncMock()
        conn.transaction().__aexit__ = AsyncMock()
        return conn

    @pytest.fixture
    def sample_snapshot(self):
        """Create sample snapshot for testing."""
        now = datetime.now(timezone.utc)

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

        version_state = VersionState(
            component_type=ComponentType.AGENT,
            current=VersionInfo(
                image="test:v1.4.0",
                tag="v1.4.0",
                deployed_at=now,
                deployment_id="deploy-123",
            ),
            last_updated=now,
        )

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

    @pytest.mark.asyncio
    async def test_connect(self, storage, mock_pool):
        """Test database connection."""
        with patch("ciris_manager.telemetry.storage.backend.asyncpg") as mock_asyncpg:
            mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)
            mock_create = mock_asyncpg.create_pool
            await storage.connect()

            assert storage._pool == mock_pool
            mock_create.assert_called_once_with(
                storage.dsn,
                min_size=1,
                max_size=5,
                command_timeout=10,
            )

    @pytest.mark.asyncio
    async def test_disconnect(self, storage, mock_pool):
        """Test database disconnection."""
        storage._pool = mock_pool

        await storage.disconnect()

        mock_pool.close.assert_called_once()
        assert storage._pool is None

    @pytest.mark.asyncio
    async def test_ensure_connected(self, storage, mock_pool):
        """Test connection ensuring."""
        assert storage._pool is None

        with patch("ciris_manager.telemetry.storage.backend.asyncpg") as mock_asyncpg:
            mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)
            await storage.ensure_connected()
            assert storage._pool == mock_pool

            # Should not reconnect if already connected
            await storage.ensure_connected()
            assert storage._pool == mock_pool

    @pytest.mark.asyncio
    async def test_store_snapshot(self, storage, mock_pool, mock_connection, sample_snapshot):
        """Test storing telemetry snapshot."""
        mock_pool.acquire = MagicMock()
        mock_pool.acquire().__aenter__ = AsyncMock(return_value=mock_connection)
        mock_pool.acquire().__aexit__ = AsyncMock()
        storage._pool = mock_pool

        await storage.store_snapshot(sample_snapshot)

        # Verify transaction was used
        mock_connection.transaction.assert_called_once()

        # Verify execute was called for collection run
        calls = mock_connection.execute.call_args_list
        assert len(calls) > 0

        # Check first call is collection run metadata
        first_call = calls[0]
        assert "INSERT INTO collection_runs" in first_call[0][0]
        assert sample_snapshot.snapshot_id in first_call[0]

        # Verify executemany was called for bulk inserts
        assert mock_connection.executemany.call_count >= 4  # containers, agents, versions, adoption

    @pytest.mark.asyncio
    async def test_store_container_metrics(self, storage, mock_connection, sample_snapshot):
        """Test storing container metrics."""
        await storage._store_container_metrics(
            mock_connection, sample_snapshot.containers, sample_snapshot.timestamp
        )

        mock_connection.executemany.assert_called_once()
        call_args = mock_connection.executemany.call_args

        # Verify SQL query
        assert "INSERT INTO container_metrics" in call_args[0][0]

        # Verify data records
        records = call_args[0][1]
        assert len(records) == 1
        assert records[0][1] == "abc123def456"  # container_id
        assert records[0][2] == "ciris-agent-test"  # container_name

    @pytest.mark.asyncio
    async def test_store_agent_metrics(self, storage, mock_connection, sample_snapshot):
        """Test storing agent metrics."""
        await storage._store_agent_metrics(
            mock_connection, sample_snapshot.agents, sample_snapshot.timestamp
        )

        mock_connection.executemany.assert_called_once()
        call_args = mock_connection.executemany.call_args

        # Verify SQL query
        assert "INSERT INTO agent_metrics" in call_args[0][0]

        # Verify data records
        records = call_args[0][1]
        assert len(records) == 1
        assert records[0][1] == "test-123"  # agent_id
        assert records[0][4] == "WORK"  # cognitive_state

    @pytest.mark.asyncio
    async def test_store_deployments(self, storage, mock_connection, sample_snapshot):
        """Test storing deployment metrics."""
        await storage._store_deployments(mock_connection, sample_snapshot.deployments)

        # Should use execute for upsert, not executemany
        mock_connection.execute.assert_called()
        call_args = mock_connection.execute.call_args

        # Verify SQL query
        assert "INSERT INTO deployments" in call_args[0][0]
        assert "ON CONFLICT" in call_args[0][0]

        # Verify deployment ID
        assert "deploy-123" in call_args[0]

    @pytest.mark.asyncio
    async def test_store_summary(self, storage, mock_pool, mock_connection):
        """Test storing system summary."""
        mock_pool.acquire = MagicMock()
        mock_pool.acquire().__aenter__ = AsyncMock(return_value=mock_connection)
        mock_pool.acquire().__aexit__ = AsyncMock()
        storage._pool = mock_pool

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

        await storage.store_summary(summary)

        mock_connection.execute.assert_called_once()
        call_args = mock_connection.execute.call_args

        # Verify SQL query
        assert "INSERT INTO system_summaries" in call_args[0][0]
        assert "ON CONFLICT" in call_args[0][0]

        # Verify data values
        assert 5 in call_args[0]  # agents_total
        assert 4 in call_args[0]  # agents_healthy
        assert 150.5 in call_args[0]  # total_cpu_percent

    @pytest.mark.asyncio
    async def test_get_latest_summary(self, storage, mock_pool, mock_connection):
        """Test retrieving latest summary."""
        mock_pool.acquire = MagicMock()
        mock_pool.acquire().__aenter__ = AsyncMock(return_value=mock_connection)
        mock_pool.acquire().__aexit__ = AsyncMock()
        storage._pool = mock_pool

        # Mock database row
        mock_row = {
            "time": datetime.now(timezone.utc),
            "agents_total": 5,
            "agents_healthy": 4,
            "agents_degraded": 0,
            "agents_down": 1,
            "agents_in_work": 2,
            "agents_in_dream": 1,
            "agents_in_solitude": 1,
            "agents_in_play": 1,
            "total_cpu_percent": 150.5,
            "total_memory_mb": 2048,
            "total_cost_cents_24h": 500,
            "total_messages_24h": 5000,
            "total_incidents_24h": 10,
            "active_deployments": 1,
            "staged_deployments": 0,
            "agents_on_latest": 3,
            "agents_on_previous": 1,
            "agents_on_older": 1,
        }
        mock_connection.fetchrow.return_value = mock_row

        summary = await storage.get_latest_summary()

        assert summary is not None
        assert summary.agents_total == 5
        assert summary.agents_healthy == 4
        assert summary.total_cpu_percent == 150.5

        # Verify query
        mock_connection.fetchrow.assert_called_once()
        call_args = mock_connection.fetchrow.call_args
        assert "SELECT * FROM system_summaries" in call_args[0][0]
        assert "ORDER BY time DESC" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_public_history(self, storage, mock_pool, mock_connection):
        """Test retrieving public history."""
        mock_pool.acquire = MagicMock()
        mock_pool.acquire().__aenter__ = AsyncMock(return_value=mock_connection)
        mock_pool.acquire().__aexit__ = AsyncMock()
        storage._pool = mock_pool

        # Mock database rows
        now = datetime.now(timezone.utc)
        mock_rows = [
            {
                "bucket": now - timedelta(minutes=10),
                "total_agents": 5,
                "healthy_agents": 4,
                "total_messages": 1000,
                "total_incidents": 5,
            },
            {
                "bucket": now - timedelta(minutes=5),
                "total_agents": 5,
                "healthy_agents": 5,
                "total_messages": 1100,
                "total_incidents": 4,
            },
        ]
        mock_connection.fetch.return_value = mock_rows

        history = await storage.get_public_history(hours=1, interval_minutes=5)

        assert len(history) == 2
        assert isinstance(history[0], PublicHistoryEntry)
        assert history[0].total_agents == 5
        assert history[0].healthy_agents == 4

        # Verify query
        mock_connection.fetch.assert_called_once()
        call_args = mock_connection.fetch.call_args
        assert "time_bucket" in call_args[0][0]
        assert "5 minutes" in call_args[0]

    @pytest.mark.asyncio
    async def test_cleanup_old_data(self, storage, mock_pool, mock_connection):
        """Test cleaning up old data."""
        mock_pool.acquire = MagicMock()
        mock_pool.acquire().__aenter__ = AsyncMock(return_value=mock_connection)
        mock_pool.acquire().__aexit__ = AsyncMock()
        storage._pool = mock_pool

        await storage.cleanup_old_data(days_to_keep=7)

        # Verify cleanup queries
        calls = mock_connection.execute.call_args_list
        assert len(calls) == 2

        # Check collection runs cleanup
        assert "DELETE FROM collection_runs" in calls[0][0][0]

        # Check summaries cleanup
        assert "DELETE FROM system_summaries" in calls[1][0][0]

    @pytest.mark.asyncio
    async def test_store_snapshot_error_handling(
        self, storage, mock_pool, mock_connection, sample_snapshot
    ):
        """Test error handling during snapshot storage."""
        mock_pool.acquire = MagicMock()
        mock_pool.acquire().__aenter__ = AsyncMock(return_value=mock_connection)
        mock_pool.acquire().__aexit__ = AsyncMock()
        storage._pool = mock_pool

        # Make transaction fail
        mock_connection.transaction().__aenter__.side_effect = Exception("Database error")

        with pytest.raises(Exception) as exc_info:
            await storage.store_snapshot(sample_snapshot)

        assert "Database error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_connection_pool_reuse(self, storage, mock_pool, mock_connection):
        """Test that connection pool is reused across operations."""
        with patch("ciris_manager.telemetry.storage.backend.asyncpg") as mock_asyncpg:
            mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)
            mock_create = mock_asyncpg.create_pool
            # First operation
            await storage.ensure_connected()
            assert mock_create.call_count == 1

            # Second operation should reuse pool
            await storage.ensure_connected()
            assert mock_create.call_count == 1  # Still 1, not 2

            # After disconnect, should create new pool
            await storage.disconnect()
            await storage.ensure_connected()
            assert mock_create.call_count == 2
