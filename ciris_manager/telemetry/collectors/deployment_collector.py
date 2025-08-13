"""
Deployment and version state collector implementation.

Collects deployment status and version tracking information.
"""

import logging
from typing import List, Optional, Tuple
from datetime import datetime, timezone, timedelta

from ciris_manager.telemetry.base import BaseCollector
from ciris_manager.telemetry.schemas import (
    DeploymentMetrics,
    DeploymentStatus,
    DeploymentPhase,
    VersionState,
    VersionInfo,
    ComponentType,
    AgentVersionAdoption,
)

logger = logging.getLogger(__name__)


class DeploymentCollector(BaseCollector[DeploymentMetrics]):
    """Collects deployment and version state metrics."""

    def __init__(self, manager=None):
        """
        Initialize deployment collector.

        Args:
            manager: CIRISManager instance for accessing orchestrator and registry
        """
        super().__init__(name="DeploymentCollector", timeout_seconds=5)
        self.manager = manager

    async def collect(self) -> List[DeploymentMetrics]:
        """Implement BaseCollector abstract method."""
        return await self.collect_deployment_metrics()

    async def is_available(self) -> bool:
        """Check if deployment orchestrator is available."""
        return self.manager is not None and hasattr(self.manager, "deployment_orchestrator")

    async def collect_deployment_metrics(self) -> List[DeploymentMetrics]:
        """
        Collect metrics for all active and recent deployments.

        Returns all deployments from last 24 hours.
        """
        if not self.manager or not hasattr(self.manager, "deployment_orchestrator"):
            logger.warning("No deployment orchestrator available")
            return []

        orchestrator = self.manager.deployment_orchestrator
        metrics = []

        # Get current deployment
        if orchestrator.current_deployment:
            deployment = orchestrator.deployments.get(orchestrator.current_deployment)
            if deployment:
                metric = self._deployment_to_metrics(deployment)
                if metric:
                    metrics.append(metric)

        # Get staged deployments
        for deployment_id, deployment in orchestrator.pending_deployments.items():
            metric = self._deployment_to_metrics(deployment)
            if metric:
                metrics.append(metric)

        # Get recent completed deployments (last 24 hours)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        for deployment_id, deployment in orchestrator.deployments.items():
            if deployment_id == orchestrator.current_deployment:
                continue  # Already added

            # Check if recent
            if deployment.started_at:
                start_time = datetime.fromisoformat(deployment.started_at)
                if start_time >= cutoff:
                    metric = self._deployment_to_metrics(deployment)
                    if metric:
                        metrics.append(metric)

        logger.info(f"Collected {len(metrics)} deployment metrics")
        return metrics

    def _deployment_to_metrics(self, deployment) -> Optional[DeploymentMetrics]:
        """Convert deployment status to metrics."""
        try:
            # Parse status
            status = self._parse_deployment_status(deployment.status)

            # Parse phase
            phase = None
            if deployment.canary_phase:
                phase = self._parse_deployment_phase(deployment.canary_phase)

            # Parse timestamps
            created_at = self._parse_timestamp(deployment.started_at) or datetime.now(timezone.utc)
            staged_at = self._parse_timestamp(deployment.staged_at)
            started_at = self._parse_timestamp(deployment.started_at)
            completed_at = self._parse_timestamp(deployment.completed_at)

            # Get images from notification
            agent_image = None
            gui_image = None
            nginx_image = None

            if deployment.notification:
                agent_image = deployment.notification.agent_image
                gui_image = deployment.notification.gui_image
                nginx_image = deployment.notification.nginx_image

            # Determine if rollback
            is_rollback = "rollback" in deployment.status.lower()

            return DeploymentMetrics(
                deployment_id=deployment.deployment_id,
                status=status,
                phase=phase,
                agent_image=agent_image,
                gui_image=gui_image,
                nginx_image=nginx_image,
                agents_total=deployment.agents_total,
                agents_staged=0,  # Would need to track separately
                agents_updated=deployment.agents_updated,
                agents_failed=deployment.agents_failed,
                agents_deferred=deployment.agents_deferred,
                created_at=created_at,
                staged_at=staged_at,
                started_at=started_at,
                completed_at=completed_at,
                initiated_by=None,  # Would need to track
                approved_by=None,  # Would need to track
                is_rollback=is_rollback,
                rollback_from_deployment=None,  # Would need to track
            )

        except Exception as e:
            logger.error(f"Failed to convert deployment to metrics: {e}")
            return None

    def _parse_deployment_status(self, status: str) -> DeploymentStatus:
        """Parse deployment status string to enum."""
        status_lower = status.lower()

        if status_lower == "pending":
            return DeploymentStatus.PENDING
        elif status_lower == "in_progress":
            return DeploymentStatus.IN_PROGRESS
        elif status_lower == "paused":
            return DeploymentStatus.PAUSED
        elif status_lower == "completed":
            return DeploymentStatus.COMPLETED
        elif status_lower == "failed":
            return DeploymentStatus.FAILED
        elif status_lower == "cancelled":
            return DeploymentStatus.CANCELLED
        elif status_lower == "rejected":
            return DeploymentStatus.REJECTED
        elif status_lower == "rolling_back":
            return DeploymentStatus.ROLLING_BACK
        elif status_lower == "rolled_back":
            return DeploymentStatus.ROLLED_BACK
        elif status_lower == "staged":
            return DeploymentStatus.STAGED
        else:
            return DeploymentStatus.PENDING

    def _parse_deployment_phase(self, phase: str) -> DeploymentPhase:
        """Parse deployment phase string to enum."""
        phase_lower = phase.lower()

        if phase_lower == "explorers":
            return DeploymentPhase.EXPLORERS
        elif phase_lower == "early_adopters":
            return DeploymentPhase.EARLY_ADOPTERS
        elif phase_lower == "general":
            return DeploymentPhase.GENERAL
        elif phase_lower == "complete":
            return DeploymentPhase.COMPLETE
        else:
            return DeploymentPhase.EXPLORERS

    def _parse_timestamp(self, timestamp_str: Optional[str]) -> Optional[datetime]:
        """Parse ISO timestamp string."""
        if not timestamp_str:
            return None

        try:
            return datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        except Exception as e:
            logger.debug(f"Failed to parse timestamp {timestamp_str}: {e}")
            return None

    async def get_staged_deployments(self) -> List[DeploymentMetrics]:
        """Get deployments awaiting approval."""
        if not self.manager or not hasattr(self.manager, "deployment_orchestrator"):
            return []

        orchestrator = self.manager.deployment_orchestrator
        metrics = []

        for deployment_id, deployment in orchestrator.pending_deployments.items():
            if deployment.status == "staged":
                metric = self._deployment_to_metrics(deployment)
                if metric:
                    metrics.append(metric)

        # Sort by creation time (oldest first)
        metrics.sort(key=lambda x: x.created_at)
        return metrics


