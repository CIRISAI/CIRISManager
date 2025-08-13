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
            if hasattr(deployment, "canary_phase") and deployment.canary_phase:
                phase = self._parse_deployment_phase(deployment.canary_phase)

            # Parse timestamps - ensure created_at is never None
            created_at = (
                self._parse_timestamp(deployment.created_at)
                if hasattr(deployment, "created_at") and deployment.created_at
                else None
            )
            if created_at is None:
                created_at = datetime.now(timezone.utc)
            staged_at = (
                self._parse_timestamp(deployment.staged_at)
                if hasattr(deployment, "staged_at")
                else None
            )
            started_at = (
                self._parse_timestamp(deployment.started_at)
                if hasattr(deployment, "started_at")
                else None
            )
            completed_at = (
                self._parse_timestamp(deployment.completed_at)
                if hasattr(deployment, "completed_at")
                else None
            )

            # Calculate duration if completed
            duration_seconds = None
            if started_at and completed_at:
                duration_seconds = int((completed_at - started_at).total_seconds())

            return DeploymentMetrics(
                deployment_id=deployment.deployment_id,
                status=status,
                phase=phase,
                agent_image=deployment.agent_image
                if hasattr(deployment, "agent_image")
                else "unknown",
                gui_image=deployment.gui_image if hasattr(deployment, "gui_image") else None,
                agents_total=deployment.agents_total if hasattr(deployment, "agents_total") else 0,
                agents_staged=deployment.agents_staged
                if hasattr(deployment, "agents_staged")
                else 0,
                agents_updated=deployment.agents_updated
                if hasattr(deployment, "agents_updated")
                else 0,
                agents_failed=deployment.agents_failed
                if hasattr(deployment, "agents_failed")
                else 0,
                agents_deferred=deployment.agents_deferred
                if hasattr(deployment, "agents_deferred")
                else 0,
                created_at=created_at,
                staged_at=staged_at,
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=duration_seconds,
                initiated_by=deployment.initiated_by
                if hasattr(deployment, "initiated_by")
                else None,
                message=deployment.message if hasattr(deployment, "message") else None,
                is_rollback=deployment.is_rollback if hasattr(deployment, "is_rollback") else False,
                rollback_from_deployment=deployment.rollback_from_deployment
                if hasattr(deployment, "rollback_from_deployment")
                else None,
            )

        except Exception as e:
            logger.error(f"Failed to convert deployment to metrics: {e}")
            return None

    def _parse_deployment_status(self, status: str) -> DeploymentStatus:
        """Parse deployment status string to enum."""
        status_lower = status.lower()
        if status_lower == "pending":
            return DeploymentStatus.PENDING
        elif status_lower == "staged":
            return DeploymentStatus.STAGED
        elif status_lower == "in_progress":
            return DeploymentStatus.IN_PROGRESS
        elif status_lower == "rolling_back":
            return DeploymentStatus.ROLLING_BACK
        elif status_lower == "completed":
            return DeploymentStatus.COMPLETED
        elif status_lower == "failed":
            return DeploymentStatus.FAILED
        elif status_lower == "cancelled":
            return DeploymentStatus.CANCELLED
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
            # Default to explorers for unknown phases
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
        states = await self.collect_version_states()
        adoptions = await self.collect_agent_adoptions()
        return states, adoptions

    async def collect_with_timeout(self) -> Tuple[List[VersionState], List[AgentVersionAdoption]]:
        """
        Collect with timeout protection.

        This method is required for compatibility with the orchestrator.
        """
        import asyncio

        try:
            return await asyncio.wait_for(self.collect(), timeout=self.timeout_seconds)
        except asyncio.TimeoutError:
            logger.warning(f"{self.name} collection timed out after {self.timeout_seconds}s")
            return [], []
        except Exception as e:
            logger.error(f"{self.name} collection failed: {e}")
            return [], []

    async def is_available(self) -> bool:
        """Check if version tracker is available."""
        return self.manager is not None and hasattr(self.manager, "version_tracker")

    def get_stats(self) -> dict:
        """Get collector statistics (for compatibility)."""
        return {
            "name": self.name,
            "timeout_seconds": self.timeout_seconds,
            "available": True,
        }

    async def collect_version_states(self) -> List[VersionState]:
        """
        Collect version state for all component types.

        Returns state for: agents, gui, nginx.
        """
        if not self.manager or not hasattr(self.manager, "version_tracker"):
            return []

        states = []

        # Get version data from version tracker
        try:
            tracker = self.manager.version_tracker

            # Call get_rollback_options to get version data
            version_data = await tracker.get_rollback_options()

            # Process each component type
            for component_name, component_data in version_data.items():
                if not component_data:
                    continue

                # Map component names to ComponentType enum
                component_type = self._parse_component_type(component_name)

                # Create VersionState from the data
                version_state = VersionState(
                    component_type=component_type,
                    current=self._create_version_info_from_dict(component_data.get("current")),
                    previous=self._create_version_info_from_dict(component_data.get("n_minus_1")),
                    fallback=self._create_version_info_from_dict(component_data.get("n_minus_2")),
                    staged=self._create_version_info_from_dict(component_data.get("staged")),
                    last_updated=datetime.now(timezone.utc),
                )
                states.append(version_state)

        except Exception as e:
            logger.error(f"Failed to collect version state: {e}")

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

    def _create_version_info_from_dict(self, version_data: Optional[dict]) -> Optional[VersionInfo]:
        """Create VersionInfo from version tracker dict data."""
        if not version_data:
            return None

        try:
            # Extract image and version
            image = version_data.get("image", "unknown")

            # Extract version from image tag
            if ":" in image:
                version = image.split(":")[-1]
            else:
                version = "unknown"

            # Parse deployed_at timestamp
            deployed_at = datetime.now(timezone.utc)
            if "deployed_at" in version_data and version_data["deployed_at"]:
                try:
                    deployed_at = datetime.fromisoformat(
                        version_data["deployed_at"].replace("Z", "+00:00")
                    )
                except Exception:
                    pass

            return VersionInfo(
                image=image,
                digest=version_data.get("digest"),
                tag=version,  # Use version as tag
                deployed_at=deployed_at,
                deployment_id=version_data.get("deployment_id"),
            )
        except Exception as e:
            logger.debug(f"Failed to create version info: {e}")
            # Return a default VersionInfo on error
            return VersionInfo(
                image="unknown",
                digest=None,
                tag="unknown",
                deployed_at=datetime.now(timezone.utc),
                deployment_id=None,
            )

    async def collect_agent_adoptions(self) -> List[AgentVersionAdoption]:
        """
        Collect version adoption by agent.

        Returns current version for each individual agent.
        """
        if not self.manager or not hasattr(self.manager, "agent_registry"):
            return []

        registry = self.manager.agent_registry
        adoptions = []

        try:
            # Get all agents
            agents = registry.list_agents()

            if not agents:
                return []

            # Create per-agent adoption entries
            for agent in agents:
                # Get agent details
                agent_id = getattr(agent, "agent_id", "unknown")
                agent_name = getattr(agent, "agent_name", getattr(agent, "name", "unknown"))
                version = getattr(agent, "version", "unknown")

                # Try to get transition times
                last_transition_at = None
                last_work_state_at = None

                # Get deployment group (default to general)
                from typing import Literal

                deployment_group: Literal["explorers", "early_adopters", "general"] = "general"
                if hasattr(agent, "deployment_group"):
                    group = getattr(agent, "deployment_group")
                    if group in ["explorers", "early_adopters", "general"]:
                        deployment_group = group  # type: ignore[assignment]

                # Create adoption entry for this agent
                adoption = AgentVersionAdoption(
                    agent_id=agent_id,
                    agent_name=agent_name,
                    current_version=version,
                    last_transition_at=last_transition_at,
                    last_work_state_at=last_work_state_at,
                    deployment_group=deployment_group,
                )
                adoptions.append(adoption)

        except Exception as e:
            logger.error(f"Failed to collect agent adoptions: {e}")

        return adoptions
