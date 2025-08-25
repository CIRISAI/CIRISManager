"""
Deployment orchestrator for CD operations.

Handles canary deployments, graceful shutdowns, and agent update coordination.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
from uuid import uuid4
import httpx
import aiofiles  # type: ignore

from ciris_manager.agent_auth import get_agent_auth
from ciris_manager.models import (
    AgentInfo,
    UpdateNotification,
    DeploymentStatus,
    AgentUpdateResponse,
)
from ciris_manager.docker_registry import DockerRegistryClient
from ciris_manager.version_tracker import get_version_tracker
from ciris_manager.utils.log_sanitizer import sanitize_agent_id, sanitize_for_log

logger = logging.getLogger(__name__)

# Global deployment orchestrator instance
_orchestrator: Optional["DeploymentOrchestrator"] = None


def get_deployment_orchestrator() -> "DeploymentOrchestrator":
    """Get the global deployment orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        from ciris_manager.manager_core import get_manager

        manager = get_manager()
        _orchestrator = DeploymentOrchestrator(manager)
    return _orchestrator


class DeploymentOrchestrator:
    """Orchestrates deployments across agent fleet."""

    def __init__(self, manager: Optional[Any] = None) -> None:
        """Initialize deployment orchestrator."""
        self.deployments: Dict[str, DeploymentStatus] = {}
        self.pending_deployments: Dict[
            str, DeploymentStatus
        ] = {}  # Staged deployments awaiting approval
        self.current_deployment: Optional[str] = None
        self._deployment_lock = asyncio.Lock()
        self.deployment_paused: Dict[str, bool] = {}  # Track paused deployments
        self.manager = manager

        # Track background tasks to prevent garbage collection
        self._background_tasks: set = set()

        # Set up persistent storage
        self.state_dir = Path("/var/lib/ciris-manager")
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            # Fall back to temp directory for testing
            import tempfile

            self.state_dir = Path(tempfile.gettempdir()) / "ciris-manager"
            self.state_dir.mkdir(parents=True, exist_ok=True)
        self.deployment_state_file = self.state_dir / "deployment_state.json"

        # Load persisted state on startup
        self._load_state()

        # Initialize Docker registry client with GitHub token if available
        github_token = os.getenv("GITHUB_TOKEN") or os.getenv("CIRIS_GITHUB_TOKEN")
        self.registry_client = DockerRegistryClient(auth_token=github_token)

    def _load_state(self) -> None:
        """Load deployment state from persistent storage (sync version for __init__)."""
        if self.deployment_state_file.exists():
            try:
                with open(self.deployment_state_file, "r") as f:
                    state = json.load(f)
                    # Restore deployments
                    for deployment_id, deployment_data in state.get("deployments", {}).items():
                        self.deployments[deployment_id] = DeploymentStatus(**deployment_data)
                    # Restore pending deployments
                    for deployment_id, deployment_data in state.get(
                        "pending_deployments", {}
                    ).items():
                        self.pending_deployments[deployment_id] = DeploymentStatus(
                            **deployment_data
                        )
                    # Restore current deployment
                    self.current_deployment = state.get("current_deployment")
                    logger.info(
                        f"Loaded deployment state with {len(self.deployments)} deployments "
                        f"and {len(self.pending_deployments)} pending deployments"
                    )

                    # Check for in-progress deployments that need recovery or marking as failed
                    if self.current_deployment and self.current_deployment in self.deployments:
                        deployment = self.deployments[self.current_deployment]
                        if deployment.status == "in_progress":
                            # Check if we have agents that were in the middle of being restarted
                            if deployment.agents_pending_restart or deployment.agents_in_progress:
                                logger.warning(
                                    f"Found interrupted deployment {self.current_deployment} after restart. "
                                    f"Agents pending restart: {deployment.agents_pending_restart}, "
                                    f"Agents in progress: {list(deployment.agents_in_progress.keys())}"
                                )
                                # Schedule recovery of interrupted operations
                                asyncio.create_task(self._recover_interrupted_deployment(deployment))
                            else:
                                logger.warning(
                                    f"Found in-progress deployment {self.current_deployment} after restart. "
                                    "Marking as failed due to manager restart during deployment."
                                )
                                deployment.status = "failed"
                                deployment.completed_at = datetime.now(timezone.utc).isoformat()
                                deployment.message = "Deployment interrupted by manager restart"
                                # Clear the current deployment lock to allow new deployments
                                self.current_deployment = None
                                self._save_state()
            except Exception as e:
                logger.warning(f"Failed to load deployment state: {e}")

    def _save_state(self) -> None:
        """Save deployment state synchronously (for compatibility)."""
        # For now, use synchronous implementation to avoid test failures
        try:
            state = {
                "deployments": {
                    deployment_id: deployment.model_dump()
                    for deployment_id, deployment in self.deployments.items()
                },
                "pending_deployments": {
                    deployment_id: deployment.model_dump()
                    for deployment_id, deployment in self.pending_deployments.items()
                },
                "current_deployment": self.current_deployment,
                "saved_at": datetime.now(timezone.utc).isoformat(),
            }

            # Write to temp file first, then move atomically
            temp_file = self.deployment_state_file.with_suffix(".tmp")
            with open(temp_file, "w") as f:
                json.dump(state, f, indent=2)

            # Atomic rename
            temp_file.replace(self.deployment_state_file)
            logger.debug(f"Saved deployment state with {len(self.deployments)} deployments")
        except Exception as e:
            logger.error(f"Failed to save deployment state: {e}")

    async def _save_state_async(self) -> None:
        """Save deployment state to persistent storage (async version)."""
        try:
            state = {
                "deployments": {
                    deployment_id: deployment.model_dump()
                    for deployment_id, deployment in self.deployments.items()
                },
                "pending_deployments": {
                    deployment_id: deployment.model_dump()
                    for deployment_id, deployment in self.pending_deployments.items()
                },
                "current_deployment": self.current_deployment,
                "saved_at": datetime.now(timezone.utc).isoformat(),
            }

            # Write to temp file first, then move atomically
            temp_file = self.deployment_state_file.with_suffix(".tmp")
            async with aiofiles.open(temp_file, "w") as f:
                await f.write(json.dumps(state, indent=2))

            # Atomic rename (this is still sync as it's a filesystem operation)
            temp_file.replace(self.deployment_state_file)
            logger.debug(f"Saved deployment state with {len(self.deployments)} deployments")
        except Exception as e:
            logger.error(f"Failed to save deployment state: {e}")

    async def stop(self) -> None:
        """Save state before shutdown."""
        logger.info("Saving deployment state before shutdown...")
        self._save_state()
        logger.info(
            f"Deployment state saved: {len(self.deployments)} deployments, {len(self.pending_deployments)} pending"
        )

    def _add_event(
        self, deployment_id: str, event_type: str, message: str, details: Optional[dict] = None
    ) -> None:
        """Add an event to deployment timeline."""
        deployment = self.deployments.get(deployment_id) or self.pending_deployments.get(
            deployment_id
        )
        if deployment:
            event: dict[str, Any] = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": event_type,
                "message": message,
            }
            if details:
                event["details"] = details
            deployment.events.append(event)
            # Save state after adding event
            self._save_state()

    async def start_single_agent_deployment(
        self, notification: UpdateNotification, agent: AgentInfo
    ) -> DeploymentStatus:
        """
        Start a deployment for a single agent (for testing purposes).

        This method allows targeted deployment to a specific agent,
        bypassing canary groups and deploying immediately.

        Args:
            notification: Update notification with target version
            agent: The specific agent to deploy to

        Returns:
            Deployment status
        """
        async with self._deployment_lock:
            if self.current_deployment:
                raise ValueError(f"Deployment {self.current_deployment} already in progress")

            deployment_id = str(uuid4())

            # Pull the new image first
            logger.info(f"Pulling image {notification.agent_image} for single agent deployment")
            pull_results = await self._pull_images(notification)

            if not pull_results["success"]:
                return DeploymentStatus(
                    deployment_id=deployment_id,
                    notification=notification,
                    agents_total=1,
                    agents_updated=0,
                    agents_deferred=0,
                    agents_failed=1,
                    started_at=datetime.now(timezone.utc).isoformat(),
                    staged_at=None,
                    completed_at=datetime.now(timezone.utc).isoformat(),
                    status="failed",
                    message=f"Failed to pull image: {pull_results.get('error', 'Unknown error')}",
                    canary_phase=None,
                )

            # Check if agent actually needs updating
            if not notification.agent_image:
                raise ValueError("Agent image is required for deployment")
            needs_update = await self._agent_needs_update(agent, notification.agent_image)

            if not needs_update:
                logger.info(f"Agent {agent.agent_id} already running {notification.agent_image}")
                return DeploymentStatus(
                    deployment_id=deployment_id,
                    notification=notification,
                    agents_total=1,
                    agents_updated=0,
                    agents_deferred=0,
                    agents_failed=0,
                    started_at=datetime.now(timezone.utc).isoformat(),
                    staged_at=None,
                    completed_at=datetime.now(timezone.utc).isoformat(),
                    status="completed",
                    message=f"Agent {agent.agent_id} already running target version",
                    canary_phase=None,
                )

            # Create deployment status
            status = DeploymentStatus(
                deployment_id=deployment_id,
                notification=notification,
                agents_total=1,
                agents_updated=0,
                agents_deferred=0,
                agents_failed=0,
                started_at=datetime.now(timezone.utc).isoformat(),
                staged_at=None,
                completed_at=None,
                status="in_progress",
                message=f"Single agent deployment to {agent.agent_id}: {notification.message}",
                canary_phase=None,  # No canary for single agent
            )

            self.deployments[deployment_id] = status
            self.current_deployment = deployment_id

            # Persist state
            self._save_state()

            # Start the deployment in background
            task = asyncio.create_task(
                self._execute_single_agent_deployment(deployment_id, notification, agent)
            )
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

            return status

    async def _execute_single_agent_deployment(
        self, deployment_id: str, notification: UpdateNotification, agent: AgentInfo
    ) -> None:
        """Execute single agent deployment."""
        try:
            status = self.deployments[deployment_id]

            # Update the single agent
            logger.info(f"Updating agent {agent.agent_id} to {notification.agent_image}")
            update_response = await self._update_single_agent(deployment_id, notification, agent)

            if update_response.decision == "accept":
                status.agents_updated = 1

                # Wait for agent to reach WORK state
                logger.info(f"Waiting for agent {agent.agent_id} to reach WORK state")
                success, results = await self._check_canary_group_health(
                    deployment_id=deployment_id,
                    agents=[agent],
                    phase_name="single_agent",
                    wait_for_work_minutes=5,  # 5 minutes for single agent
                    stability_minutes=1,  # 1 minute stability
                )

                if success:
                    status.status = "completed"
                    status.message = f"Successfully deployed to {agent.agent_id}"

                    # Promote staged version to current
                    tracker = get_version_tracker()
                    if notification.agent_image:
                        await tracker.promote_staged_version("agent", deployment_id)
                    if notification.gui_image:
                        await tracker.promote_staged_version("gui", deployment_id)
                else:
                    status.status = "failed"
                    status.agents_failed = 1
                    status.agents_updated = 0
                    status.message = f"Agent {agent.agent_id} failed to reach stable WORK state"

            elif update_response.decision == "defer":
                status.agents_deferred = 1
                status.status = "completed"
                status.message = f"Agent {agent.agent_id} deferred the update"
            else:
                status.agents_failed = 1
                status.status = "failed"
                status.message = (
                    f"Agent {agent.agent_id} rejected the update: {update_response.reason}"
                )

            status.completed_at = datetime.now(timezone.utc).isoformat()

        except Exception as e:
            logger.error(f"Single agent deployment {deployment_id} failed: {e}")
            status.status = "failed"
            status.agents_failed = 1
            status.message = f"Deployment failed: {str(e)}"
            status.completed_at = datetime.now(timezone.utc).isoformat()
        finally:
            self.current_deployment = None
            self._save_state()

    async def _agent_needs_update(self, agent: AgentInfo, target_image: str) -> bool:
        """Check if a specific agent needs updating to target image."""
        try:
            import docker

            client = docker.from_env()

            container = client.containers.get(agent.container_name)
            current_image: str = ""
            if container.image and container.image.tags:
                current_image = container.image.tags[0]
            elif container.image and container.image.id:
                current_image = container.image.id
            else:
                # Can't determine current image, assume update needed
                return True

            # Normalize image names for comparison
            if current_image and ":" in current_image:
                current = current_image.split(":")[-1]
            else:
                current = "latest"

            target = target_image.split(":")[-1] if ":" in target_image else "latest"

            return bool(current != target)

        except Exception as e:
            logger.warning(f"Could not check if agent {agent.agent_id} needs update: {e}")
            return True  # Assume update needed if we can't check

    async def start_deployment(
        self,
        notification: UpdateNotification,
        agents: List[AgentInfo],
    ) -> DeploymentStatus:
        """
        Start a new deployment.

        Args:
            notification: Update notification from CD
            agents: List of all agents

        Returns:
            Deployment status
        """
        async with self._deployment_lock:
            if self.current_deployment:
                raise ValueError(f"Deployment {self.current_deployment} already in progress")

            # Pull new images first to ensure we have the latest
            logger.info("Pulling new images before checking for updates...")
            pull_results = await self._pull_images(notification)

            if not pull_results["success"]:
                logger.error(f"Failed to pull images: {pull_results.get('error', 'Unknown error')}")
                return DeploymentStatus(
                    deployment_id=str(uuid4()),
                    notification=notification,
                    agents_total=len(agents),
                    agents_updated=0,
                    agents_deferred=0,
                    agents_failed=0,
                    started_at=datetime.now(timezone.utc).isoformat(),
                    staged_at=None,
                    completed_at=datetime.now(timezone.utc).isoformat(),
                    status="failed",
                    message=f"Failed to pull images: {pull_results.get('error', 'Unknown error')}",
                    canary_phase=None,
                )

            # Check if any agents actually need updating
            agents_needing_update, nginx_needs_update = await self._check_agents_need_update(
                notification, agents
            )

            if not agents_needing_update and not nginx_needs_update:
                # No agents need updating and no nginx update - this is a no-op deployment
                logger.info("No agents or nginx need updating - images unchanged")
                return DeploymentStatus(
                    deployment_id=str(uuid4()),
                    notification=notification,
                    agents_total=len(agents),
                    agents_updated=0,
                    agents_deferred=0,
                    agents_failed=0,
                    started_at=datetime.now(timezone.utc).isoformat(),
                    staged_at=None,
                    completed_at=datetime.now(timezone.utc).isoformat(),
                    status="completed",
                    message="No update needed - images unchanged",
                    canary_phase=None,
                )

            # Handle nginx-only updates immediately
            if nginx_needs_update and not agents_needing_update:
                logger.info("Only nginx/GUI needs updating - deploying immediately")
                deployment_id = str(uuid4())

                # Update GUI/nginx containers
                nginx_updated = await self._update_nginx_container(
                    notification.gui_image,  # type: ignore[arg-type]
                    notification.nginx_image,
                )

                status = DeploymentStatus(
                    deployment_id=deployment_id,
                    notification=notification,
                    agents_total=0,
                    agents_updated=0,
                    agents_deferred=0,
                    agents_failed=0,
                    started_at=datetime.now(timezone.utc).isoformat(),
                    staged_at=None,
                    completed_at=datetime.now(timezone.utc).isoformat(),
                    status="completed" if nginx_updated else "failed",
                    message="GUI container updated"
                    if nginx_updated
                    else "Failed to update GUI container",
                    canary_phase=None,
                )

                # Add to deployments history
                self.deployments[deployment_id] = status
                self._save_state()

                return status

            deployment_id = str(uuid4())
            status = DeploymentStatus(
                deployment_id=deployment_id,
                notification=notification,
                agents_total=len(agents_needing_update),
                agents_updated=0,
                agents_deferred=0,
                agents_failed=0,
                started_at=datetime.now(timezone.utc).isoformat(),
                staged_at=None,
                completed_at=None,
                status="in_progress",
                message=notification.message,
                canary_phase="explorers" if notification.strategy == "canary" else None,
            )

            self.deployments[deployment_id] = status
            self.current_deployment = deployment_id

            # Save state after creating deployment
            self._save_state()

            # Start deployment in background with only agents that need updates
            task = asyncio.create_task(
                self._run_deployment(deployment_id, notification, agents_needing_update)
            )
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

            return status

    async def stage_deployment(
        self,
        notification: UpdateNotification,
        agents: List[AgentInfo],
    ) -> str:
        """
        Stage a deployment for human review (Wisdom-Based Deferral).

        Args:
            notification: Update notification from CD
            agents: List of all agents

        Returns:
            Deployment ID of staged deployment
        """
        deployment_id = str(uuid4())

        # Determine affected agents count
        agents_needing_update, nginx_needs_update = await self._check_agents_need_update(
            notification, agents
        )

        # Set appropriate counts based on what's being updated
        if nginx_needs_update and not agents_needing_update:
            # GUI-only update
            agents_total = 0  # No agents affected
            message = f"GUI Update: {notification.message}"
        elif agents_needing_update:
            # Agent update (possibly with GUI)
            agents_total = len(agents_needing_update)
            message = f"Staged: {notification.message}"
        else:
            # No actual updates needed
            agents_total = 0
            message = "No changes detected"

        status = DeploymentStatus(
            deployment_id=deployment_id,
            notification=notification,
            agents_total=agents_total,
            agents_updated=0,
            agents_deferred=0,
            agents_failed=0,
            started_at=None,  # Not started yet
            completed_at=None,
            status="pending",
            message=message,
            staged_at=datetime.now(timezone.utc).isoformat(),
            canary_phase=None,
        )

        self.pending_deployments[deployment_id] = status

        # Add staging event
        self._add_event(
            deployment_id,
            "staged",
            "Deployment staged for review",
            {"affected_agents": agents_total, "gui_update": nginx_needs_update},
        )

        # Track staged versions as n+1
        tracker = get_version_tracker()

        # Stage agent version if provided
        if notification.agent_image:
            await tracker.stage_version(
                "agent",  # Use singular form to keep separate from GUI
                notification.agent_image,
                digest=None,  # Could get from registry
                deployment_id=deployment_id,
                deployed_by="CD Pipeline",
            )

        # Stage GUI version if provided
        if notification.gui_image:
            await tracker.stage_version(
                "gui",
                notification.gui_image,
                digest=None,
                deployment_id=deployment_id,
                deployed_by="CD Pipeline",
            )

        # Stage nginx version if we have one
        # Note: nginx image rarely changes, but we should track it
        if hasattr(notification, "nginx_image") and notification.nginx_image:
            await tracker.stage_version(
                "nginx",
                notification.nginx_image,
                digest=None,
                deployment_id=deployment_id,
                deployed_by="CD Pipeline",
            )

        logger.info(f"Staged deployment {deployment_id} for review with version tracking")

        # Save state to persist the staged deployment
        self._save_state()

        return deployment_id

    async def get_pending_deployment(self) -> Optional[DeploymentStatus]:
        """Get the currently pending deployment if any."""
        if not self.pending_deployments:
            return None
        # Return the most recent pending deployment
        return next(iter(self.pending_deployments.values()))

    async def launch_staged_deployment(self, deployment_id: str) -> bool:
        """
        Launch a previously staged deployment.

        Args:
            deployment_id: ID of staged deployment

        Returns:
            True if deployment was launched, False if not found
        """
        if deployment_id not in self.pending_deployments:
            return False

        async with self._deployment_lock:
            if self.current_deployment:
                raise ValueError(f"Deployment {self.current_deployment} already in progress")

            deployment = self.pending_deployments.pop(deployment_id)
            deployment.status = "in_progress"
            deployment.started_at = datetime.now(timezone.utc).isoformat()

            # Determine canary phase if applicable
            if deployment.notification and deployment.notification.strategy == "canary":
                deployment.canary_phase = "explorers"

            self.deployments[deployment_id] = deployment
            self.current_deployment = deployment_id
            self._save_state()

            # Get agents needing update
            from ciris_manager.docker_discovery import DockerAgentDiscovery

            if not self.manager or not self.manager.agent_registry:
                raise ValueError("Manager or agent_registry not available")

            discovery = DockerAgentDiscovery(self.manager.agent_registry)
            agents = discovery.discover_agents()

            if not deployment.notification:
                raise ValueError(f"Deployment {deployment_id} has no notification")

            agents_needing_update, nginx_needs_update = await self._check_agents_need_update(
                deployment.notification, agents
            )

            # Check if this is a GUI-only update
            if nginx_needs_update and not agents_needing_update:
                # Handle GUI-only update immediately
                logger.info(f"Deployment {deployment_id} is GUI-only, updating directly")

                # Update GUI/nginx containers
                gui_image = deployment.notification.gui_image or ""
                nginx_image = deployment.notification.nginx_image or ""
                nginx_updated = await self._update_nginx_container(
                    gui_image,
                    nginx_image,
                )

                # Update deployment status
                deployment.status = "completed" if nginx_updated else "failed"
                deployment.completed_at = datetime.now(timezone.utc).isoformat()
                deployment.message = (
                    "GUI Update: GUI container updated successfully"
                    if nginx_updated
                    else "GUI Update: Failed to update GUI container"
                )
                # Ensure agents_total is 0 for GUI-only updates
                deployment.agents_total = 0
                self.current_deployment = None
                self._save_state()

                logger.info(
                    f"GUI-only deployment {deployment_id} {'succeeded' if nginx_updated else 'failed'}"
                )
                return True

            # Start normal agent deployment in background
            task = asyncio.create_task(
                self._run_deployment(deployment_id, deployment.notification, agents_needing_update)
            )
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

            logger.info(f"Launched staged deployment {deployment_id}")
            return True

    async def reject_staged_deployment(
        self, deployment_id: str, reason: str = "Rejected by operator"
    ) -> bool:
        """
        Reject a staged deployment.

        Args:
            deployment_id: ID of staged deployment
            reason: Reason for rejection

        Returns:
            True if deployment was rejected, False if not found
        """
        if deployment_id not in self.pending_deployments:
            return False

        deployment = self.pending_deployments.pop(deployment_id)
        deployment.status = "rejected"
        deployment.completed_at = datetime.now(timezone.utc).isoformat()
        deployment.message = reason

        self.deployments[deployment_id] = deployment
        self._save_state()

        # Audit the rejection
        from ciris_manager.audit import audit_deployment_action

        audit_deployment_action("reject", deployment_id, {"reason": reason})

        logger.info(f"Rejected staged deployment {deployment_id}: {reason}")
        return True

    async def cancel_stuck_deployment(
        self, deployment_id: str, reason: str = "Cancelled due to stuck state"
    ) -> bool:
        """
        Cancel a stuck deployment to allow restarting.

        Args:
            deployment_id: ID of stuck deployment
            reason: Reason for cancellation

        Returns:
            True if deployment was cancelled, False if not found
        """
        if deployment_id not in self.deployments:
            return False

        deployment = self.deployments[deployment_id]

        # Clear current deployment if this is it
        if self.current_deployment == deployment_id:
            self.current_deployment = None
            logger.info(f"Cleared current deployment lock for {deployment_id}")

        # If this was a failed deployment, re-stage it as pending for retry
        if deployment.status == "failed" and deployment.notification:
            # Create a new pending deployment with the same notification
            new_deployment_id = str(uuid4())
            new_status = DeploymentStatus(
                deployment_id=new_deployment_id,
                notification=deployment.notification,  # Re-use the same notification
                agents_total=deployment.agents_total,
                agents_updated=0,
                agents_deferred=0,
                agents_failed=0,
                started_at=None,  # Not started yet
                completed_at=None,
                status="pending",
                message=f"Ready to retry: {deployment.notification.message}",
                staged_at=datetime.now(timezone.utc).isoformat(),
                canary_phase=None,
            )

            # Add to pending deployments
            self.pending_deployments[new_deployment_id] = new_status
            logger.info(f"Re-staged failed deployment as {new_deployment_id} for retry")

            # Update the original deployment as cancelled
            deployment.status = "cancelled"
            deployment.completed_at = datetime.now(timezone.utc).isoformat()
            deployment.message = f"{reason} - Re-staged as {new_deployment_id}"
        else:
            # Just cancel normally
            deployment.status = "cancelled"
            deployment.completed_at = datetime.now(timezone.utc).isoformat()
            deployment.message = reason

        # Save state
        self._save_state()

        # Audit the cancellation
        from ciris_manager.audit import audit_deployment_action

        audit_deployment_action(
            deployment_id=deployment_id, action="deployment_cancelled", details={"reason": reason}
        )

        logger.info(f"Cancelled stuck deployment {deployment_id}: {reason}")
        return True

    async def pause_deployment(self, deployment_id: str) -> bool:
        """
        Pause an active deployment.

        Args:
            deployment_id: ID of active deployment

        Returns:
            True if deployment was paused, False if not found/not active
        """
        if deployment_id not in self.deployments:
            return False

        deployment = self.deployments[deployment_id]
        if deployment.status != "in_progress":
            return False

        self.deployment_paused[deployment_id] = True
        deployment.status = "paused"

        logger.info(f"Paused deployment {deployment_id}")
        return True

    async def rollback_deployment(
        self,
        deployment_id: str,
        target_version: str = "n-1",
        target_versions: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Initiate rollback of a deployment.

        Args:
            deployment_id: ID of deployment to rollback
            target_version: Version to rollback to ("n-1", "n-2", or specific version)
            target_versions: Granular version control per component

        Returns:
            True if rollback initiated, False if not found
        """
        if deployment_id not in self.deployments:
            return False

        deployment = self.deployments[deployment_id]
        deployment.status = "rolling_back"

        # Store rollback target in deployment metadata
        if deployment.notification:
            if not deployment.notification.metadata:
                deployment.notification.metadata = {}

            deployment.notification.metadata["rollback_target"] = target_version
            if target_versions:
                deployment.notification.metadata["rollback_targets"] = target_versions

        # Start rollback process
        task = asyncio.create_task(
            self._rollback_agents(deployment, target_version, target_versions)
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

        logger.info(f"Initiated rollback for deployment {deployment_id} to {target_version}")
        return True

    async def get_current_images(self) -> Dict[str, Any]:
        """Get current running container images."""
        import json

        result = {}

        try:
            # Get agent image from running containers
            process = await asyncio.create_subprocess_exec(
                "docker",
                "ps",
                "--format",
                "json",
                "--filter",
                "label=ciris.agent=true",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()

            if stdout:
                for line in stdout.decode().strip().split("\n"):
                    if line:
                        container = json.loads(line)
                        if "Image" in container:
                            result["agent_image"] = container["Image"]
                            break

            # Get GUI image
            process = await asyncio.create_subprocess_exec(
                "docker",
                "ps",
                "--format",
                "json",
                "--filter",
                "name=ciris-gui",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()

            if stdout:
                for line in stdout.decode().strip().split("\n"):
                    if line:
                        container = json.loads(line)
                        if "Image" in container:
                            result["gui_image"] = container["Image"]
                            break

        except Exception as e:
            logger.error(f"Failed to get current images: {e}")

        return result

    async def get_rollback_versions(self, deployment_id: str) -> Optional[Dict[str, Any]]:
        """
        Get available rollback versions for a deployment.

        Returns version history for all components that can be rolled back.
        """
        if deployment_id not in self.deployments:
            return None

        result: Dict[str, Any] = {
            "deployment_id": deployment_id,
            "agent": {},  # Individual agent versions
            "gui": {},
            "nginx": {},
        }

        # Get agent versions
        if self.manager and hasattr(self.manager, "agent_registry"):
            for agent_id, agent_info in self.manager.agent_registry.agents.items():
                if hasattr(agent_info, "metadata"):
                    previous = agent_info.metadata.get("previous_images", {})
                    current = agent_info.metadata.get("current_images", {})

                    agent_versions = {
                        "current": current.get("agent_tag", current.get("agent", "unknown")),
                        "n-1": previous.get("n-1", "not available"),
                        "n-2": previous.get("n-2", "not available"),
                    }
                    result["agent"][agent_id] = agent_versions

        # Get GUI versions
        gui_file = Path("/opt/ciris/metadata/gui_versions.json")
        if gui_file.exists():
            async with aiofiles.open(gui_file, "r") as f:
                content = await f.read()
                gui_versions = json.loads(content)
                result["gui"] = {
                    "current": gui_versions.get("current", "unknown"),
                    "n-1": gui_versions.get("n-1", "not available"),
                    "n-2": gui_versions.get("n-2", "not available"),
                }

        # Get nginx versions
        nginx_file = Path("/opt/ciris/metadata/nginx_versions.json")
        if nginx_file.exists():
            async with aiofiles.open(nginx_file, "r") as f:
                content = await f.read()
                nginx_versions = json.loads(content)
                result["nginx"] = {
                    "current": nginx_versions.get("current", "unknown"),
                    "n-1": nginx_versions.get("n-1", "not available"),
                    "n-2": nginx_versions.get("n-2", "not available"),
                }

        return result

    async def get_deployment_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get deployment history."""
        deployments = sorted(
            self.deployments.values(), key=lambda d: d.started_at or "", reverse=True
        )[:limit]

        return [
            {
                "deployment_id": d.deployment_id,
                "started_at": d.started_at,
                "completed_at": d.completed_at,
                "status": d.status,
                "message": d.message,
                "agents_total": d.agents_total,
                "agents_updated": d.agents_updated,
                "agents_failed": d.agents_failed,
            }
            for d in deployments
        ]

    async def evaluate_and_stage(
        self,
        notification: UpdateNotification,
        agents: List[AgentInfo],
    ) -> str:
        """
        Evaluate deployment and either stage for review or execute immediately.

        GUI-only deployments with immediate strategy are executed right away.
        All other deployments are staged for human review.

        Args:
            notification: Update notification
            agents: List of agents

        Returns:
            Deployment ID
        """
        # Check if this is a GUI-only deployment with immediate strategy
        if (
            notification.strategy == "immediate"
            and notification.gui_image
            and not notification.agent_image
        ):
            # Check if GUI actually needs updating
            agents_needing_update, nginx_needs_update = await self._check_agents_need_update(
                notification, agents
            )

            if nginx_needs_update and not agents_needing_update:
                logger.info(
                    f"GUI-only immediate deployment - executing now: {notification.message}"
                )
                # Start the deployment immediately for GUI-only updates
                status = await self.start_deployment(notification, agents)
                return status.deployment_id

        # All other deployments are staged for human review
        logger.info(f"Staging deployment for human review: {notification.message}")
        return await self.stage_deployment(notification, agents)

    async def _requires_wisdom_based_deferral(
        self,
        notification: UpdateNotification,
        agents: List[AgentInfo],
    ) -> bool:
        """
        Determine if update requires human review (Wisdom-Based Deferral).

        Criteria for staging:
        - Major version updates
        - Updates affecting many agents (>5)
        - Updates with "breaking" or "major" in message
        - Manual strategy requested

        Args:
            notification: Update notification
            agents: List of agents

        Returns:
            True if staging required
        """
        # Manual strategy always requires approval
        if notification.strategy == "manual":
            return True

        # Check for major version bump
        if notification.agent_image:
            # Extract version from image tag
            parts = notification.agent_image.split(":")
            if len(parts) > 1:
                version = parts[-1]
                if version.startswith("v2") or version.startswith("2"):
                    logger.info("Major version update detected - requiring review")
                    return True

        # Check message for high-risk keywords
        if notification.message:
            risk_keywords = ["breaking", "major", "critical", "emergency"]
            message_lower = notification.message.lower()
            if any(keyword in message_lower for keyword in risk_keywords):
                logger.info("High-risk keywords in message - requiring review")
                return True

        # Check number of affected agents
        if len(agents) > 5:
            logger.info(f"Large fleet update ({len(agents)} agents) - requiring review")
            return True

        return False

    async def _propose_rollback(
        self,
        deployment_id: str,
        reason: str,
        affected_agents: List[AgentInfo],
        include_gui: bool = False,
        include_nginx: bool = False,
    ) -> None:
        """
        Propose rollback to human operator.

        Args:
            deployment_id: Deployment identifier
            reason: Why rollback is being proposed
            affected_agents: Agents that would be rolled back
            include_gui: Whether GUI container should be rolled back
            include_nginx: Whether nginx container should be rolled back
        """
        if deployment_id not in self.deployments:
            return

        deployment = self.deployments[deployment_id]

        # Prepare rollback targets
        rollback_targets: Dict[str, Any] = {}

        if affected_agents:
            rollback_targets["agent"] = [a.agent_id for a in affected_agents]
            rollback_targets["agent_versions"] = await self._get_previous_versions(affected_agents)

        if include_gui:
            rollback_targets["gui"] = "n-1"  # Default to previous version
            # Check if GUI version history exists
            gui_versions_file = Path("/opt/ciris/metadata/gui_versions.json")
            if gui_versions_file.exists():
                async with aiofiles.open(gui_versions_file, "r") as f:
                    content = await f.read()
                    gui_versions = json.loads(content)
                    rollback_targets["gui_version"] = gui_versions.get("n-1", "unknown")

        if include_nginx:
            rollback_targets["nginx"] = "n-1"  # Default to previous version
            # Check if nginx version history exists
            nginx_versions_file = Path("/opt/ciris/metadata/nginx_versions.json")
            if nginx_versions_file.exists():
                async with aiofiles.open(nginx_versions_file, "r") as f:
                    content = await f.read()
                    nginx_versions = json.loads(content)
                    rollback_targets["nginx_version"] = nginx_versions.get("n-1", "unknown")

        # Create rollback proposal
        rollback_proposal = {
            "deployment_id": deployment_id,
            "proposed_at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "rollback_targets": rollback_targets,
        }

        # Store proposal for UI to display
        if not hasattr(self, "rollback_proposals"):
            self.rollback_proposals = {}
        self.rollback_proposals[deployment_id] = rollback_proposal

        # Mark deployment as requiring attention
        deployment.status = "rollback_proposed"

        # Audit the proposal
        from ciris_manager.audit import audit_deployment_action

        audit_deployment_action(
            "rollback_proposed",
            deployment_id,
            {"reason": reason, "affected_agents": len(affected_agents)},
        )

        logger.warning(
            f"Rollback proposed for deployment {sanitize_for_log(deployment_id)}: {sanitize_for_log(reason)}. "
            f"Awaiting operator decision."
        )

    async def _get_previous_versions(self, agents: List[AgentInfo]) -> Dict[str, str]:
        """
        Get previous image versions for agents.

        Args:
            agents: List of agents

        Returns:
            Dictionary mapping agent_id to previous image version
        """
        previous_versions = {}

        for agent in agents:
            # Get from agent metadata if available
            if self.manager and hasattr(self.manager, "agent_registry"):
                agent_info = self.manager.agent_registry.get_agent(agent.agent_id)
                if agent_info and hasattr(agent_info, "metadata"):
                    # Look for n-1 version in metadata
                    previous_images = agent_info.metadata.get("previous_images", {})
                    if previous_images:
                        # Get the most recent previous version
                        previous_versions[agent.agent_id] = previous_images.get(
                            "n-1", previous_images.get("agent", "unknown")
                        )
                    else:
                        previous_versions[agent.agent_id] = "unknown"

        return previous_versions

    async def _rollback_agents(
        self,
        deployment: DeploymentStatus,
        target_version: str = "n-1",
        target_versions: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Rollback agents to specified versions.

        This works by updating docker-compose.yml with previous image tags
        and restarting containers. Since agents cannot consent when failed,
        this requires human operator approval.

        Args:
            deployment: Deployment to rollback
            target_version: Default version to rollback to ("n-1", "n-2", or specific)
            target_versions: Granular version control per component
        """
        logger.info(f"Starting rollback for deployment {deployment.deployment_id}")

        try:
            # Get rollback targets from deployment
            rollback_targets = {}
            if deployment.notification and deployment.notification.metadata:
                rollback_targets = deployment.notification.metadata.get("rollback_targets", {})
                # Legacy support for affected_agents
                affected_agents = deployment.notification.metadata.get("affected_agents", [])
                if affected_agents and not rollback_targets:
                    rollback_targets["agent"] = affected_agents

            # Rollback GUI/nginx if needed
            gui_target = target_version  # Default
            nginx_target = target_version  # Default

            if target_versions:
                gui_target = target_versions.get("gui", target_version)
                nginx_target = target_versions.get("nginx", target_version)
            elif rollback_targets:
                gui_target = rollback_targets.get("gui", target_version)
                nginx_target = rollback_targets.get("nginx", target_version)

            # Rollback GUI if applicable
            if gui_target:
                await self._rollback_gui_container(gui_target)

            # Rollback nginx if applicable
            if nginx_target:
                await self._rollback_nginx_container(nginx_target)

            # Rollback agents
            if self.manager and hasattr(self.manager, "agent_registry"):
                agent_list = rollback_targets.get("agent", [])
                for agent_id in agent_list:
                    agent_info = self.manager.agent_registry.get_agent(agent_id)
                    if not agent_info:
                        continue

                    # Get target version from metadata
                    if hasattr(agent_info, "metadata"):
                        previous_images = agent_info.metadata.get("previous_images", {})

                        # Check for agent-specific target version
                        agent_target = target_version
                        if target_versions and "agent" in target_versions:
                            agent_target = target_versions["agent"].get(agent_id, target_version)

                        # Get the appropriate image based on target
                        if agent_target in ["n-1", "n-2"]:
                            rollback_image = previous_images.get(agent_target)
                            if not rollback_image:
                                logger.warning(
                                    f"No {agent_target} version available for agent {agent_id}, skipping rollback"
                                )
                                continue
                        else:
                            # Specific version provided
                            rollback_image = agent_target

                        if rollback_image and rollback_image != "not available":
                            logger.info(
                                f"Rolling back {agent_id} to {rollback_image} (target: {agent_target})"
                            )

                            # Update the agent's image in docker-compose
                            # This would involve updating the compose file
                            # For now, we'll restart with the previous image tag
                            container_name = agent_info.container_name

                            # Stop container to force re-pull of n-1 image
                            await asyncio.create_subprocess_exec(
                                "docker",
                                "stop",
                                container_name,
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.PIPE,
                            )

                            # Update container with n-1 image
                            await asyncio.create_subprocess_exec(
                                "docker",
                                "run",
                                "-d",
                                "--name",
                                container_name,
                                "--restart",
                                "unless-stopped",
                                rollback_image,
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.PIPE,
                            )

                            # Update metadata to reflect rollback
                            agent_info.metadata["current_images"]["agent"] = rollback_image
                            self.manager.agent_registry.update_agent(agent_info)

            deployment.status = "rolled_back"
            deployment.completed_at = datetime.now(timezone.utc).isoformat()
            logger.info(f"Rollback completed for deployment {deployment.deployment_id}")

        except Exception as e:
            logger.error(f"Rollback failed: {e}")
            deployment.status = "rollback_failed"
            deployment.completed_at = datetime.now(timezone.utc).isoformat()

    async def _pull_images(self, notification: UpdateNotification) -> Dict[str, Any]:
        """
        Pull Docker images specified in the notification.

        Args:
            notification: Update notification with image details

        Returns:
            Dictionary with success status and any error messages
        """
        import asyncio

        results: Dict[str, Any] = {"success": True, "agent_image": None, "gui_image": None}

        try:
            # Pull agent image if specified
            if notification.agent_image:
                # Normalize image name to lowercase for Docker
                agent_image = notification.agent_image.lower()
                logger.info(f"Pulling agent image: {agent_image}")
                process = await asyncio.create_subprocess_exec(
                    "docker",
                    "pull",
                    agent_image,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await process.communicate()

                if process.returncode != 0:
                    error_msg = stderr.decode() if stderr else "Failed to pull agent image"
                    logger.error(f"Failed to pull agent image: {error_msg}")
                    results["success"] = False
                    results["error"] = f"Agent image pull failed: {error_msg}"
                    return results

                results["agent_image"] = notification.agent_image  # type: ignore[assignment]
                logger.info(f"Successfully pulled agent image: {notification.agent_image}")

            # Pull GUI image if specified
            if notification.gui_image:
                # Normalize image name to lowercase for Docker
                gui_image = notification.gui_image.lower()
                logger.info(f"Pulling GUI image: {gui_image}")
                process = await asyncio.create_subprocess_exec(
                    "docker",
                    "pull",
                    gui_image,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await process.communicate()

                if process.returncode != 0:
                    error_msg = stderr.decode() if stderr else "Failed to pull GUI image"
                    logger.error(f"Failed to pull GUI image: {error_msg}")
                    results["success"] = False
                    results["error"] = f"GUI image pull failed: {error_msg}"
                    return results

                results["gui_image"] = notification.gui_image  # type: ignore[assignment]
                logger.info(f"Successfully pulled GUI image: {notification.gui_image}")

        except Exception as e:
            logger.error(f"Exception during image pull: {e}")
            results["success"] = False
            results["error"] = str(e)

        return results

    async def _get_local_image_digest(self, image_tag: str) -> Optional[str]:
        """
        Get the digest of a locally pulled Docker image.

        Args:
            image_tag: Docker image tag (e.g., ghcr.io/cirisai/ciris-agent:latest)

        Returns:
            Image digest or None if not found
        """
        import json

        try:
            # Use docker inspect to get image details
            result = await asyncio.create_subprocess_exec(
                "docker",
                "inspect",
                image_tag,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await result.communicate()

            if result.returncode != 0:
                logger.warning(f"Failed to inspect image {image_tag}: {stderr.decode()}")
                return None

            # Parse JSON output
            image_data = json.loads(stdout.decode())
            if image_data and len(image_data) > 0:
                # Get the RepoDigests field which contains the image digest
                repo_digests = image_data[0].get("RepoDigests", [])
                if repo_digests:
                    # Extract digest from format like "ghcr.io/cirisai/ciris-agent@sha256:abc123..."
                    for digest in repo_digests:
                        if "@sha256:" in digest:
                            return str(digest.split("@")[-1])  # Return just the sha256:... part

                # Fallback to Id if no RepoDigests
                image_id = image_data[0].get("Id", "")
                if image_id:
                    return str(image_id)

            return None

        except Exception as e:
            logger.error(f"Error getting local image digest for {image_tag}: {e}")
            return None

    async def _get_container_image_digest(self, container_name: str) -> Optional[str]:
        """
        Get the digest of the image used by a running container.

        Args:
            container_name: Name of the container

        Returns:
            Image digest or None if not found
        """
        import json

        try:
            # Get container details
            result = await asyncio.create_subprocess_exec(
                "docker",
                "inspect",
                container_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await result.communicate()

            if result.returncode != 0:
                logger.warning(f"Failed to inspect container {container_name}: {stderr.decode()}")
                return None

            # Parse JSON output
            container_data = json.loads(stdout.decode())
            if container_data and len(container_data) > 0:
                # Get the image ID the container is using
                image_id = container_data[0].get("Image", "")
                if image_id:
                    # If it's already a digest, return it
                    if image_id.startswith("sha256:"):
                        return str(image_id)

                    # Otherwise get the full image details
                    image_name = container_data[0].get("Config", {}).get("Image", "")
                    if image_name:
                        # Get digest of the image the container is using
                        digest = await self._get_local_image_digest(image_name)
                        return digest if digest else None

            return None

        except Exception as e:
            logger.error(f"Error getting container image digest for {container_name}: {e}")
            return None

    def _get_agent_canary_group(self, agent_id: str) -> str:
        """
        Get the canary group for an agent.

        Args:
            agent_id: ID of the agent
        Returns:
            Canary group name: 'explorer', 'early_adopter', or 'general'
        """
        if not self.manager or not self.manager.agent_registry:
            return "general"

        # Get from agent registry metadata
        try:
            agent_metadata = self.manager.agent_registry.get_agent_metadata(agent_id)
            if agent_metadata:
                canary_group = agent_metadata.get("metadata", {}).get("canary_group", "general")
                return str(canary_group) if canary_group else "general"
        except Exception:
            pass

        return "general"  # Default to general if not specified

    async def get_shutdown_reasons_preview(self, deployment_id: str) -> Dict[str, Any]:
        """
        Get a preview of shutdown reasons that will be sent to each agent.

        Args:
            deployment_id: Deployment ID

        Returns:
            Dict with shutdown reasons for each agent group
        """
        if deployment_id not in self.pending_deployments:
            return {"error": "Deployment not found"}

        deployment = self.pending_deployments[deployment_id]
        notification = deployment.notification

        if not notification:
            return {"error": "No notification in deployment"}

        # Build base reason
        if notification.version and not notification.version.startswith(("v", "1", "2", "3")):
            base_reason = f"Runtime: CD update to commit {notification.version[:7]}"
        elif notification.version:
            base_reason = f"Runtime: CD update to version {notification.version}"
        else:
            base_reason = "Runtime: CD update requested"

        reasons = {
            "explorers": f"{base_reason} (deployment {deployment_id[:8]})",
            "early_adopters": f"{base_reason} (deployment {deployment_id[:8]})",
            "general": f"{base_reason} (deployment {deployment_id[:8]})",
        }

        # Early adopters will see explorer results (if explorers exist)
        if self.manager and hasattr(self.manager, "agent_registry"):
            groups = self.manager.agent_registry.get_agents_by_canary_group()

            if groups.get("explorer"):
                # Simulate successful explorer
                reasons["early_adopters"] = (
                    f"{base_reason} | Prior groups: Explorers: 1/1 succeeded "
                    f"(avg 2.5min to WORK) (deployment {deployment_id[:8]})"
                )

                # General will see both
                reasons["general"] = (
                    f"{base_reason} | Prior groups: Explorers: 1/1 succeeded (avg 2.5min to WORK) | "
                    f"Early adopters: 1/1 succeeded (avg 2.0min to WORK) (deployment {deployment_id[:8]})"
                )
            elif groups.get("early_adopter"):
                # No explorers, so early adopters get no peer info
                # General only sees early adopters
                reasons["general"] = (
                    f"{base_reason} | Prior groups: Early adopters: 1/1 succeeded "
                    f"(avg 2.0min to WORK) (deployment {deployment_id[:8]})"
                )

        return {
            "deployment_id": deployment_id,
            "version": notification.version,
            "shutdown_reasons": reasons,
            "note": "These are example reasons. Actual times and success counts will vary based on deployment results.",
        }

    async def get_deployment_preview(self, deployment_id: str) -> Dict[str, Any]:
        """
        Get a preview of what a deployment will do without launching it.
        Shows which agents need updates and which are already current.

        Args:
            deployment_id: ID of the pending deployment
        Returns:
            Preview data with per-agent update status
        """
        if deployment_id not in self.pending_deployments:
            return {"error": "Deployment not found"}

        deployment = self.pending_deployments[deployment_id]
        if not deployment.notification:
            return {"error": "No update notification for deployment"}

        # Get all agents
        from ciris_manager.docker_discovery import DockerAgentDiscovery

        if not self.manager or not self.manager.agent_registry:
            return {"error": "Manager not available"}

        discovery = DockerAgentDiscovery(self.manager.agent_registry)
        all_agents = discovery.discover_agents()

        # Check which agents need updates
        agents_needing_update, nginx_needs_update = await self._check_agents_need_update(
            deployment.notification, all_agents
        )

        # Build preview data
        preview: Dict[str, Any] = {
            "deployment_id": deployment_id,
            "version": deployment.notification.version or "unknown",
            "total_agents": len(all_agents),
            "agents_to_update": len(agents_needing_update),
            "nginx_needs_update": nginx_needs_update,
            "agent_details": [],
        }

        # Get current and target digests for each agent
        target_agent_digest = None
        if deployment.notification.agent_image:
            target_agent_digest = await self._get_local_image_digest(
                deployment.notification.agent_image
            )

        # Add details for each agent
        for agent in all_agents:
            current_digest = await self._get_container_image_digest(f"ciris-{agent.agent_id}")

            needs_update = agent in agents_needing_update
            agent_detail = {
                "agent_id": agent.agent_id,
                "agent_name": agent.agent_name,
                "needs_update": needs_update,
                "current_digest": current_digest[:12] if current_digest else "unknown",
                "target_digest": target_agent_digest[:12]
                if target_agent_digest and needs_update
                else None,
                "status": "Up to date" if not needs_update else "Needs update",
                "canary_group": self._get_agent_canary_group(agent.agent_id),
            }

            # Try to get current version from agent
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    from ciris_manager.agent_auth import get_agent_auth

                    auth = get_agent_auth()
                    headers = auth.get_auth_headers(agent.agent_id)

                    health_url = f"http://localhost:{agent.api_port}/v1/system/health"
                    response = await client.get(health_url, headers=headers)

                    if response.status_code == 200:
                        health_data = response.json()
                        if isinstance(health_data, dict) and health_data.get("data"):
                            health_data = health_data["data"]
                        agent_detail["current_version"] = health_data.get("version", "unknown")
            except Exception:
                agent_detail["current_version"] = "unknown"

            preview["agent_details"].append(agent_detail)

        # Sort agents by update status and canary group (in deployment order)
        canary_order = {"explorer": 0, "early_adopter": 1, "general": 2}
        preview["agent_details"].sort(
            key=lambda x: (
                not x["needs_update"],
                canary_order.get(x.get("canary_group", "general"), 2),
                x["agent_id"],
            )
        )

        return preview

    async def _check_agents_need_update(
        self,
        notification: UpdateNotification,
        agents: List[AgentInfo],
    ) -> tuple[List[AgentInfo], bool]:
        """
        Check which agents actually need updating based on versions.

        Args:
            notification: Update notification with new images
            agents: List of all agents

        Returns:
            Tuple of (List of agents that need updating, bool for nginx needs update)
        """
        # For GUI/nginx, still use digests since they don't have versions
        new_gui_digest = None
        nginx_needs_update = False

        if notification.gui_image:
            # Normalize image name to lowercase for Docker compatibility
            gui_image = notification.gui_image.lower()
            new_gui_digest = await self._get_local_image_digest(gui_image)
            logger.info(f"New GUI image digest: {new_gui_digest}")

            # Check if GUI container needs updating by comparing digests
            # Try to get current GUI container digest
            current_gui_digest = await self._get_container_image_digest("ciris-gui")
            if new_gui_digest and new_gui_digest != current_gui_digest:
                nginx_needs_update = True
                logger.info(f"GUI/nginx needs update: {current_gui_digest} -> {new_gui_digest}")
            else:
                logger.info("GUI/nginx image unchanged")

        # Check each agent to see if it needs updating based on version
        agents_needing_update: List[AgentInfo] = []

        # Only check agents if an agent_image was provided
        if not notification.agent_image:
            logger.info("No agent_image in notification, skipping agent checks")
            return agents_needing_update, nginx_needs_update

        target_version = notification.version

        if not target_version:
            logger.warning(
                "No target version specified in notification, falling back to digest comparison"
            )
            # Fall back to digest comparison if no version specified
            new_agent_digest = None
            if notification.agent_image:
                new_agent_digest = await self._get_local_image_digest(notification.agent_image)
                logger.info(f"New agent image digest: {new_agent_digest}")

        for agent in agents:
            needs_update = False

            if target_version:
                # Version-based comparison
                try:
                    # Get current version from agent's health endpoint
                    auth = get_agent_auth()
                    try:
                        headers = auth.get_auth_headers(agent.agent_id)
                    except Exception:
                        # If auth fails, use empty headers for testing
                        headers = {}

                    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                        health_url = f"http://localhost:{agent.api_port}/v1/system/health"
                        response = await client.get(health_url, headers=headers)

                        if response.status_code == 200:
                            health_data = response.json()
                            current_version = health_data.get("data", {}).get("version", "unknown")

                            # Compare versions
                            if current_version != target_version:
                                logger.info(
                                    f"Agent {agent.agent_name} needs update: "
                                    f"version {current_version} -> {target_version}"
                                )
                                needs_update = True
                            else:
                                logger.info(
                                    f"Agent {agent.agent_name} is up to date at version {current_version}"
                                )
                        else:
                            logger.warning(
                                f"Could not get version for agent {agent.agent_name}, "
                                f"assuming update needed"
                            )
                            needs_update = True

                except Exception as e:
                    logger.warning(
                        f"Error checking version for agent {agent.agent_name}: {e}, "
                        f"assuming update needed"
                    )
                    needs_update = True
            else:
                # Digest-based comparison (fallback)
                current_agent_digest = None
                if agent.container_name:
                    current_agent_digest = await self._get_container_image_digest(
                        agent.container_name
                    )
                    logger.info(f"Agent {agent.agent_name} current digest: {current_agent_digest}")

                # Check if agent image changed
                agent_changed = bool(new_agent_digest and new_agent_digest != current_agent_digest)
                needs_update = agent_changed

                if needs_update:
                    logger.info(
                        f"Agent {agent.agent_name} needs update: "
                        f"digest changed from {current_agent_digest} to {new_agent_digest}"
                    )

            if needs_update:
                agents_needing_update.append(agent)

        return agents_needing_update, nginx_needs_update

    async def get_deployment_status(self, deployment_id: str) -> Optional[DeploymentStatus]:
        """Get status of a deployment."""
        return self.deployments.get(deployment_id)

    async def get_current_deployment(self) -> Optional[DeploymentStatus]:
        """Get current active deployment."""
        if self.current_deployment:
            return self.deployments.get(self.current_deployment)
        return None

    async def _run_deployment(
        self,
        deployment_id: str,
        notification: UpdateNotification,
        agents: List[AgentInfo],
    ) -> None:
        """
        Run the deployment process.

        Args:
            deployment_id: Deployment identifier
            notification: Update notification
            agents: List of agents to update
        """
        from ciris_manager.audit import audit_deployment_action

        logger.info(
            f"Starting deployment {deployment_id} with strategy '{notification.strategy}' "
            f"for {len(agents)} agents. Version: {notification.version}"
        )
        audit_deployment_action(
            deployment_id=deployment_id,
            action="deployment_started",
            details={
                "strategy": notification.strategy,
                "agent_count": len(agents),
                "version": notification.version,
                "message": notification.message,
            },
        )

        try:
            status = self.deployments[deployment_id]

            if notification.strategy == "canary":
                await self._run_canary_deployment(deployment_id, notification, agents)
            elif notification.strategy == "immediate":
                await self._run_immediate_deployment(deployment_id, notification, agents)
            else:
                status.message = f"Unknown deployment strategy: {notification.strategy}"
                status.status = "failed"
                self._save_state()

        except Exception as e:
            logger.error(f"Deployment {deployment_id} failed: {e}", exc_info=True)
            audit_deployment_action(
                deployment_id=deployment_id,
                action="deployment_failed",
                success=False,
                details={"error": str(e), "error_type": type(e).__name__},
            )
            deployment_status = self.deployments.get(deployment_id)
            if deployment_status:
                deployment_status.status = "failed"
                deployment_status.message = str(e)
                self._save_state()
        finally:
            async with self._deployment_lock:
                if self.current_deployment == deployment_id:
                    self.current_deployment = None

            # Mark deployment as completed
            deployment_status = self.deployments.get(deployment_id)
            if deployment_status and deployment_status.status == "in_progress":
                deployment_status.status = "completed"
                deployment_status.completed_at = datetime.now(timezone.utc).isoformat()
                self._save_state()

                # Promote staged versions to current (n+1 → n, n → n-1, n-1 → n-2)
                tracker = get_version_tracker()

                if deployment_status.notification is not None:
                    notification = deployment_status.notification
                    # Promote agent version
                    if notification.agent_image:
                        await tracker.promote_staged_version("agent", deployment_id)

                    # Promote GUI version
                    if notification.gui_image:
                        await tracker.promote_staged_version("gui", deployment_id)

                    # Promote nginx version if we have one
                    if hasattr(notification, "nginx_image") and notification.nginx_image:
                        await tracker.promote_staged_version("nginx", deployment_id)

                logger.info(f"Promoted staged versions to current for deployment {deployment_id}")

                # Log deployment completion with summary
                logger.info(
                    f"Deployment {deployment_id} completed. "
                    f"Updated: {deployment_status.agents_updated}, "
                    f"Deferred: {deployment_status.agents_deferred}, "
                    f"Failed: {deployment_status.agents_failed}"
                )
                audit_deployment_action(
                    deployment_id=deployment_id,
                    action="deployment_completed",
                    success=True,
                    details={
                        "agents_updated": deployment_status.agents_updated,
                        "agents_deferred": deployment_status.agents_deferred,
                        "agents_failed": deployment_status.agents_failed,
                        "duration_seconds": (
                            datetime.now(timezone.utc)
                            - datetime.fromisoformat(
                                deployment_status.started_at.replace("Z", "+00:00")
                                if deployment_status.started_at
                                else datetime.now(timezone.utc).isoformat()
                            )
                        ).total_seconds()
                        if deployment_status.started_at
                        else 0,
                    },
                )

    async def _check_canary_group_health(
        self,
        deployment_id: str,
        agents: List[AgentInfo],
        phase_name: str,
        wait_for_work_minutes: int = 5,
        stability_minutes: int = 1,
    ) -> tuple[bool, Dict[str, Any]]:
        """
        Check if at least one agent in the canary group has reached WORK state
        and has no incidents for the stability period.

        Args:
            deployment_id: Deployment identifier
            agents: List of agents in the canary group
            phase_name: Name of the current phase (for logging)
            wait_for_work_minutes: Max time to wait for WORK state
            stability_minutes: Time agent must be stable in WORK state

        Returns:
            Tuple of (success, results_dict) where results_dict contains timing info
        """
        logger.info(
            f"Deployment {deployment_id}: Waiting for {phase_name} agents to reach WORK state"
        )

        start_time = datetime.now(timezone.utc)
        wait_until = start_time.timestamp() + (wait_for_work_minutes * 60)

        # Track which agents have reached WORK and when
        agents_in_work: Dict[str, datetime] = {}

        while datetime.now(timezone.utc).timestamp() < wait_until:
            # Check each agent's state
            for agent in agents:
                if not agent.is_running:
                    continue

                try:
                    # Get agent health status
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        # Get auth headers for this agent
                        from ciris_manager.agent_auth import get_agent_auth

                        auth = get_agent_auth()
                        headers = auth.get_auth_headers(agent.agent_id)

                        # Check health endpoint (using system/health which is the correct endpoint)
                        health_url = f"http://localhost:{agent.api_port}/v1/system/health"
                        response = await client.get(health_url, headers=headers)

                        if response.status_code == 200:
                            health_data = response.json()
                            if isinstance(health_data, dict) and health_data.get("data"):
                                health_data = health_data["data"]

                            cognitive_state = health_data.get("cognitive_state", "").lower()
                            version = health_data.get("version", "unknown")

                            # Check if agent is in WORK state
                            if cognitive_state == "work":
                                if agent.agent_id not in agents_in_work:
                                    agents_in_work[agent.agent_id] = datetime.now(timezone.utc)
                                    logger.info(
                                        f"Agent {agent.agent_id} reached WORK state with version {version}"
                                    )

                                # Check if agent has been stable for required period
                                work_duration = (
                                    datetime.now(timezone.utc) - agents_in_work[agent.agent_id]
                                ).total_seconds() / 60

                                if work_duration >= stability_minutes:
                                    # Agent has been in WORK state for required duration
                                    # Try to check telemetry for incidents, but don't block on it
                                    recent_critical = False
                                    telemetry_checked = False

                                    try:
                                        telemetry_url = f"http://localhost:{agent.api_port}/v1/telemetry/overview"
                                        telemetry_response = await client.get(
                                            telemetry_url, headers=headers, timeout=5.0
                                        )

                                        if telemetry_response.status_code == 200:
                                            telemetry_data = telemetry_response.json()
                                            if isinstance(
                                                telemetry_data, dict
                                            ) and telemetry_data.get("data"):
                                                telemetry_data = telemetry_data["data"]

                                            incidents = telemetry_data.get("recent_incidents", [])

                                            # Handle case where incidents might be an int (count) instead of list
                                            if isinstance(incidents, int):
                                                incidents = []  # No incidents if it's just a count
                                            elif not isinstance(incidents, list):
                                                logger.warning(
                                                    f"Unexpected incidents type for {agent.agent_id}: {type(incidents)}"
                                                )
                                                incidents = []

                                            # Check for critical incidents in the last stability_minutes
                                            cutoff_time = datetime.now(timezone.utc).timestamp() - (
                                                stability_minutes * 60
                                            )

                                            for incident in incidents:
                                                if incident.get("severity") in ["critical", "high"]:
                                                    incident_time = incident.get("timestamp", 0)
                                                    if isinstance(incident_time, str):
                                                        # Parse ISO timestamp
                                                        from dateutil import parser

                                                        incident_time = parser.parse(
                                                            incident_time
                                                        ).timestamp()
                                                    if incident_time > cutoff_time:
                                                        recent_critical = True
                                                        break

                                            telemetry_checked = True
                                        else:
                                            logger.warning(
                                                f"Telemetry endpoint returned {telemetry_response.status_code} "
                                                f"for agent {agent.agent_id}, proceeding without incident check"
                                            )
                                    except Exception as e:
                                        # Telemetry check failed, but agent is in WORK state
                                        logger.warning(
                                            f"Could not check telemetry for agent {agent.agent_id}: {e}. "
                                            f"Proceeding based on WORK state alone."
                                        )

                                    # If there were critical incidents, skip this agent
                                    if recent_critical:
                                        logger.warning(
                                            f"Agent {agent.agent_id} has recent critical incidents, "
                                            f"continuing to monitor"
                                        )
                                        continue

                                    # Agent is stable in WORK state (with or without telemetry confirmation)
                                    if telemetry_checked:
                                        logger.info(
                                            f"Agent {agent.agent_id} is stable in WORK state "
                                            f"for {work_duration:.1f} minutes with no critical incidents"
                                        )
                                    else:
                                        logger.info(
                                            f"Agent {agent.agent_id} is stable in WORK state "
                                            f"for {work_duration:.1f} minutes (telemetry unavailable)"
                                        )

                                    # Add event for agent reaching stable WORK
                                    self._add_event(
                                        deployment_id,
                                        "agent_stable",
                                        f"{agent.agent_name} reached stable WORK state",
                                        {
                                            "agent_id": agent.agent_id,
                                            "phase": phase_name,
                                            "time_to_work": round(work_duration, 1),
                                            "version": version,
                                            "telemetry_checked": telemetry_checked,
                                        },
                                    )

                                    # Calculate time to reach WORK
                                    time_to_work = (
                                        agents_in_work[agent.agent_id] - start_time
                                    ).total_seconds() / 60

                                    results = {
                                        "successful_agent": agent.agent_id,
                                        "time_to_work_minutes": round(time_to_work, 1),
                                        "stability_duration_minutes": round(work_duration, 1),
                                        "version": version,
                                        "telemetry_available": telemetry_checked,
                                    }
                                    return True, results
                            else:
                                # Agent not in WORK state, remove from tracking
                                if agent.agent_id in agents_in_work:
                                    del agents_in_work[agent.agent_id]
                                    logger.warning(
                                        f"Agent {agent.agent_id} left WORK state, now in {cognitive_state}"
                                    )

                except httpx.ConnectError as e:
                    # Connection errors are expected when container is starting
                    logger.debug(f"Agent {agent.agent_id} not ready yet: {e}")
                except Exception as e:
                    # Log other errors but don't fail the deployment
                    logger.warning(
                        f"Error checking agent {sanitize_agent_id(agent.agent_id)} health: {e}"
                    )

            # Wait before next check
            await asyncio.sleep(10)

        # Timeout reached - propose rollback to operator
        logger.warning(
            f"Deployment {sanitize_for_log(deployment_id)}: No {sanitize_for_log(phase_name)} agents reached stable WORK state "
            f"within {wait_for_work_minutes} minutes"
        )

        # Stage a rollback proposal for human review
        await self._propose_rollback(
            deployment_id,
            reason=f"No {phase_name} agents reached WORK state within {wait_for_work_minutes} minutes",
            affected_agents=agents,
        )

        return False, {"failed": True, "reason": "timeout"}

    async def _run_canary_deployment(
        self,
        deployment_id: str,
        notification: UpdateNotification,
        agents: List[AgentInfo],
    ) -> None:
        """
        Run canary deployment using pre-assigned groups (explorers → early adopters → general).

        Only agents that have been manually assigned to canary groups will receive
        update notifications. Unassigned agents are skipped.

        Args:
            deployment_id: Deployment identifier
            notification: Update notification
            agents: List of agents
        """
        status = self.deployments[deployment_id]

        # Track peer results from previous phases
        peer_results: Dict[str, Dict[str, Any]] = {
            "explorers": {"total": 0, "successful": 0, "failed": 0, "time_to_work": []},
            "early_adopters": {"total": 0, "successful": 0, "failed": 0, "time_to_work": []},
        }

        # Get agents organized by their pre-assigned canary groups
        explorers = []
        early_adopters = []
        general = []

        if self.manager and hasattr(self.manager, "agent_registry"):
            # Use pre-assigned groups from registry
            groups = self.manager.agent_registry.get_agents_by_canary_group()

            # Only include running agents from each group
            for agent in agents:
                if agent.is_running:
                    # Find which group this agent belongs to
                    for group_agent in groups.get("explorer", []):
                        if group_agent.agent_id == agent.agent_id:
                            explorers.append(agent)
                            break
                    for group_agent in groups.get("early_adopter", []):
                        if group_agent.agent_id == agent.agent_id:
                            early_adopters.append(agent)
                            break
                    for group_agent in groups.get("general", []):
                        if group_agent.agent_id == agent.agent_id:
                            general.append(agent)
                            break
        else:
            # Fallback if no registry available - skip unassigned agents
            logger.warning(
                "No agent registry available for canary groups, skipping canary deployment"
            )
            status.message = "Canary deployment requires agent registry with group assignments"
            status.status = "failed"
            self._save_state()
            return

        # Check if we have any agents in canary groups
        if not explorers and not early_adopters and not general:
            status.message = "No agents assigned to canary groups"
            logger.warning(
                "No agents assigned to canary groups, cannot proceed with canary deployment"
            )
            status.status = "failed"
            self._save_state()
            return

        # Phase 1: Explorers (if any)
        from ciris_manager.audit import audit_deployment_action

        if explorers:
            status.canary_phase = "explorers"
            status.message = f"Notifying {len(explorers)} explorer agents"
            self._save_state()
            logger.info(
                f"Deployment {deployment_id}: Starting explorer phase with {len(explorers)} pre-assigned explorer agents"
            )
            audit_deployment_action(
                deployment_id=deployment_id,
                action="canary_phase_started",
                details={"phase": "explorers", "agent_count": len(explorers)},
            )
            # First group - no peer results to share
            await self._update_agent_group(deployment_id, notification, explorers, None)

            # Wait for at least one explorer to reach WORK state and be stable
            success, results = await self._check_canary_group_health(
                deployment_id, explorers, "explorer", wait_for_work_minutes=5, stability_minutes=1
            )

            if success:
                # Update peer results
                peer_results["explorers"]["total"] = len(explorers)
                peer_results["explorers"]["successful"] = 1
                peer_results["explorers"]["time_to_work"].append(
                    results.get("time_to_work_minutes", 0)
                )

            if not success:
                status.message = "Explorer phase failed - no agents reached stable WORK state"
                status.status = "failed"
                # Clear the deployment lock on failure
                self.current_deployment = None
                self._save_state()
                logger.error(
                    f"Deployment {deployment_id}: Explorer phase failed, aborting deployment"
                )
                audit_deployment_action(
                    deployment_id=deployment_id,
                    action="canary_phase_failed",
                    details={"phase": "explorers", "reason": "no_stable_work_state"},
                )
                return

            logger.info(
                f"Deployment {deployment_id}: Explorer phase successful, proceeding to early adopters"
            )
            self._add_event(
                deployment_id,
                "phase_complete",
                "Explorer phase completed successfully",
                {"phase": "explorers", "results": results if results else {}},
            )
        else:
            logger.info(f"Deployment {deployment_id}: No explorer agents assigned, skipping phase")

        # Phase 2: Early Adopters (if any)
        if early_adopters:
            status.canary_phase = "early_adopters"
            status.message = f"Notifying {len(early_adopters)} early adopter agents"
            self._save_state()
            logger.info(
                f"Deployment {deployment_id}: Starting early adopter phase with {len(early_adopters)} pre-assigned agents"
            )
            audit_deployment_action(
                deployment_id=deployment_id,
                action="canary_phase_started",
                details={"phase": "early_adopters", "agent_count": len(early_adopters)},
            )
            # Only pass peer results if explorers ran first
            peer_results_to_pass = peer_results if explorers else None
            await self._update_agent_group(
                deployment_id, notification, early_adopters, peer_results_to_pass
            )

            # Wait for at least one early adopter to reach WORK state and be stable
            success, results = await self._check_canary_group_health(
                deployment_id,
                early_adopters,
                "early adopter",
                wait_for_work_minutes=5,
                stability_minutes=1,
            )

            if success:
                # Update peer results
                peer_results["early_adopters"]["total"] = len(early_adopters)
                peer_results["early_adopters"]["successful"] = 1
                peer_results["early_adopters"]["time_to_work"].append(
                    results.get("time_to_work_minutes", 0)
                )

            if not success:
                status.message = "Early adopter phase failed - no agents reached stable WORK state"
                status.status = "failed"
                # Clear the deployment lock on failure
                self.current_deployment = None
                self._save_state()
                logger.error(
                    f"Deployment {deployment_id}: Early adopter phase failed, aborting deployment"
                )
                audit_deployment_action(
                    deployment_id=deployment_id,
                    action="canary_phase_failed",
                    details={"phase": "early_adopters", "reason": "no_stable_work_state"},
                )
                return

            logger.info(
                f"Deployment {deployment_id}: Early adopter phase successful, proceeding to general"
            )
            self._add_event(
                deployment_id,
                "phase_complete",
                "Early adopter phase completed successfully",
                {
                    "phase": "early_adopters",
                    "results": results if results else {},
                },
            )
        else:
            logger.info(
                f"Deployment {deployment_id}: No early adopter agents assigned, skipping phase"
            )

        # Phase 3: General Population (if any)
        if general:
            status.canary_phase = "general"
            status.message = f"Notifying {len(general)} general agents"
            self._save_state()
            logger.info(
                f"Deployment {deployment_id}: Starting general phase with {len(general)} pre-assigned agents"
            )
            audit_deployment_action(
                deployment_id=deployment_id,
                action="canary_phase_started",
                details={"phase": "general", "agent_count": len(general)},
            )
            await self._update_agent_group(deployment_id, notification, general, peer_results)

            # For general population, just log if they don't reach WORK state (don't fail deployment)
            success, results = await self._check_canary_group_health(
                deployment_id, general, "general", wait_for_work_minutes=5, stability_minutes=1
            )
            if success:
                logger.info(
                    f"Deployment {deployment_id}: General phase agents reached stable WORK state"
                )
            else:
                logger.warning(
                    f"Deployment {sanitize_for_log(deployment_id)}: Some general phase agents did not reach stable WORK state"
                )
        else:
            logger.info(f"Deployment {deployment_id}: No general agents assigned, skipping phase")

    async def _run_immediate_deployment(
        self,
        deployment_id: str,
        notification: UpdateNotification,
        agents: List[AgentInfo],
    ) -> None:
        """
        Run immediate deployment (all agents at once).

        Args:
            deployment_id: Deployment identifier
            notification: Update notification
            agents: List of agents
        """
        status = self.deployments[deployment_id]
        running_agents = [a for a in agents if a.is_running]

        status.message = f"Updating {len(running_agents)} agents immediately"
        self._save_state()
        await self._update_agent_group(deployment_id, notification, running_agents)

        # Mark deployment as completed
        status.status = "completed"
        status.completed_at = datetime.now(timezone.utc).isoformat()
        self._save_state()

        # Promote staged versions to current after immediate deployment
        tracker = get_version_tracker()
        if notification.agent_image:
            await tracker.promote_staged_version("agent", deployment_id)
        if notification.gui_image:
            await tracker.promote_staged_version("gui", deployment_id)
        if hasattr(notification, "nginx_image") and notification.nginx_image:
            await tracker.promote_staged_version("nginx", deployment_id)

        logger.info(f"Immediate deployment {deployment_id} completed, versions promoted")

    async def _update_agent_group(
        self,
        deployment_id: str,
        notification: UpdateNotification,
        agents: List[AgentInfo],
        peer_results: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Update a group of agents.

        Args:
            deployment_id: Deployment identifier
            notification: Update notification
            agents: Agents to update
        """
        status = self.deployments[deployment_id]
        tasks = []

        for agent in agents:
            task = asyncio.create_task(
                self._update_single_agent(deployment_id, notification, agent, peer_results)
            )
            tasks.append(task)
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

        # Run updates in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Count results
        for result in results:
            if isinstance(result, Exception):
                status.agents_failed += 1
            elif isinstance(result, AgentUpdateResponse):
                if result.decision == "accept":
                    status.agents_updated += 1
                elif result.decision == "notified":
                    # Agent was notified of shutdown request but may not actually shutdown
                    # Count as updated for now, but log the uncertainty
                    status.agents_updated += 1
                    logger.info(f"Agent {result.agent_id} was notified (not confirmed)")
                elif result.decision == "defer":
                    status.agents_deferred += 1
                else:
                    status.agents_failed += 1

        # Save state after updating counts
        self._save_state()

    async def _update_single_agent(
        self,
        deployment_id: str,
        notification: UpdateNotification,
        agent: AgentInfo,
        peer_results: Optional[Dict[str, Any]] = None,
    ) -> AgentUpdateResponse:
        """
        Update a single agent.

        Args:
            deployment_id: Deployment identifier
            notification: Update notification
            agent: Agent to update

        Returns:
            Agent update response
        """
        from ciris_manager.audit import audit_deployment_action, audit_service_token_use

        logger.info(f"Starting update for agent {agent.agent_id} in deployment {deployment_id}")

        try:
            # peer_results tracking removed - using shutdown endpoint instead of update endpoint

            # Build enhanced notification (for future use when agents support update endpoint)
            # update_payload = {
            #     "new_image": notification.agent_image,
            #     "message": notification.message,
            #     "deployment_id": deployment_id,
            #     "version": notification.version,
            #     "changelog": notification.changelog or notification.message,
            #     "risk_level": notification.risk_level,
            #     "peer_results": peer_results,
            #     "commit_sha": notification.commit_sha,
            # }

            # Call agent's graceful shutdown endpoint
            async with httpx.AsyncClient() as client:
                # Use shutdown endpoint instead of non-existent update endpoint
                # Build a more descriptive shutdown reason
                if notification.version and not notification.version.startswith(
                    ("v", "1", "2", "3")
                ):
                    # Looks like a commit SHA, use a more descriptive format
                    reason = f"Runtime: CD update to commit {notification.version[:7]}"
                elif notification.version:
                    # Semantic version
                    reason = f"Runtime: CD update to version {notification.version}"
                else:
                    # No version provided
                    reason = "Runtime: CD update requested"

                # Add peer results if available (but NOT for the first group)
                if peer_results:
                    # Build peer summary
                    peer_info = []

                    if peer_results.get("explorers", {}).get("total", 0) > 0:
                        exp = peer_results["explorers"]
                        if exp.get("successful", 0) > 0:
                            avg_time = sum(exp.get("time_to_work", [])) / len(
                                exp.get("time_to_work", [1])
                            )
                            peer_info.append(
                                f"Explorers: {exp['successful']}/{exp['total']} succeeded (avg {avg_time:.1f}min to WORK)"
                            )

                    if peer_results.get("early_adopters", {}).get("total", 0) > 0:
                        ea = peer_results["early_adopters"]
                        if ea.get("successful", 0) > 0:
                            avg_time = sum(ea.get("time_to_work", [])) / len(
                                ea.get("time_to_work", [1])
                            )
                            peer_info.append(
                                f"Early adopters: {ea['successful']}/{ea['total']} succeeded (avg {avg_time:.1f}min to WORK)"
                            )

                    if peer_info:
                        reason = f"{reason} | Prior groups: {' | '.join(peer_info)}"

                # Add deployment ID for context
                reason = f"{reason} (deployment {deployment_id[:8]})"

                # Include full changelog if available (all commit messages from release)
                if notification.changelog:
                    # Format changelog for readability
                    changelog_lines = notification.changelog.strip().split("\n")
                    if len(changelog_lines) > 1:
                        # Multi-line changelog - include as bullet points
                        formatted_changelog = "\nRelease notes:\n" + "\n".join(
                            f"  • {line.strip()}" for line in changelog_lines if line.strip()
                        )
                        reason = f"{reason}{formatted_changelog}"
                    else:
                        # Single line changelog
                        reason = f"{reason} - {notification.changelog}"
                elif notification.message and notification.message != "Update available":
                    # Fall back to message if no changelog
                    reason = f"{reason} - {notification.message}"

                # Handle different deployment strategies
                if notification.strategy == "docker":
                    # Manager forced - skip API call and directly restart container
                    logger.info(
                        f"Manager forced restart for agent {agent.agent_id} - bypassing API"
                    )

                    # Recreate the container with the new image
                    logger.info(f"Recreating container {agent.container_name} with new image...")

                    # Use the existing proper recreation method
                    recreated = await self._recreate_agent_container(agent.agent_id)

                    if recreated:
                        # Update metadata with new image
                        if self.manager:
                            await self._update_agent_metadata(agent.agent_id, notification)

                        return AgentUpdateResponse(
                            agent_id=agent.agent_id,
                            decision="accept",
                            reason="Container forcefully recreated with new image via Docker",
                            ready_at=None,
                        )
                    else:
                        logger.error(f"Failed to recreate container for {agent.agent_id}")
                        return AgentUpdateResponse(
                            agent_id=agent.agent_id,
                            decision="reject",
                            reason="Failed to recreate container",
                            ready_at=None,
                        )

                # For API-based strategies (manual or immediate)
                # Add API indicator for clarity
                reason = f"System shutdown requested: {reason} (API shutdown by wa-system-admin)"

                # Respect deployment strategy for force flag
                # "immediate" means force the shutdown via API, "manual" means consensual (agent decides)
                force_shutdown = notification.strategy == "immediate"

                shutdown_payload = {
                    "reason": reason,
                    "force": force_shutdown,
                    "confirm": True,
                }

                # Use centralized agent authentication
                from ciris_manager.agent_auth import get_agent_auth

                auth = get_agent_auth(self.manager.agent_registry if self.manager else None)
                try:
                    headers = auth.get_auth_headers(agent.agent_id)
                except ValueError as e:
                    logger.error(f"Failed to authenticate with agent {agent.agent_id}: {e}")
                    return AgentUpdateResponse(
                        agent_id=agent.agent_id,
                        decision="reject",
                        reason=f"Authentication failed: {str(e)}",
                        ready_at=None,
                    )

                # Audit token use if using service token
                if "service:" in headers.get("Authorization", ""):
                    audit_service_token_use(
                        agent_id=agent.agent_id,
                        action=f"deployment_{deployment_id}",
                        success=True,
                        details={"deployment_id": deployment_id},
                    )

                # Log the shutdown request with strategy
                if force_shutdown:
                    deployment_mode = "API forced (immediate)"
                else:
                    deployment_mode = "consensual (agent decides)"
                logger.info(
                    f"Requesting {deployment_mode} shutdown for agent {agent.agent_id} at http://localhost:{agent.api_port}/v1/system/shutdown"
                )
                audit_deployment_action(
                    deployment_id=deployment_id,
                    action="shutdown_requested",
                    details={"agent_id": agent.agent_id, "reason": shutdown_payload["reason"]},
                )

                response = await client.post(
                    f"http://localhost:{agent.api_port}/v1/system/shutdown",
                    json=shutdown_payload,
                    headers=headers,
                    timeout=30.0,
                )

                if response.status_code == 200:
                    # HTTP 200 means shutdown was requested, not necessarily accepted
                    # The agent may or may not actually shutdown based on its own logic
                    logger.info(f"Agent {agent.agent_id} notified of shutdown request (HTTP 200)")
                    audit_deployment_action(
                        deployment_id=deployment_id,
                        action="shutdown_notified",
                        success=True,
                        details={
                            "agent_id": agent.agent_id,
                            "note": "Agent notified but may not shutdown immediately",
                        },
                    )

                    # Update agent metadata with new image digests
                    if self.manager:
                        await self._update_agent_metadata(agent.agent_id, notification)
                        logger.debug(f"Updated metadata for agent {agent.agent_id}")

                    # Track that this agent is pending restart
                    deployment = self.deployments[deployment_id]
                    if agent.agent_id not in deployment.agents_pending_restart:
                        deployment.agents_pending_restart.append(agent.agent_id)
                    deployment.agents_in_progress[agent.agent_id] = "waiting_for_shutdown"
                    self._save_state()

                    # Wait for container to stop and recreate it with new image
                    logger.info(f"Waiting for container {agent.container_name} to stop...")
                    stopped = await self._wait_for_container_stop(agent.container_name, timeout=60)

                    if stopped:
                        # Update state to show we're restarting
                        deployment.agents_in_progress[agent.agent_id] = "restarting"
                        self._save_state()
                        
                        logger.info(
                            f"Container {agent.container_name} stopped, recreating with new image..."
                        )
                        recreated = await self._recreate_agent_container(agent.agent_id)

                        if recreated:
                            # Remove from pending and in-progress
                            if agent.agent_id in deployment.agents_pending_restart:
                                deployment.agents_pending_restart.remove(agent.agent_id)
                            if agent.agent_id in deployment.agents_in_progress:
                                del deployment.agents_in_progress[agent.agent_id]
                            self._save_state()
                            
                            logger.info(
                                f"Successfully recreated container for agent {agent.agent_id}"
                            )
                            return AgentUpdateResponse(
                                agent_id=agent.agent_id,
                                decision="accept",
                                reason="Container recreated with new image",
                                ready_at=None,
                            )
                        else:
                            # Mark as failed
                            if agent.agent_id in deployment.agents_pending_restart:
                                deployment.agents_pending_restart.remove(agent.agent_id)
                            if agent.agent_id in deployment.agents_in_progress:
                                del deployment.agents_in_progress[agent.agent_id]
                            self._save_state()
                            
                            logger.error(f"Failed to recreate container for agent {agent.agent_id}")
                            return AgentUpdateResponse(
                                agent_id=agent.agent_id,
                                decision="reject",
                                reason="Failed to recreate container",
                                ready_at=None,
                            )
                    else:
                        # Remove from tracking since it didn't stop
                        if agent.agent_id in deployment.agents_pending_restart:
                            deployment.agents_pending_restart.remove(agent.agent_id)
                        if agent.agent_id in deployment.agents_in_progress:
                            del deployment.agents_in_progress[agent.agent_id]
                        self._save_state()
                        
                        logger.warning(f"Container {agent.container_name} did not stop in time")
                        return AgentUpdateResponse(
                            agent_id=agent.agent_id,
                            decision="notified",
                            reason="Container did not stop in expected time",
                            ready_at=None,
                        )
                else:
                    # Log non-200 response with details
                    logger.error(
                        f"Agent {agent.agent_id} rejected update with HTTP {response.status_code}. "
                        f"Response body: {response.text[:500]}"
                    )
                    audit_deployment_action(
                        deployment_id=deployment_id,
                        action="update_rejected",
                        success=False,
                        details={
                            "agent_id": agent.agent_id,
                            "http_status": response.status_code,
                            "response_body": response.text[:500],
                        },
                    )
                    return AgentUpdateResponse(
                        agent_id=agent.agent_id,
                        decision="reject",
                        reason=f"HTTP {response.status_code}",
                        ready_at=None,
                    )

        except httpx.ConnectError as e:
            # Agent not reachable, might already be shutting down
            logger.warning(
                f"Agent {agent.agent_id} not reachable: {e}. Assuming it may be shutting down."
            )
            audit_deployment_action(
                deployment_id=deployment_id,
                action="connection_error",
                success=True,  # We treat this as success since agent may be shutting down
                details={
                    "agent_id": agent.agent_id,
                    "error": str(e),
                    "note": "Agent unreachable, shutdown status unknown",
                },
            )
            return AgentUpdateResponse(
                agent_id=agent.agent_id,
                decision="notified",  # Changed to "notified" since we can't confirm
                reason="Agent not reachable (possibly already shutting down)",
                ready_at=None,
            )
        except Exception as e:
            logger.error(f"Failed to update agent {agent.agent_id}: {e}", exc_info=True)
            audit_deployment_action(
                deployment_id=deployment_id,
                action="update_error",
                success=False,
                details={
                    "agent_id": agent.agent_id,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )
            return AgentUpdateResponse(
                agent_id=agent.agent_id,
                decision="reject",
                reason=str(e),
                ready_at=None,
            )

    async def _wait_for_container_stop(self, container_name: str, timeout: int = 60) -> bool:
        """
        Wait for a container to stop.

        Args:
            container_name: Name of the container to monitor
            timeout: Maximum time to wait in seconds

        Returns:
            True if container stopped, False if timeout reached
        """
        import time

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                # Check container status
                result = await asyncio.create_subprocess_exec(
                    "docker",
                    "inspect",
                    container_name,
                    "--format",
                    "{{.State.Status}}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await result.communicate()

                if result.returncode != 0:
                    # Container doesn't exist or error
                    logger.debug(f"Container {container_name} not found or error")
                    return True

                status = stdout.decode().strip()
                if status in ["exited", "dead", "removing", "removed"]:
                    logger.info(f"Container {container_name} has stopped (status: {status})")
                    return True

                logger.debug(f"Container {container_name} status: {status}, waiting...")
                await asyncio.sleep(2)

            except Exception as e:
                logger.error(f"Error checking container status: {e}")
                await asyncio.sleep(2)

        logger.warning(f"Timeout waiting for container {container_name} to stop")
        return False

    async def _recreate_agent_container(self, agent_id: str) -> bool:
        """
        Recreate an agent container using docker-compose.

        Args:
            agent_id: ID of the agent to recreate

        Returns:
            True if successful, False otherwise
        """
        try:
            # Find the agent's docker-compose file
            agent_dir = Path("/opt/ciris/agents") / agent_id
            compose_file = agent_dir / "docker-compose.yml"

            if not compose_file.exists():
                logger.error(f"Docker compose file not found: {compose_file}")
                return False

            logger.info(f"Recreating container for agent {agent_id} using docker-compose...")

            # Run docker-compose up -d with --pull always to use the newly pulled image
            result = await asyncio.create_subprocess_exec(
                "docker-compose",
                "-f",
                str(compose_file),
                "up",
                "-d",
                "--pull",
                "always",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(agent_dir),
            )
            stdout, stderr = await result.communicate()

            if result.returncode != 0:
                logger.error(f"Failed to recreate container: {stderr.decode()}")
                return False

            logger.info(f"Successfully ran docker-compose up for agent {agent_id}")

            # Wait a moment for container to start
            await asyncio.sleep(5)

            # Verify container is running
            container_name = f"ciris-{agent_id}"
            check_result = await asyncio.create_subprocess_exec(
                "docker",
                "inspect",
                container_name,
                "--format",
                "{{.State.Status}}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            check_stdout, _ = await check_result.communicate()

            if check_result.returncode == 0:
                status = check_stdout.decode().strip()
                if status == "running":
                    logger.info(f"Container {container_name} is running")
                    return True
                else:
                    logger.warning(f"Container {container_name} status: {status}")

            return False

        except Exception as e:
            logger.error(f"Error recreating container for agent {agent_id}: {e}")
            return False

    async def _recover_interrupted_deployment(self, deployment: DeploymentStatus) -> None:
        """
        Recover an interrupted deployment after manager restart.
        
        Args:
            deployment: The deployment to recover
        """
        logger.info(f"Starting recovery for interrupted deployment {deployment.deployment_id}")
        
        try:
            # Process agents that were pending restart
            for agent_id in list(deployment.agents_pending_restart):
                logger.info(f"Recovering restart for agent {agent_id}")
                
                # Check if container is already stopped
                container_name = f"ciris-{agent_id}"
                status_result = await asyncio.create_subprocess_exec(
                    "docker",
                    "inspect",
                    container_name,
                    "--format",
                    "{{.State.Status}}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await status_result.communicate()
                
                if status_result.returncode != 0:
                    # Container doesn't exist - try to recreate it
                    logger.info(f"Container {container_name} not found, attempting recreation")
                    recreated = await self._recreate_agent_container(agent_id)
                    if recreated:
                        deployment.agents_updated += 1
                        deployment.agents_pending_restart.remove(agent_id)
                        if agent_id in deployment.agents_in_progress:
                            del deployment.agents_in_progress[agent_id]
                        logger.info(f"Successfully recovered agent {agent_id}")
                    else:
                        deployment.agents_failed += 1
                        deployment.agents_pending_restart.remove(agent_id)
                        if agent_id in deployment.agents_in_progress:
                            del deployment.agents_in_progress[agent_id]
                        logger.error(f"Failed to recover agent {agent_id}")
                else:
                    status = stdout.decode().strip()
                    if status in ["exited", "dead", "removing", "removed"]:
                        # Container is stopped, recreate it
                        logger.info(f"Container {container_name} is stopped, recreating")
                        recreated = await self._recreate_agent_container(agent_id)
                        if recreated:
                            deployment.agents_updated += 1
                            deployment.agents_pending_restart.remove(agent_id)
                            if agent_id in deployment.agents_in_progress:
                                del deployment.agents_in_progress[agent_id]
                            logger.info(f"Successfully recovered agent {agent_id}")
                        else:
                            deployment.agents_failed += 1
                            deployment.agents_pending_restart.remove(agent_id)
                            if agent_id in deployment.agents_in_progress:
                                del deployment.agents_in_progress[agent_id]
                            logger.error(f"Failed to recover agent {agent_id}")
                    elif status == "running":
                        # Container is already running - check if it's the new version
                        # For now, assume it was successfully updated
                        logger.info(f"Container {container_name} is already running, assuming update completed")
                        deployment.agents_updated += 1
                        deployment.agents_pending_restart.remove(agent_id)
                        if agent_id in deployment.agents_in_progress:
                            del deployment.agents_in_progress[agent_id]
                    else:
                        # Container in unexpected state
                        logger.warning(f"Container {container_name} in unexpected state: {status}")
                        deployment.agents_failed += 1
                        deployment.agents_pending_restart.remove(agent_id)
                        if agent_id in deployment.agents_in_progress:
                            del deployment.agents_in_progress[agent_id]
                
                # Save state after each agent
                self._save_state()
            
            # Check if deployment is complete
            if (deployment.agents_updated + deployment.agents_deferred + deployment.agents_failed) >= deployment.agents_total:
                deployment.status = "completed"
                deployment.completed_at = datetime.now(timezone.utc).isoformat()
                deployment.message = f"Deployment recovered after manager restart: {deployment.agents_updated} updated, {deployment.agents_deferred} deferred, {deployment.agents_failed} failed"
                self.current_deployment = None
                logger.info(f"Deployment {deployment.deployment_id} recovery completed")
            else:
                # Continue with remaining agents if needed
                logger.info(f"Deployment {deployment.deployment_id} recovery in progress")
            
            self._save_state()
            
        except Exception as e:
            logger.error(f"Error recovering deployment {deployment.deployment_id}: {e}")
            deployment.status = "failed"
            deployment.completed_at = datetime.now(timezone.utc).isoformat()
            deployment.message = f"Recovery failed: {str(e)}"
            self.current_deployment = None
            self._save_state()

    async def _update_nginx_container(
        self, gui_image: str, nginx_image: Optional[str] = None
    ) -> bool:
        """
        Update the GUI and optionally nginx containers with new images.

        Args:
            gui_image: New GUI image to deploy
            nginx_image: Optional new nginx image to deploy

        Returns:
            True if successful, False otherwise
        """
        try:
            success = True

            # Update GUI container
            if gui_image:
                # Normalize image name to lowercase for Docker compatibility
                gui_image = gui_image.lower()
                logger.info(f"Updating GUI container to {gui_image}")
                # Store previous image for rollback capability
                await self._store_container_version("gui", gui_image)

            # Pull the new image first
            logger.info(f"Pulling GUI image: {gui_image}")
            pull_result = await asyncio.create_subprocess_exec(
                "docker",
                "pull",
                gui_image,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await pull_result.communicate()

            if pull_result.returncode != 0:
                logger.error(f"Failed to pull GUI image: {stderr.decode()}")
                return False

            # Find GUI container
            result = await asyncio.create_subprocess_exec(
                "docker",
                "ps",
                "--format",
                "{{.Names}}",
                "--filter",
                "name=gui",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await result.communicate()

            if result.returncode != 0:
                logger.error(f"Failed to list GUI containers: {stderr.decode()}")
                return False

            gui_containers = stdout.decode().strip().split("\n")
            gui_containers = [c for c in gui_containers if c]  # Remove empty strings

            if not gui_containers:
                logger.warning("No GUI container found to update")
                # Don't return here - we might still need to update nginx
            else:
                for container_name in gui_containers:
                    logger.info(f"Updating GUI container: {container_name}")

                    # GUI is a standalone container, not managed by docker-compose
                    # Stop the existing container
                    stop_result = await asyncio.create_subprocess_exec(
                        "docker",
                        "stop",
                        container_name,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    await stop_result.communicate()

                    # Remove the old container
                    rm_result = await asyncio.create_subprocess_exec(
                        "docker",
                        "rm",
                        container_name,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    await rm_result.communicate()

                    # Run new container with updated image
                    # Use host network to match nginx configuration
                    run_result = await asyncio.create_subprocess_exec(
                        "docker",
                        "run",
                        "-d",
                        "--name",
                        container_name,
                        "--restart",
                        "unless-stopped",
                        "--network",
                        "host",  # Use host network to match nginx
                        gui_image,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    stdout, stderr = await run_result.communicate()

                    if run_result.returncode != 0:
                        logger.error(f"Failed to recreate GUI container: {stderr.decode()}")
                        success = False
                    else:
                        logger.info(f"Successfully updated GUI container with image {gui_image}")

            # Update nginx container if specified
            if nginx_image:
                logger.info(f"Updating nginx container to {nginx_image}")
                # Store previous image for rollback capability
                await self._store_container_version("nginx", nginx_image)

                # Pull the nginx image
                pull_result = await asyncio.create_subprocess_exec(
                    "docker",
                    "pull",
                    nginx_image,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await pull_result.communicate()

                if pull_result.returncode != 0:
                    logger.error(f"Failed to pull nginx image: {stderr.decode()}")
                    success = False
                else:
                    # Update nginx container using docker-compose
                    compose_result = await asyncio.create_subprocess_exec(
                        "docker-compose",
                        "-f",
                        "/opt/ciris/docker-compose.yml",
                        "up",
                        "-d",
                        "--no-deps",
                        "--force-recreate",
                        "nginx",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        env={**os.environ, "NGINX_IMAGE": nginx_image},
                    )
                    stdout, stderr = await compose_result.communicate()

                    if compose_result.returncode != 0:
                        logger.error(f"Failed to update nginx container: {stderr.decode()}")
                        success = False

            if success:
                logger.info("Successfully updated container(s)")
            return success

        except Exception as e:
            logger.error(f"Error updating containers: {e}")
            return False

    async def _update_agent_metadata(self, agent_id: str, notification: UpdateNotification) -> None:
        """
        Update agent metadata with current image digests after successful deployment.

        Args:
            agent_id: Agent identifier
            notification: Update notification with new images
        """
        try:
            # Get the agent from registry
            if not self.manager:
                logger.warning("No manager instance available for metadata update")
                return

            agent_info = self.manager.agent_registry.get_agent(agent_id)
            if not agent_info:
                logger.warning(f"Agent {agent_id} not found in registry")
                return

            # Initialize metadata if needed
            if not hasattr(agent_info, "metadata"):
                agent_info.metadata = {}

            # Rotate image versions: current -> n-1 -> n-2
            if "current_images" not in agent_info.metadata:
                agent_info.metadata["current_images"] = {}
            if "previous_images" not in agent_info.metadata:
                agent_info.metadata["previous_images"] = {}

            # Move current to n-1, n-1 to n-2
            current_agent = agent_info.metadata["current_images"].get("agent")
            n1_agent = agent_info.metadata["previous_images"].get("n-1")

            if current_agent:
                # Move current to n-1
                agent_info.metadata["previous_images"]["n-1"] = current_agent

                if n1_agent:
                    # Move n-1 to n-2
                    agent_info.metadata["previous_images"]["n-2"] = n1_agent

            # Store the new current version
            if notification.agent_image:
                digest = await self.registry_client.resolve_image_digest(notification.agent_image)
                if digest:
                    agent_info.metadata["current_images"]["agent"] = digest
                    agent_info.metadata["current_images"]["agent_tag"] = notification.agent_image

            if notification.gui_image:
                digest = await self.registry_client.resolve_image_digest(notification.gui_image)
                if digest:
                    agent_info.metadata["current_images"]["gui"] = digest

            agent_info.metadata["last_updated"] = datetime.now(timezone.utc).isoformat()
            agent_info.metadata["version_history"] = agent_info.metadata.get("version_history", [])

            # Add to version history (keep last 10 deployments)
            agent_info.metadata["version_history"].append(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "agent_image": notification.agent_image,
                    "deployment_id": self.current_deployment,
                }
            )
            agent_info.metadata["version_history"] = agent_info.metadata["version_history"][-10:]

            # Save the updated metadata
            self.manager.agent_registry._save_metadata()
            logger.info(
                f"Updated metadata for agent {agent_id}: "
                f"current={notification.agent_image}, n-1={current_agent}, n-2={n1_agent}"
            )

            # Schedule image cleanup to remove versions older than n-2
            task = asyncio.create_task(self._trigger_image_cleanup())
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

        except Exception as e:
            logger.error(f"Failed to update agent metadata: {e}")

    async def _trigger_image_cleanup(self) -> None:
        """Trigger Docker image cleanup to maintain only n-2 versions."""
        try:
            from ciris_manager.docker_image_cleanup import DockerImageCleanup

            # Clean up keeping n-2 versions
            cleanup = DockerImageCleanup(versions_to_keep=3)  # Current, n-1, n-2
            results = await cleanup.cleanup_images()

            if results:
                total_removed = sum(results.values())
                if total_removed > 0:
                    logger.info(f"Image cleanup removed {total_removed} old images")
        except Exception as e:
            # Don't fail deployment if cleanup fails
            logger.warning(f"Image cleanup failed (non-critical): {e}")

    async def _store_container_version(self, container_type: str, new_image: str) -> None:
        """
        Store container version history for rollback capability.

        Args:
            container_type: Type of container (gui, nginx, etc.)
            new_image: New image being deployed
        """
        try:
            # Store in a metadata file for infrastructure containers
            # Use /tmp for now as it's always writable
            metadata_file = Path(f"/tmp/ciris_manager_{container_type}_versions.json")
            metadata_file.parent.mkdir(parents=True, exist_ok=True)

            versions = {}
            if metadata_file.exists():
                async with aiofiles.open(metadata_file, "r") as f:
                    content = await f.read()
                    versions = json.loads(content)

            # Rotate versions
            current = versions.get("current")
            if current and current != new_image:  # Only rotate if actually different
                # Move n-1 to n-2 first
                n1 = versions.get("n-1")
                if n1:
                    versions["n-2"] = n1
                # Then move current to n-1
                versions["n-1"] = current

            # Store new version
            versions["current"] = new_image
            versions["updated_at"] = datetime.now(timezone.utc).isoformat()

            async with aiofiles.open(metadata_file, "w") as f:
                await f.write(json.dumps(versions, indent=2))

            logger.info(f"Stored {container_type} version: {new_image}")

        except Exception as e:
            logger.error(f"Failed to store {container_type} version: {e}")

    async def _rollback_gui_container(self, target_version: str) -> bool:
        """
        Rollback GUI container to a previous version.

        Args:
            target_version: Version to rollback to (or "n-1" for previous)

        Returns:
            True if successful, False otherwise
        """
        try:
            # Get target image
            if target_version in ["n-1", "n-2"]:
                metadata_file = Path("/opt/ciris/metadata/gui_versions.json")
                if metadata_file.exists():
                    async with aiofiles.open(metadata_file, "r") as f:
                        content = await f.read()
                        versions = json.loads(content)
                    target_image = versions.get(target_version)
                    if not target_image:
                        logger.error(f"No {target_version} version found for GUI")
                        return False
                else:
                    logger.error("No GUI version history found")
                    return False
            else:
                target_image = target_version

            logger.info(f"Rolling back GUI container to {target_image}")

            # Update using docker-compose
            compose_result = await asyncio.create_subprocess_exec(
                "docker-compose",
                "-f",
                "/opt/ciris/docker-compose.yml",
                "up",
                "-d",
                "--no-deps",
                "gui",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "CIRIS_GUI_IMAGE": target_image},
            )
            stdout, stderr = await compose_result.communicate()

            if compose_result.returncode != 0:
                logger.error(f"Failed to rollback GUI: {stderr.decode()}")
                return False

            logger.info("GUI container rolled back successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to rollback GUI container: {e}")
            return False

    async def _rollback_nginx_container(self, target_version: str) -> bool:
        """
        Rollback nginx container to a previous version.

        Args:
            target_version: Version to rollback to (or "n-1" for previous)

        Returns:
            True if successful, False otherwise
        """
        try:
            # Get target image
            if target_version in ["n-1", "n-2"]:
                metadata_file = Path("/opt/ciris/metadata/nginx_versions.json")
                if metadata_file.exists():
                    async with aiofiles.open(metadata_file, "r") as f:
                        content = await f.read()
                        versions = json.loads(content)
                    target_image = versions.get(target_version)
                    if not target_image:
                        logger.error(f"No {target_version} version found for nginx")
                        return False
                else:
                    logger.error("No nginx version history found")
                    return False
            else:
                target_image = target_version

            logger.info(f"Rolling back nginx container to {target_image}")

            # Update using docker-compose
            compose_result = await asyncio.create_subprocess_exec(
                "docker-compose",
                "-f",
                "/opt/ciris/docker-compose.yml",
                "up",
                "-d",
                "--no-deps",
                "nginx",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "NGINX_IMAGE": target_image},
            )
            stdout, stderr = await compose_result.communicate()

            if compose_result.returncode != 0:
                logger.error(f"Failed to rollback nginx: {stderr.decode()}")
                return False

            # Regenerate nginx config after rollback
            if self.manager:
                await self.manager.update_nginx_config()

            logger.info("Nginx container rolled back successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to rollback nginx container: {e}")
            return False

    # Wrapper methods for v2 API compatibility
    async def process_update_notification(self, notification: UpdateNotification) -> str:
        """
        Process an update notification (wrapper for stage_deployment).

        This is for v2 API compatibility.
        """
        # Get all agents for staging
        from ciris_manager.docker_discovery import DockerAgentDiscovery

        if self.manager:
            discovery = DockerAgentDiscovery(self.manager.agent_registry)
            agents = discovery.discover_agents()
        else:
            agents = []

        return await self.stage_deployment(notification, agents)

    async def cancel_deployment(self, deployment_id: str) -> bool:
        """
        Cancel a deployment (wrapper for pause_deployment).

        This is for v2 API compatibility.
        """
        return await self.pause_deployment(deployment_id)

    async def launch_deployment(self, deployment_id: str) -> bool:
        """
        Launch a deployment (wrapper for launch_staged_deployment).

        This is for v2 API compatibility.
        """
        return await self.launch_staged_deployment(deployment_id)

    async def start_rollback(
        self,
        deployment_id: str,
        target_version: str,
        rollback_targets: Dict[str, Any],
        reason: str = "Manual rollback",
    ) -> None:
        """
        Start a rollback deployment.

        This is a simplified implementation for v2 API.
        """
        # For now, just log the rollback request
        logger.info(f"Rollback requested for {deployment_id}: {reason}")
        logger.info(f"Target version: {target_version}, targets: {rollback_targets}")

        # TODO: Implement actual rollback logic
        # This would involve:
        # 1. Creating a new deployment with rollback flag
        # 2. Setting target versions from version history
        # 3. Executing the rollback deployment
        pass
