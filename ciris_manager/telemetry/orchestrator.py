"""
Main telemetry orchestrator that coordinates all collectors.

This is the central component that brings together all telemetry sources
and produces complete system snapshots.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Any
from pathlib import Path

from ciris_manager.telemetry.base import CompositeCollector, PeriodicCollector
from ciris_manager.telemetry.schemas import (
    TelemetrySnapshot,
    SystemSummary,
    CognitiveState,
    ContainerStatus,
)
from ciris_manager.telemetry.collectors.docker_collector import DockerCollector
from ciris_manager.telemetry.collectors.agent_collector import AgentMetricsCollector
from ciris_manager.telemetry.collectors.deployment_collector import (
    DeploymentCollector,
    VersionCollector,
)

logger = logging.getLogger(__name__)


class TelemetryOrchestrator(CompositeCollector):
    """
    Main orchestrator that coordinates all telemetry collection.

    This class brings together all individual collectors and produces
    complete telemetry snapshots with aggregated summaries.
    """

    def __init__(
        self,
        agent_registry,
        state_dir: str = "/opt/ciris/state",
        versions_dir: str = "/opt/ciris/versions",
    ):
        """
        Initialize telemetry orchestrator.

        Args:
            agent_registry: Registry containing agent metadata
            state_dir: Directory for deployment state files
            versions_dir: Directory for version tracking files
        """
        super().__init__(name="TelemetryOrchestrator")

        self.agent_registry = agent_registry
        self.state_dir = Path(state_dir)
        self.versions_dir = Path(versions_dir)

        # Initialize and register all collectors
        self._initialize_collectors()

    def _initialize_collectors(self) -> None:
        """Initialize and register all telemetry collectors."""
        # Docker metrics
        docker_collector = DockerCollector()
        self.register_collector("docker", docker_collector)

        # Agent operational metrics
        agent_collector = AgentMetricsCollector(self.agent_registry)
        self.register_collector("agents", agent_collector)

        # Deployment state
        deployment_collector = DeploymentCollector(str(self.state_dir))
        self.register_collector("deployments", deployment_collector)

        # Version tracking
        version_collector = VersionCollector(str(self.versions_dir))
        self.register_collector("versions", version_collector)  # type: ignore[arg-type]

        logger.info("Initialized all telemetry collectors")

    async def collect(self) -> List[TelemetrySnapshot]:
        """
        Collect complete telemetry snapshot.

        Returns:
            List containing single complete snapshot (for base class compatibility)
        """
        snapshot = await self.collect_snapshot()
        return [snapshot] if snapshot else []

    async def collect_snapshot(self) -> Optional[TelemetrySnapshot]:
        """
        Collect a complete telemetry snapshot from all sources.

        Returns:
            Complete telemetry snapshot or None on critical failure
        """
        start_time = datetime.now(timezone.utc)
        errors = []

        try:
            # Collect from all sources in parallel
            results = await self.collect_all_parallel()

            # Extract results
            containers = results.get("docker", [])
            agents = results.get("agents", [])
            deployments = results.get("deployments", [])

            # Version collector returns tuple
            version_data: Any = results.get("versions", ([], []))
            if isinstance(version_data, tuple) and len(version_data) == 2:
                versions, adoptions = version_data
            else:
                versions, adoptions = [], []
                if version_data is not None:
                    errors.append("Version collector returned unexpected format")

            # Track collection errors
            for key, data in results.items():
                if not data and key != "deployments":  # Deployments can be empty
                    errors.append(f"{key} collector returned no data")

            # Calculate collection duration
            duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

            # Create snapshot
            snapshot = TelemetrySnapshot(
                snapshot_id=str(uuid.uuid4()),
                timestamp=start_time,
                containers=containers,
                agents=agents,
                deployments=deployments,
                versions=versions,
                adoption=adoptions,
                collection_duration_ms=duration_ms,
                errors=errors,
            )

            logger.info(
                f"Collected telemetry snapshot {snapshot.snapshot_id} in {duration_ms}ms "
                f"({len(containers)} containers, {len(agents)} agents, "
                f"{len(deployments)} deployments, {len(errors)} errors)"
            )

            return snapshot

        except Exception as e:
            logger.error(f"Failed to collect telemetry snapshot: {e}")
            return None

    async def is_available(self) -> bool:
        """
        Check if orchestrator can collect data.

        Returns:
            True if at least one collector is available
        """
        # Check each collector
        for key, collector in self.collectors.items():
            if await collector.is_available():
                return True
        return False

    def calculate_summary(self, snapshot: TelemetrySnapshot) -> SystemSummary:
        """
        Calculate aggregated system summary from snapshot.

        Args:
            snapshot: Complete telemetry snapshot

        Returns:
            Aggregated system summary for dashboard
        """
        return SystemSummary(
            timestamp=snapshot.timestamp,
            **self._calculate_agent_health_stats(snapshot),
            **self._calculate_cognitive_state_stats(snapshot),
            **self._calculate_resource_stats(snapshot),
            **self._calculate_activity_stats(snapshot),
            **self._calculate_deployment_stats(snapshot),
            **self._calculate_version_adoption_stats(snapshot),
        )

    def _calculate_agent_health_stats(self, snapshot: TelemetrySnapshot) -> dict:
        """Calculate agent health statistics."""
        agents_total = len(snapshot.agents)
        agents_healthy = sum(1 for a in snapshot.agents if a.api_healthy)
        agents_down = sum(1 for a in snapshot.agents if not a.api_healthy)
        agents_degraded = 0  # Could be based on response time or error rate

        return {
            "agents_total": agents_total,
            "agents_healthy": agents_healthy,
            "agents_degraded": agents_degraded,
            "agents_down": agents_down,
        }

    def _calculate_cognitive_state_stats(self, snapshot: TelemetrySnapshot) -> dict:
        """Calculate cognitive state distribution."""
        state_counts = {
            "agents_in_work": 0,
            "agents_in_dream": 0,
            "agents_in_solitude": 0,
            "agents_in_play": 0,
        }

        for agent in snapshot.agents:
            if agent.cognitive_state == CognitiveState.WORK:
                state_counts["agents_in_work"] += 1
            elif agent.cognitive_state == CognitiveState.DREAM:
                state_counts["agents_in_dream"] += 1
            elif agent.cognitive_state == CognitiveState.SOLITUDE:
                state_counts["agents_in_solitude"] += 1
            elif agent.cognitive_state == CognitiveState.PLAY:
                state_counts["agents_in_play"] += 1

        return state_counts

    def _calculate_resource_stats(self, snapshot: TelemetrySnapshot) -> dict:
        """Calculate resource usage statistics."""
        running_containers = [c for c in snapshot.containers if c.status == ContainerStatus.RUNNING]

        total_cpu_percent = sum(c.resources.cpu_percent for c in running_containers)
        total_memory_mb = sum(c.resources.memory_mb for c in running_containers)

        return {
            "total_cpu_percent": round(total_cpu_percent, 2),
            "total_memory_mb": total_memory_mb,
        }

    def _calculate_activity_stats(self, snapshot: TelemetrySnapshot) -> dict:
        """Calculate activity metrics."""
        return {
            "total_messages_24h": sum(a.message_count_24h for a in snapshot.agents),
            "total_incidents_24h": sum(a.incident_count_24h for a in snapshot.agents),
            "total_cost_cents_24h": sum(a.cost_cents_24h for a in snapshot.agents),
        }

    def _calculate_deployment_stats(self, snapshot: TelemetrySnapshot) -> dict:
        """Calculate deployment statistics."""
        active_deployments = sum(
            1 for d in snapshot.deployments if d.status.value in ["in_progress", "rolling_back"]
        )
        staged_deployments = sum(1 for d in snapshot.deployments if d.status.value == "staged")

        return {
            "active_deployments": active_deployments,
            "staged_deployments": staged_deployments,
        }

    def _calculate_version_adoption_stats(self, snapshot: TelemetrySnapshot) -> dict:
        """Calculate version adoption statistics."""
        if not snapshot.adoption:
            return {
                "agents_on_latest": 0,
                "agents_on_previous": 0,
                "agents_on_older": 0,
            }

        # Find agent version information
        agent_versions = self._get_agent_versions(snapshot)

        # Count adoption
        agents_on_latest = 0
        agents_on_previous = 0
        agents_on_older = 0

        for adoption in snapshot.adoption:
            if adoption.current_version == agent_versions.get("latest"):
                agents_on_latest += 1
            elif adoption.current_version == agent_versions.get("previous"):
                agents_on_previous += 1
            elif adoption.current_version == agent_versions.get("fallback"):
                agents_on_older += 1

        return {
            "agents_on_latest": agents_on_latest,
            "agents_on_previous": agents_on_previous,
            "agents_on_older": agents_on_older,
        }

    def _get_agent_versions(self, snapshot: TelemetrySnapshot) -> dict:
        """Extract agent version information from snapshot."""
        versions = {}

        for v in snapshot.versions:
            if v.component_type.value == "agent":
                if v.current:
                    versions["latest"] = v.current.tag
                if v.previous:
                    versions["previous"] = v.previous.tag
                if v.fallback:
                    versions["fallback"] = v.fallback.tag
                break

        return versions

    def get_public_summary(self, summary: SystemSummary) -> dict:
        """
        Get public-safe summary for external dashboard.

        This removes any sensitive information and provides only
        high-level metrics suitable for public consumption.

        Args:
            summary: Full system summary

        Returns:
            Sanitized summary dictionary
        """
        # Calculate percentages and rates
        healthy_percentage = (
            (summary.agents_healthy / max(1, summary.agents_total)) * 100
            if summary.agents_total > 0
            else 0
        )

        # Simplified public view
        return {
            "timestamp": summary.timestamp.isoformat(),
            "total_agents": summary.agents_total,
            "healthy_percentage": round(healthy_percentage, 1),
            "messages_24h": summary.total_messages_24h,
            "incidents_24h": summary.total_incidents_24h,
            "active_deployments": summary.active_deployments > 0,
            "agents_working": summary.agents_in_work,
            "agents_dreaming": summary.agents_in_dream,
            # No specific agent names, IDs, or costs
        }


class ContinuousTelemetryCollector(PeriodicCollector):
    """
    Continuous telemetry collector that runs the orchestrator periodically.

    This class manages the lifecycle of continuous telemetry collection,
    including storage and error recovery.
    """

    def __init__(
        self,
        orchestrator: TelemetryOrchestrator,
        storage_backend=None,
        interval_seconds: int = 60,
    ):
        """
        Initialize continuous collector.

        Args:
            orchestrator: The telemetry orchestrator
            storage_backend: Backend for storing collected data
            interval_seconds: Collection interval
        """
        super().__init__(
            collector=orchestrator,
            interval_seconds=interval_seconds,
            storage_backend=storage_backend,
        )
        self.orchestrator = orchestrator
        self._last_summary: Optional[SystemSummary] = None

    async def _store_data(self, data: List[TelemetrySnapshot]) -> None:
        """
        Store collected telemetry data.

        Args:
            data: List containing the telemetry snapshot
        """
        if not data:
            return

        snapshot = data[0]

        # Calculate and cache summary
        self._last_summary = self.orchestrator.calculate_summary(snapshot)

        # Store in backend if available
        if self.storage_backend:
            try:
                await self.storage_backend.store_snapshot(snapshot)
                await self.storage_backend.store_summary(self._last_summary)
                logger.debug(f"Stored snapshot {snapshot.snapshot_id}")
            except Exception as e:
                logger.error(f"Failed to store telemetry: {e}")

    def get_last_summary(self) -> Optional[SystemSummary]:
        """Get the most recent calculated summary."""
        return self._last_summary

    def get_public_status(self) -> Optional[dict]:
        """Get public-safe status for external consumption."""
        if not self._last_summary:
            return None
        return self.orchestrator.get_public_summary(self._last_summary)
