"""
PostgreSQL/TimescaleDB storage backend for telemetry data.

This module provides async storage and retrieval of telemetry metrics
using TimescaleDB for efficient time-series data management.
"""

import logging
from typing import List, Optional, Any
from datetime import datetime, timedelta

try:
    import asyncpg

    ASYNCPG_AVAILABLE = True
except ImportError:
    asyncpg = None
    ASYNCPG_AVAILABLE = False

from ciris_manager.telemetry.schemas import (
    TelemetrySnapshot,
    SystemSummary,
    ContainerMetrics,
    AgentOperationalMetrics,
    DeploymentMetrics,
    VersionState,
    AgentVersionAdoption,
    TelemetryQuery,
    TelemetryResponse,
    PublicHistoryEntry,
)

logger = logging.getLogger(__name__)


class TelemetryStorageBackend:
    """
    PostgreSQL/TimescaleDB storage backend for telemetry data.

    Handles all database operations for storing and querying telemetry metrics.
    """

    def __init__(
        self,
        dsn: str,
        pool_min_size: int = 2,
        pool_max_size: int = 10,
    ):
        """
        Initialize storage backend.

        Args:
            dsn: PostgreSQL connection string
            pool_min_size: Minimum connection pool size
            pool_max_size: Maximum connection pool size
        """
        self.dsn = dsn
        self.pool_min_size = pool_min_size
        self.pool_max_size = pool_max_size
        self._pool: Optional[Any] = None  # asyncpg.Pool when available

    async def connect(self) -> None:
        """Establish connection pool to database."""
        if self._pool:
            return

        if not ASYNCPG_AVAILABLE:
            logger.error("asyncpg is not available")
            raise ImportError("asyncpg is required for database storage")

        try:
            self._pool = await asyncpg.create_pool(
                self.dsn,
                min_size=self.pool_min_size,
                max_size=self.pool_max_size,
                command_timeout=10,
            )
            logger.info("Connected to PostgreSQL/TimescaleDB")
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise

    async def disconnect(self) -> None:
        """Close connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("Disconnected from PostgreSQL/TimescaleDB")

    async def ensure_connected(self) -> None:
        """Ensure we have an active connection pool."""
        if not self._pool:
            await self.connect()

    async def store_snapshot(self, snapshot: TelemetrySnapshot) -> None:
        """
        Store complete telemetry snapshot in database.

        Args:
            snapshot: Complete telemetry snapshot to store
        """
        await self.ensure_connected()

        if not self._pool:
            raise RuntimeError("Database connection not established")

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                try:
                    # Store collection metadata
                    await self._store_collection_run(conn, snapshot)

                    # Store container metrics
                    if snapshot.containers:
                        await self._store_container_metrics(
                            conn, snapshot.containers, snapshot.timestamp
                        )

                    # Store agent metrics
                    if snapshot.agents:
                        await self._store_agent_metrics(conn, snapshot.agents, snapshot.timestamp)

                    # Store deployment metrics
                    if snapshot.deployments:
                        await self._store_deployments(conn, snapshot.deployments)

                    # Store version states
                    if snapshot.versions:
                        await self._store_version_states(
                            conn, snapshot.versions, snapshot.timestamp
                        )

                    # Store adoption data
                    if snapshot.adoption:
                        await self._store_adoption_data(conn, snapshot.adoption, snapshot.timestamp)

                    logger.debug(f"Stored snapshot {snapshot.snapshot_id}")

                except Exception as e:
                    logger.error(f"Failed to store snapshot: {e}")
                    raise

    async def _store_collection_run(self, conn, snapshot: TelemetrySnapshot) -> None:
        """Store collection run metadata."""
        await conn.execute(
            """
            INSERT INTO collection_runs (
                snapshot_id, time, duration_ms,
                containers_collected, agents_collected,
                errors, success
            ) VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (snapshot_id) DO NOTHING
        """,
            snapshot.snapshot_id,
            snapshot.timestamp,
            snapshot.collection_duration_ms,
            len(snapshot.containers),
            len(snapshot.agents),
            snapshot.errors,
            len(snapshot.errors) == 0,
        )

    async def _store_container_metrics(
        self, conn, containers: List[ContainerMetrics], timestamp: datetime
    ) -> None:
        """Store container metrics."""
        # Prepare data for bulk insert
        records = []
        for container in containers:
            records.append(
                (
                    timestamp,
                    container.container_id,
                    container.container_name,
                    container.image,
                    container.image_digest,
                    container.status.value,
                    container.health.value,
                    container.restart_count,
                    container.resources.cpu_percent,
                    container.resources.memory_mb,
                    container.resources.memory_limit_mb,
                    container.resources.memory_percent,
                    container.resources.disk_read_mb,
                    container.resources.disk_write_mb,
                    container.resources.network_rx_mb,
                    container.resources.network_tx_mb,
                    container.created_at,
                    container.started_at,
                    container.finished_at,
                    container.exit_code,
                    container.error_message,
                )
            )

        await conn.executemany(
            """
            INSERT INTO container_metrics (
                time, container_id, container_name, image, image_digest,
                status, health_status, restart_count,
                cpu_percent, memory_mb, memory_limit_mb, memory_percent,
                disk_read_mb, disk_write_mb, network_rx_mb, network_tx_mb,
                created_at, started_at, finished_at, exit_code, error_message
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21)
        """,
            records,
        )

    async def _store_agent_metrics(
        self, conn, agents: List[AgentOperationalMetrics], timestamp: datetime
    ) -> None:
        """Store agent operational metrics."""
        records = []
        for agent in agents:
            records.append(
                (
                    timestamp,
                    agent.agent_id,
                    agent.agent_name,
                    agent.version,
                    agent.cognitive_state.value,
                    agent.api_healthy,
                    agent.api_response_time_ms,
                    agent.uptime_seconds,
                    agent.incident_count_24h,
                    agent.message_count_24h,
                    agent.cost_cents_24h,
                    agent.api_port,
                    agent.oauth_configured,
                    agent.oauth_providers,
                )
            )

        await conn.executemany(
            """
            INSERT INTO agent_metrics (
                time, agent_id, agent_name, version, cognitive_state,
                api_healthy, api_response_ms, uptime_seconds,
                incident_count_24h, message_count_24h, cost_cents_24h,
                api_port, oauth_configured, oauth_providers
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
        """,
            records,
        )

    async def _store_deployments(self, conn, deployments: List[DeploymentMetrics]) -> None:
        """Store or update deployment records."""
        for deployment in deployments:
            await conn.execute(
                """
                INSERT INTO deployments (
                    deployment_id, status, phase,
                    agent_image, gui_image, nginx_image,
                    agents_total, agents_staged, agents_updated,
                    agents_failed, agents_deferred,
                    created_at, staged_at, started_at, completed_at,
                    initiated_by, approved_by,
                    is_rollback, rollback_from_deployment
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19)
                ON CONFLICT (deployment_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    phase = EXCLUDED.phase,
                    agents_staged = EXCLUDED.agents_staged,
                    agents_updated = EXCLUDED.agents_updated,
                    agents_failed = EXCLUDED.agents_failed,
                    agents_deferred = EXCLUDED.agents_deferred,
                    staged_at = COALESCE(EXCLUDED.staged_at, deployments.staged_at),
                    started_at = COALESCE(EXCLUDED.started_at, deployments.started_at),
                    completed_at = COALESCE(EXCLUDED.completed_at, deployments.completed_at),
                    approved_by = COALESCE(EXCLUDED.approved_by, deployments.approved_by)
            """,
                deployment.deployment_id,
                deployment.status.value,
                deployment.phase.value if deployment.phase else None,
                deployment.agent_image,
                deployment.gui_image,
                deployment.nginx_image,
                deployment.agents_total,
                deployment.agents_staged,
                deployment.agents_updated,
                deployment.agents_failed,
                deployment.agents_deferred,
                deployment.created_at,
                deployment.staged_at,
                deployment.started_at,
                deployment.completed_at,
                deployment.initiated_by,
                deployment.approved_by,
                deployment.is_rollback,
                deployment.rollback_from_deployment,
            )

    async def _store_version_states(
        self, conn, versions: List[VersionState], timestamp: datetime
    ) -> None:
        """Store version state information."""
        records = []
        for version in versions:
            # Store each version type
            if version.current:
                records.append(
                    (
                        timestamp,
                        version.component_type.value,
                        "current",
                        version.current.image,
                        version.current.digest,
                        version.current.tag,
                        version.current.deployed_at,
                        version.current.deployment_id,
                    )
                )

            if version.previous:
                records.append(
                    (
                        timestamp,
                        version.component_type.value,
                        "previous",
                        version.previous.image,
                        version.previous.digest,
                        version.previous.tag,
                        version.previous.deployed_at,
                        version.previous.deployment_id,
                    )
                )

            if version.fallback:
                records.append(
                    (
                        timestamp,
                        version.component_type.value,
                        "fallback",
                        version.fallback.image,
                        version.fallback.digest,
                        version.fallback.tag,
                        version.fallback.deployed_at,
                        version.fallback.deployment_id,
                    )
                )

            if version.staged:
                records.append(
                    (
                        timestamp,
                        version.component_type.value,
                        "staged",
                        version.staged.image,
                        version.staged.digest,
                        version.staged.tag,
                        version.staged.deployed_at,
                        version.staged.deployment_id,
                    )
                )

        if records:
            await conn.executemany(
                """
                INSERT INTO version_history (
                    time, component_type, version_type,
                    image, digest, tag, deployed_at, deployment_id
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
                records,
            )

    async def _store_adoption_data(
        self, conn, adoptions: List[AgentVersionAdoption], timestamp: datetime
    ) -> None:
        """Store agent version adoption data."""
        records = []
        for adoption in adoptions:
            records.append(
                (
                    timestamp,
                    adoption.agent_id,
                    adoption.agent_name,
                    adoption.current_version,
                    adoption.deployment_group,
                    adoption.last_transition_at,
                    adoption.last_work_state_at,
                )
            )

        await conn.executemany(
            """
            INSERT INTO agent_version_adoption (
                time, agent_id, agent_name, current_version,
                deployment_group, last_transition_at, last_work_state_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
            records,
        )

    async def store_summary(self, summary: SystemSummary) -> None:
        """
        Store system summary.

        Args:
            summary: System summary to store
        """
        await self.ensure_connected()

        if not self._pool:
            raise RuntimeError("Database connection not established")

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO system_summaries (
                    time,
                    agents_total, agents_healthy, agents_degraded, agents_down,
                    agents_in_work, agents_in_dream, agents_in_solitude, agents_in_play,
                    total_cpu_percent, total_memory_mb, total_cost_cents_24h,
                    total_messages_24h, total_incidents_24h,
                    active_deployments, staged_deployments,
                    agents_on_latest, agents_on_previous, agents_on_older
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19)
                ON CONFLICT (time) DO UPDATE SET
                    agents_total = EXCLUDED.agents_total,
                    agents_healthy = EXCLUDED.agents_healthy,
                    agents_degraded = EXCLUDED.agents_degraded,
                    agents_down = EXCLUDED.agents_down,
                    agents_in_work = EXCLUDED.agents_in_work,
                    agents_in_dream = EXCLUDED.agents_in_dream,
                    agents_in_solitude = EXCLUDED.agents_in_solitude,
                    agents_in_play = EXCLUDED.agents_in_play,
                    total_cpu_percent = EXCLUDED.total_cpu_percent,
                    total_memory_mb = EXCLUDED.total_memory_mb,
                    total_cost_cents_24h = EXCLUDED.total_cost_cents_24h,
                    total_messages_24h = EXCLUDED.total_messages_24h,
                    total_incidents_24h = EXCLUDED.total_incidents_24h,
                    active_deployments = EXCLUDED.active_deployments,
                    staged_deployments = EXCLUDED.staged_deployments,
                    agents_on_latest = EXCLUDED.agents_on_latest,
                    agents_on_previous = EXCLUDED.agents_on_previous,
                    agents_on_older = EXCLUDED.agents_on_older
            """,
                summary.timestamp,
                summary.agents_total,
                summary.agents_healthy,
                summary.agents_degraded,
                summary.agents_down,
                summary.agents_in_work,
                summary.agents_in_dream,
                summary.agents_in_solitude,
                summary.agents_in_play,
                summary.total_cpu_percent,
                summary.total_memory_mb,
                summary.total_cost_cents_24h,
                summary.total_messages_24h,
                summary.total_incidents_24h,
                summary.active_deployments,
                summary.staged_deployments,
                summary.agents_on_latest,
                summary.agents_on_previous,
                summary.agents_on_older,
            )

    async def get_latest_summary(self) -> Optional[SystemSummary]:
        """
        Get the most recent system summary.

        Returns:
            Latest system summary or None if not found
        """
        await self.ensure_connected()

        if not self._pool:
            return None

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM system_summaries
                ORDER BY time DESC
                LIMIT 1
            """
            )

            if not row:
                return None

            return SystemSummary(
                timestamp=row["time"],
                agents_total=row["agents_total"],
                agents_healthy=row["agents_healthy"],
                agents_degraded=row["agents_degraded"],
                agents_down=row["agents_down"],
                agents_in_work=row["agents_in_work"],
                agents_in_dream=row["agents_in_dream"],
                agents_in_solitude=row["agents_in_solitude"],
                agents_in_play=row["agents_in_play"],
                total_cpu_percent=float(row["total_cpu_percent"]),
                total_memory_mb=row["total_memory_mb"],
                total_cost_cents_24h=row["total_cost_cents_24h"],
                total_messages_24h=row["total_messages_24h"],
                total_incidents_24h=row["total_incidents_24h"],
                active_deployments=row["active_deployments"],
                staged_deployments=row["staged_deployments"],
                agents_on_latest=row["agents_on_latest"],
                agents_on_previous=row["agents_on_previous"],
                agents_on_older=row["agents_on_older"],
            )

    async def get_public_history(
        self, hours: int = 24, interval_minutes: int = 5
    ) -> List[PublicHistoryEntry]:
        """
        Get public-safe historical data.

        Args:
            hours: Number of hours to retrieve
            interval_minutes: Aggregation interval

        Returns:
            List of public history entries
        """
        await self.ensure_connected()

        if not self._pool:
            return []

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    time_bucket($1::interval, time) as bucket,
                    MAX(agents_total) as total_agents,
                    MAX(agents_healthy) as healthy_agents,
                    MAX(total_messages_24h) as total_messages,
                    MAX(total_incidents_24h) as total_incidents
                FROM system_summaries
                WHERE time > NOW() - ($2::int || ' hours')::interval
                GROUP BY bucket
                ORDER BY bucket DESC
            """,
                f"{interval_minutes} minutes",
                hours,
            )

            return [
                PublicHistoryEntry(
                    timestamp=row["bucket"],
                    total_agents=row["total_agents"],
                    healthy_agents=row["healthy_agents"],
                    total_messages=row["total_messages"],
                    total_incidents=row["total_incidents"],
                )
                for row in rows
            ]

    async def query_telemetry(self, query: TelemetryQuery) -> TelemetryResponse:
        """
        Query telemetry data based on parameters.

        Args:
            query: Query parameters

        Returns:
            Telemetry response with matching data
        """
        # This would be implemented with complex queries based on the query parameters
        # For now, returning a placeholder
        return TelemetryResponse(
            query=query,
            snapshots=[],
            summary=None,
            total_count=0,
            has_more=False,
        )

    async def cleanup_old_data(self, days_to_keep: int = 7) -> None:
        """
        Clean up old data beyond retention period.

        Args:
            days_to_keep: Number of days of data to retain
        """
        await self.ensure_connected()

        if not self._pool:
            logger.warning("Cannot cleanup data: database connection not established")
            return

        cutoff = datetime.now() - timedelta(days=days_to_keep)

        async with self._pool.acquire() as conn:
            # Clean up collection runs
            await conn.execute(
                """
                DELETE FROM collection_runs
                WHERE time < $1
            """,
                cutoff,
            )

            # Clean up old summaries (keep longer)
            summary_cutoff = datetime.now() - timedelta(days=90)
            await conn.execute(
                """
                DELETE FROM system_summaries
                WHERE time < $1
            """,
                summary_cutoff,
            )

            logger.info(f"Cleaned up data older than {days_to_keep} days")