class VersionCollector:
    """Collects version state and adoption metrics."""

    def __init__(self, manager=None):
        """
        Initialize version collector.

        Args:
            manager: CIRISManager instance for accessing version tracker and registry
        """
        self.manager = manager
        self.name = "VersionCollector"
        self.timeout_seconds = 5

    async def collect(self) -> Tuple[List[VersionState], List[AgentVersionAdoption]]:
        """Collect version states and adoption metrics."""
        states = await self.collect_version_state()
        adoptions = await self.collect_adoption_metrics()
        return states, adoptions

    async def is_available(self) -> bool:
        """Check if version tracker is available."""
        return self.manager is not None

    async def collect_version_state(self) -> List[VersionState]:
        """
        Collect version state for all component types.

        Returns state for: agents, gui, nginx, manager.
        """
        states = []

        # Get version tracker if available
        try:
            from ciris_manager.version_tracker import get_version_tracker

            tracker = get_version_tracker()

            # Ensure loaded
            await tracker._ensure_loaded()

            # Collect state for each component type
            for component_type in ["agents", "gui", "nginx"]:
                if component_type in tracker.state:
                    state_data = tracker.state[component_type]

                    # Convert to our schema
                    version_state = VersionState(
                        component_type=self._parse_component_type(component_type),
                        current=self._create_version_info(state_data.n),
                        previous=self._create_version_info(state_data.n_minus_1),
                        fallback=self._create_version_info(state_data.n_minus_2),
                        staged=self._create_version_info(state_data.n_plus_1),
                        last_updated=datetime.now(timezone.utc),
                    )
                    states.append(version_state)

        except Exception as e:
            logger.error(f"Failed to collect version state: {e}")

        # Add manager version (static for now)
        states.append(
            VersionState(
                component_type=ComponentType.MANAGER,
                current=VersionInfo(
                    image="ciris-manager:latest",
                    digest=None,
                    tag="latest",
                    deployed_at=datetime.now(timezone.utc),
                    deployment_id=None,
                ),
                previous=None,
                fallback=None,
                staged=None,
                last_updated=datetime.now(timezone.utc),
            )
        )

        return states

    def _parse_component_type(self, component: str) -> ComponentType:
        """Parse component string to enum."""
        if component == "agents":
            return ComponentType.AGENT
        elif component == "gui":
            return ComponentType.GUI
        elif component == "nginx":
            return ComponentType.NGINX
        else:
            return ComponentType.MANAGER

    def _create_version_info(self, version_data) -> Optional[VersionInfo]:
        """Create VersionInfo from version tracker data."""
        if not version_data:
            return None

        try:
            deployed_at = datetime.now(timezone.utc)
            if hasattr(version_data, "deployed_at"):
                deployed_at = datetime.fromisoformat(
                    version_data.deployed_at.replace("Z", "+00:00")
                )

            # Extract tag from image
            image = version_data.image if hasattr(version_data, "image") else "unknown"
            tag = image.split(":")[-1] if ":" in image else "latest"

            return VersionInfo(
                image=image,
                digest=version_data.digest if hasattr(version_data, "digest") else None,
                tag=tag,
                deployed_at=deployed_at,
                deployment_id=version_data.deployment_id
                if hasattr(version_data, "deployment_id")
                else None,
            )
        except Exception as e:
            logger.debug(f"Failed to create version info: {e}")
            return None

    async def collect_adoption_metrics(self) -> List[AgentVersionAdoption]:
        """
        Collect version adoption by agent.

        Returns current version for each agent.
        """
        if not self.manager or not hasattr(self.manager, "agent_registry"):
            return []

        registry = self.manager.agent_registry
        metrics = []

        for agent_id, agent_info in registry.agents.items():
            # Get deployment group
            group = "general"  # Default
            if hasattr(agent_info, "metadata") and agent_info.metadata:
                raw_group = agent_info.metadata.get("deployment_group", "general")
                # Ensure it's one of the allowed values
                if raw_group in ["explorers", "early_adopters", "general"]:
                    group = raw_group
                else:
                    group = "general"

            # Get version info
            current_version = agent_info.current_version or "unknown"

            # Parse timestamps
            last_transition_at = None
            last_work_state_at = None

            if agent_info.last_work_state_at:
                try:
                    last_work_state_at = datetime.fromisoformat(
                        agent_info.last_work_state_at.replace("Z", "+00:00")
                    )
                except Exception:
                    pass

            # Get last transition time from version_transitions
            if agent_info.version_transitions:
                last_transition = agent_info.version_transitions[-1]
                if "timestamp" in last_transition:
                    try:
                        last_transition_at = datetime.fromisoformat(
                            last_transition["timestamp"].replace("Z", "+00:00")
                        )
                    except Exception:
                        pass

            metrics.append(
                AgentVersionAdoption(
                    agent_id=agent_id,
                    agent_name=agent_info.name,
                    current_version=current_version,
                    last_transition_at=last_transition_at,
                    last_work_state_at=last_work_state_at,
                    deployment_group=group,
                )
            )

        return metrics
