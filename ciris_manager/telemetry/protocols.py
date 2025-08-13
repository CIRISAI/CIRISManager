"""
Telemetry protocols defining contracts between components.

These protocols define what each component promises to provide,
ensuring clean separation of concerns and testability.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Protocol, runtime_checkable
from datetime import datetime

from ciris_manager.telemetry.schemas import (
    ContainerMetrics,
    AgentOperationalMetrics,
    DeploymentMetrics,
    VersionState,
    AgentVersionAdoption,
    TelemetrySnapshot,
    SystemSummary,
    TelemetryQuery,
    TelemetryResponse,
)


# ============================================================================
# COLLECTOR PROTOCOLS - What each collector promises to provide
# ============================================================================


@runtime_checkable
class ContainerMetricsCollector(Protocol):
    """Protocol for collecting Docker container metrics."""

    async def collect_container_metrics(self) -> List[ContainerMetrics]:
        """
        Collect metrics for all CIRIS containers.

        Promises:
        - Returns metrics for ALL containers with 'ciris' in name
        - Handles Docker API errors gracefully (returns empty list)
        - Completes within 5 seconds
        - Never raises exceptions
        """
        ...

    async def is_available(self) -> bool:
        """
        Check if Docker API is available.

        Promises:
        - Returns True only if Docker socket is accessible
        - Completes within 1 second
        - Never raises exceptions
        """
        ...


@runtime_checkable
class AgentMetricsCollector(Protocol):
    """Protocol for collecting agent operational metrics."""

    async def collect_agent_metrics(self) -> List[AgentOperationalMetrics]:
        """
        Collect operational metrics from all agents.

        Promises:
        - Makes only ONE API call per agent (/v1/system/health)
        - Respects 5-second timeout per agent
        - Returns partial results if some agents fail
        - Never queries internal agent details (audit logs, messages)
        - Never raises exceptions
        """
        ...

    async def get_agent_ports(self) -> dict[str, int]:
        """
        Get port mappings for all agents.

        Promises:
        - Returns mapping of agent_id to port
        - Uses agent registry as source of truth
        - Never raises exceptions
        """
        ...


@runtime_checkable
class DeploymentMetricsCollector(Protocol):
    """Protocol for collecting deployment state."""

    async def collect_deployment_metrics(self) -> List[DeploymentMetrics]:
        """
        Collect metrics for all active and recent deployments.

        Promises:
        - Returns all deployments from last 24 hours
        - Includes both active and completed deployments
        - Reads from deployment orchestrator state
        - Never raises exceptions
        """
        ...

    async def get_staged_deployments(self) -> List[DeploymentMetrics]:
        """
        Get deployments awaiting approval.

        Promises:
        - Returns only STAGED status deployments
        - Ordered by creation time (oldest first)
        - Never raises exceptions
        """
        ...


@runtime_checkable
class VersionMetricsCollector(Protocol):
    """Protocol for collecting version state."""

    async def collect_version_state(self) -> List[VersionState]:
        """
        Collect version state for all component types.

        Promises:
        - Returns state for: agents, gui, nginx, manager
        - Includes n, n-1, n-2, and staged versions
        - Reads from version tracker
        - Never raises exceptions
        """
        ...

    async def collect_adoption_metrics(self) -> List[AgentVersionAdoption]:
        """
        Collect version adoption by agent.

        Promises:
        - Returns current version for each agent
        - Includes deployment group assignment
        - Tracks last WORK state transition
        - Never raises exceptions
        """
        ...


# ============================================================================
# STORAGE PROTOCOL - What storage backends must provide
# ============================================================================


@runtime_checkable
class TelemetryStorage(Protocol):
    """Protocol for telemetry storage backends."""

    async def store_snapshot(self, snapshot: TelemetrySnapshot) -> bool:
        """
        Store a telemetry snapshot.

        Promises:
        - Atomically stores complete snapshot
        - Returns True only if fully successful
        - Handles conflicts (duplicate snapshot_id)
        - Completes within 10 seconds
        - Never raises exceptions
        """
        ...

    async def query_snapshots(self, query: TelemetryQuery) -> TelemetryResponse:
        """
        Query stored telemetry data.

        Promises:
        - Returns data within query time range
        - Applies all filters correctly
        - Respects pagination limits
        - Returns empty result for no matches
        - Never raises exceptions
        """
        ...

    async def get_latest_snapshot(self) -> Optional[TelemetrySnapshot]:
        """
        Get the most recent snapshot.

        Promises:
        - Returns snapshot from last 5 minutes if available
        - Returns None if no recent data
        - Completes within 2 seconds
        - Never raises exceptions
        """
        ...

    async def get_system_summary(self, start_time: Optional[datetime] = None) -> SystemSummary:
        """
        Get aggregated system summary.

        Promises:
        - Aggregates data from start_time to now
        - Uses last 24 hours if start_time is None
        - Always returns valid summary (zeros if no data)
        - Completes within 5 seconds
        - Never raises exceptions
        """
        ...

    async def cleanup_old_data(self, days_to_keep: int) -> int:
        """
        Remove data older than specified days.

        Promises:
        - Deletes only data older than days_to_keep
        - Returns count of records deleted
        - Maintains referential integrity
        - Completes within 60 seconds
        - Never raises exceptions
        """
        ...

    async def is_healthy(self) -> bool:
        """
        Check storage backend health.

        Promises:
        - Returns True only if backend is fully operational
        - Checks connection and write capability
        - Completes within 2 seconds
        - Never raises exceptions
        """
        ...


# ============================================================================
# MAIN COLLECTOR PROTOCOL - The orchestrator
# ============================================================================


@runtime_checkable
class TelemetryCollector(Protocol):
    """Main telemetry collector that orchestrates all collection."""

    async def collect_all(self) -> TelemetrySnapshot:
        """
        Collect all telemetry data.

        Promises:
        - Collects from all sources in parallel
        - Returns partial snapshot if some collectors fail
        - Records errors in snapshot.errors
        - Completes within 30 seconds total
        - Never raises exceptions
        """
        ...

    async def start(self) -> None:
        """
        Start continuous collection loop.

        Promises:
        - Collects every 60 seconds
        - Stores each snapshot to backend
        - Continues on individual failures
        - Logs but doesn't raise exceptions
        """
        ...

    async def stop(self) -> None:
        """
        Stop collection loop gracefully.

        Promises:
        - Completes current collection if in progress
        - Stores final snapshot
        - Cleans up resources
        - Completes within 10 seconds
        """
        ...

    def get_collection_stats(self) -> dict:
        """
        Get collection statistics.

        Promises:
        - Returns counts of successful/failed collections
        - Includes average collection duration
        - Shows last collection time
        - Never raises exceptions

        Returns:
            Dict with keys: total, successful, failed,
            avg_duration_ms, last_collection_at
        """
        ...


# ============================================================================
# API PROTOCOL - Query interface for consumers
# ============================================================================


@runtime_checkable
class TelemetryAPI(Protocol):
    """API for querying telemetry data."""

    async def get_current_state(self) -> TelemetrySnapshot:
        """
        Get current system state.

        Promises:
        - Returns latest snapshot if < 5 minutes old
        - Otherwise triggers new collection
        - Completes within 35 seconds
        - Never raises exceptions
        """
        ...

    async def get_dashboard_data(self) -> SystemSummary:
        """
        Get data formatted for dashboard display.

        Promises:
        - Returns aggregated 24-hour summary
        - Optimized for UI display
        - Includes all key metrics
        - Completes within 5 seconds
        - Never raises exceptions
        """
        ...

    async def get_agent_history(
        self, agent_id: str, hours: int = 24
    ) -> List[AgentOperationalMetrics]:
        """
        Get historical metrics for a specific agent.

        Promises:
        - Returns hourly aggregates for specified period
        - Maximum 7 days of history
        - Empty list if agent not found
        - Completes within 5 seconds
        - Never raises exceptions
        """
        ...

    async def get_deployment_history(self, days: int = 7) -> List[DeploymentMetrics]:
        """
        Get deployment history.

        Promises:
        - Returns all deployments within period
        - Ordered by creation time (newest first)
        - Maximum 30 days of history
        - Completes within 5 seconds
        - Never raises exceptions
        """
        ...

    async def get_version_adoption(self) -> List[AgentVersionAdoption]:
        """
        Get current version adoption across fleet.

        Promises:
        - Returns current state for all agents
        - Groups by version for easy analysis
        - Completes within 2 seconds
        - Never raises exceptions
        """
        ...


# ============================================================================
# PUBLIC API PROTOCOL - Sanitized data for public dashboard
# ============================================================================


@runtime_checkable
class PublicTelemetryAPI(Protocol):
    """Public API with sanitized data only."""

    async def get_public_status(self) -> dict:
        """
        Get public system status.

        Promises:
        - Returns only non-sensitive metrics
        - No agent IDs or internal details
        - Aggregated statistics only
        - Caches for 60 seconds
        - Never raises exceptions

        Returns:
            Dict with: total_agents, healthy_percentage,
            messages_24h, incidents_24h, uptime_percentage
        """
        ...

    async def get_public_history(self, hours: int = 24) -> List[dict]:
        """
        Get public historical metrics.

        Promises:
        - Returns hourly aggregates only
        - No individual agent data
        - Maximum 72 hours of history
        - Caches for 5 minutes
        - Never raises exceptions

        Returns:
            List of dicts with: timestamp, total_agents,
            healthy_agents, total_messages, total_incidents
        """
        ...


# ============================================================================
# FACTORY PROTOCOL - For dependency injection
# ============================================================================


class TelemetryFactory(ABC):
    """Factory for creating telemetry components."""

    @abstractmethod
    async def create_collector(self) -> TelemetryCollector:
        """Create configured telemetry collector."""
        ...

    @abstractmethod
    async def create_storage(self) -> TelemetryStorage:
        """Create configured storage backend."""
        ...

    @abstractmethod
    async def create_api(self) -> TelemetryAPI:
        """Create telemetry API instance."""
        ...

    @abstractmethod
    async def create_public_api(self) -> PublicTelemetryAPI:
        """Create public API instance."""
        ...
