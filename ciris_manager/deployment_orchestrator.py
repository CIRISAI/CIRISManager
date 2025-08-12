"""
Deployment orchestrator for CD operations.

Handles canary deployments, graceful shutdowns, and agent update coordination.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
from uuid import uuid4
import httpx

from ciris_manager.models import (
    AgentInfo,
    UpdateNotification,
    DeploymentStatus,
    AgentUpdateResponse,
)
from ciris_manager.docker_registry import DockerRegistryClient

logger = logging.getLogger(__name__)


class DeploymentOrchestrator:
    """Orchestrates deployments across agent fleet."""

    def __init__(self, manager: Optional[Any] = None) -> None:
        """Initialize deployment orchestrator."""
        self.deployments: Dict[str, DeploymentStatus] = {}
        self.current_deployment: Optional[str] = None
        self._deployment_lock = asyncio.Lock()
        self.manager = manager

        # Initialize Docker registry client with GitHub token if available
        github_token = os.getenv("GITHUB_TOKEN") or os.getenv("CIRIS_GITHUB_TOKEN")
        self.registry_client = DockerRegistryClient(auth_token=github_token)

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
                    agents_total=len(agents),
                    agents_updated=0,
                    agents_deferred=0,
                    agents_failed=0,
                    started_at=datetime.now(timezone.utc).isoformat(),
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
                    agents_total=len(agents),
                    agents_updated=0,
                    agents_deferred=0,
                    agents_failed=0,
                    started_at=datetime.now(timezone.utc).isoformat(),
                    completed_at=datetime.now(timezone.utc).isoformat(),
                    status="completed",
                    message="No update needed - images unchanged",
                    canary_phase=None,
                )

            # Handle nginx-only updates immediately
            if nginx_needs_update and not agents_needing_update:
                logger.info("Only nginx/GUI needs updating - deploying immediately")
                deployment_id = str(uuid4())

                # Update nginx container (gui_image is guaranteed to be non-None here)
                nginx_updated = await self._update_nginx_container(notification.gui_image)  # type: ignore[arg-type]

                return DeploymentStatus(
                    deployment_id=deployment_id,
                    agents_total=0,
                    agents_updated=0,
                    agents_deferred=0,
                    agents_failed=0,
                    started_at=datetime.now(timezone.utc).isoformat(),
                    completed_at=datetime.now(timezone.utc).isoformat(),
                    status="completed" if nginx_updated else "failed",
                    message="Nginx/GUI container updated"
                    if nginx_updated
                    else "Failed to update nginx/GUI",
                    canary_phase=None,
                )

            deployment_id = str(uuid4())
            status = DeploymentStatus(
                deployment_id=deployment_id,
                agents_total=len(agents_needing_update),
                agents_updated=0,
                agents_deferred=0,
                agents_failed=0,
                started_at=datetime.now(timezone.utc).isoformat(),
                completed_at=None,
                status="in_progress",
                message=notification.message,
                canary_phase="explorers" if notification.strategy == "canary" else None,
            )

            self.deployments[deployment_id] = status
            self.current_deployment = deployment_id

            # Start deployment in background with only agents that need updates
            asyncio.create_task(
                self._run_deployment(deployment_id, notification, agents_needing_update)
            )

            return status

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
                logger.info(f"Pulling agent image: {notification.agent_image}")
                process = await asyncio.create_subprocess_exec(
                    "docker",
                    "pull",
                    notification.agent_image,
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
                logger.info(f"Pulling GUI image: {notification.gui_image}")
                process = await asyncio.create_subprocess_exec(
                    "docker",
                    "pull",
                    notification.gui_image,
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

    async def _check_agents_need_update(
        self,
        notification: UpdateNotification,
        agents: List[AgentInfo],
    ) -> tuple[List[AgentInfo], bool]:
        """
        Check which agents actually need updating based on image digests.

        Args:
            notification: Update notification with new images
            agents: List of all agents

        Returns:
            Tuple of (List of agents that need updating, bool for nginx needs update)
        """
        # Get digests of newly pulled images from local Docker
        new_agent_digest = None
        new_gui_digest = None
        nginx_needs_update = False

        if notification.agent_image:
            new_agent_digest = await self._get_local_image_digest(notification.agent_image)
            logger.info(f"New agent image digest: {new_agent_digest}")

        if notification.gui_image:
            new_gui_digest = await self._get_local_image_digest(notification.gui_image)
            logger.info(f"New GUI image digest: {new_gui_digest}")

            # Check if GUI container needs updating by comparing digests
            # Try to get current GUI container digest
            current_gui_digest = await self._get_container_image_digest("ciris-gui")
            if new_gui_digest and new_gui_digest != current_gui_digest:
                nginx_needs_update = True
                logger.info(f"GUI/nginx needs update: {current_gui_digest} -> {new_gui_digest}")
            else:
                logger.info("GUI/nginx image unchanged")

        # Check each agent to see if it needs updating
        agents_needing_update = []

        for agent in agents:
            # Get current image digest from running container
            current_agent_digest = None
            if agent.container_name:
                current_agent_digest = await self._get_container_image_digest(agent.container_name)
                logger.info(f"Agent {agent.agent_name} current digest: {current_agent_digest}")

            # Check if agent image changed
            agent_changed = new_agent_digest and new_agent_digest != current_agent_digest

            if agent_changed:
                logger.info(
                    f"Agent {agent.agent_name} needs update: "
                    f"agent image changed from {current_agent_digest} to {new_agent_digest}"
                )
                agents_needing_update.append(agent)
            else:
                logger.info(f"Agent {agent.agent_name} is up to date")

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
        finally:
            async with self._deployment_lock:
                if self.current_deployment == deployment_id:
                    self.current_deployment = None

            # Mark deployment as completed
            deployment_status = self.deployments.get(deployment_id)
            if deployment_status and deployment_status.status == "in_progress":
                deployment_status.status = "completed"
                deployment_status.completed_at = datetime.now(timezone.utc).isoformat()

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
                            )
                        ).total_seconds(),
                    },
                )

    async def _check_canary_group_health(
        self,
        deployment_id: str,
        agents: List[AgentInfo],
        phase_name: str,
        wait_for_work_minutes: int = 5,
        stability_minutes: int = 1,
    ) -> bool:
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
            True if at least one agent is stable in WORK state, False otherwise
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
                        
                        # Check health endpoint
                        health_url = f"http://localhost:{agent.port}/v1/health"
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
                                    # Check for recent incidents
                                    telemetry_url = f"http://localhost:{agent.port}/v1/telemetry/overview"
                                    telemetry_response = await client.get(telemetry_url, headers=headers)
                                    
                                    if telemetry_response.status_code == 200:
                                        telemetry_data = telemetry_response.json()
                                        if isinstance(telemetry_data, dict) and telemetry_data.get("data"):
                                            telemetry_data = telemetry_data["data"]
                                        
                                        incidents = telemetry_data.get("recent_incidents", [])
                                        
                                        # Check for critical incidents in the last stability_minutes
                                        recent_critical = False
                                        cutoff_time = datetime.now(timezone.utc).timestamp() - (stability_minutes * 60)
                                        
                                        for incident in incidents:
                                            if incident.get("severity") in ["critical", "high"]:
                                                incident_time = incident.get("timestamp", 0)
                                                if isinstance(incident_time, str):
                                                    # Parse ISO timestamp
                                                    from dateutil import parser
                                                    incident_time = parser.parse(incident_time).timestamp()
                                                if incident_time > cutoff_time:
                                                    recent_critical = True
                                                    break
                                        
                                        if not recent_critical:
                                            logger.info(
                                                f"Agent {agent.agent_id} is stable in WORK state "
                                                f"for {work_duration:.1f} minutes with no critical incidents"
                                            )
                                            return True
                            else:
                                # Agent not in WORK state, remove from tracking
                                if agent.agent_id in agents_in_work:
                                    del agents_in_work[agent.agent_id]
                                    logger.warning(
                                        f"Agent {agent.agent_id} left WORK state, now in {cognitive_state}"
                                    )
                                    
                except Exception as e:
                    logger.error(f"Error checking agent {agent.agent_id} health: {e}")
            
            # Wait before next check
            await asyncio.sleep(10)
        
        # Timeout reached
        logger.warning(
            f"Deployment {deployment_id}: No {phase_name} agents reached stable WORK state "
            f"within {wait_for_work_minutes} minutes"
        )
        return False

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
            return

        # Check if we have any agents in canary groups
        if not explorers and not early_adopters and not general:
            status.message = "No agents assigned to canary groups"
            logger.warning(
                "No agents assigned to canary groups, cannot proceed with canary deployment"
            )
            status.status = "failed"
            return

        # Phase 1: Explorers (if any)
        from ciris_manager.audit import audit_deployment_action

        if explorers:
            status.canary_phase = "explorers"
            status.message = f"Notifying {len(explorers)} explorer agents"
            logger.info(
                f"Deployment {deployment_id}: Starting explorer phase with {len(explorers)} pre-assigned explorer agents"
            )
            audit_deployment_action(
                deployment_id=deployment_id,
                action="canary_phase_started",
                details={"phase": "explorers", "agent_count": len(explorers)},
            )
            await self._update_agent_group(deployment_id, notification, explorers)

            # Wait for at least one explorer to reach WORK state and be stable
            if not await self._check_canary_group_health(
                deployment_id, explorers, "explorer", wait_for_work_minutes=5, stability_minutes=1
            ):
                status.message = "Explorer phase failed - no agents reached stable WORK state"
                status.status = "failed"
                logger.error(f"Deployment {deployment_id}: Explorer phase failed, aborting deployment")
                audit_deployment_action(
                    deployment_id=deployment_id,
                    action="canary_phase_failed",
                    details={"phase": "explorers", "reason": "no_stable_work_state"},
                )
                return
                
            logger.info(f"Deployment {deployment_id}: Explorer phase successful, proceeding to early adopters")
        else:
            logger.info(f"Deployment {deployment_id}: No explorer agents assigned, skipping phase")

        # Phase 2: Early Adopters (if any)
        if early_adopters:
            status.canary_phase = "early_adopters"
            status.message = f"Notifying {len(early_adopters)} early adopter agents"
            logger.info(
                f"Deployment {deployment_id}: Starting early adopter phase with {len(early_adopters)} pre-assigned agents"
            )
            audit_deployment_action(
                deployment_id=deployment_id,
                action="canary_phase_started",
                details={"phase": "early_adopters", "agent_count": len(early_adopters)},
            )
            await self._update_agent_group(deployment_id, notification, early_adopters)

            # Wait for at least one early adopter to reach WORK state and be stable
            if not await self._check_canary_group_health(
                deployment_id, early_adopters, "early adopter", wait_for_work_minutes=5, stability_minutes=1
            ):
                status.message = "Early adopter phase failed - no agents reached stable WORK state"
                status.status = "failed"
                logger.error(f"Deployment {deployment_id}: Early adopter phase failed, aborting deployment")
                audit_deployment_action(
                    deployment_id=deployment_id,
                    action="canary_phase_failed",
                    details={"phase": "early_adopters", "reason": "no_stable_work_state"},
                )
                return
                
            logger.info(f"Deployment {deployment_id}: Early adopter phase successful, proceeding to general")
        else:
            logger.info(
                f"Deployment {deployment_id}: No early adopter agents assigned, skipping phase"
            )

        # Phase 3: General Population (if any)
        if general:
            status.canary_phase = "general"
            status.message = f"Notifying {len(general)} general agents"
            logger.info(
                f"Deployment {deployment_id}: Starting general phase with {len(general)} pre-assigned agents"
            )
            audit_deployment_action(
                deployment_id=deployment_id,
                action="canary_phase_started",
                details={"phase": "general", "agent_count": len(general)},
            )
            await self._update_agent_group(deployment_id, notification, general)
            
            # For general population, just log if they don't reach WORK state (don't fail deployment)
            if await self._check_canary_group_health(
                deployment_id, general, "general", wait_for_work_minutes=5, stability_minutes=1
            ):
                logger.info(f"Deployment {deployment_id}: General phase agents reached stable WORK state")
            else:
                logger.warning(
                    f"Deployment {deployment_id}: Some general phase agents did not reach stable WORK state"
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
        await self._update_agent_group(deployment_id, notification, running_agents)

    async def _update_agent_group(
        self,
        deployment_id: str,
        notification: UpdateNotification,
        agents: List[AgentInfo],
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
                self._update_single_agent(deployment_id, notification, agent)
            )
            tasks.append(task)

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

    async def _update_single_agent(
        self,
        deployment_id: str,
        notification: UpdateNotification,
        agent: AgentInfo,
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

                # Add API indicator for clarity
                reason = f"System shutdown requested: {reason} (API shutdown by wa-system-admin)"

                shutdown_payload = {
                    "reason": reason,
                    "force": False,
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
                        deployment_id=deployment_id,
                        success=True,
                        token="[REDACTED]",  # Don't log actual token
                    )

                # Log the shutdown request
                logger.info(
                    f"Requesting shutdown for agent {agent.agent_id} at http://localhost:{agent.api_port}/v1/system/shutdown"
                )
                audit_deployment_action(
                    deployment_id=deployment_id,
                    action="shutdown_requested",
                    agent_id=agent.agent_id,
                    details={"reason": shutdown_payload["reason"]},
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
                        agent_id=agent.agent_id,
                        success=True,
                        details={"note": "Agent notified but may not shutdown immediately"},
                    )

                    # Update agent metadata with new image digests
                    if self.manager:
                        await self._update_agent_metadata(agent.agent_id, notification)
                        logger.debug(f"Updated metadata for agent {agent.agent_id}")

                    # Wait for container to stop and recreate it with new image
                    logger.info(f"Waiting for container {agent.container_name} to stop...")
                    stopped = await self._wait_for_container_stop(agent.container_name, timeout=60)

                    if stopped:
                        logger.info(
                            f"Container {agent.container_name} stopped, recreating with new image..."
                        )
                        recreated = await self._recreate_agent_container(agent.agent_id)

                        if recreated:
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
                            logger.error(f"Failed to recreate container for agent {agent.agent_id}")
                            return AgentUpdateResponse(
                                agent_id=agent.agent_id,
                                decision="reject",
                                reason="Failed to recreate container",
                                ready_at=None,
                            )
                    else:
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
                        agent_id=agent.agent_id,
                        success=False,
                        details={
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
                agent_id=agent.agent_id,
                success=True,  # We treat this as success since agent may be shutting down
                details={"error": str(e), "note": "Agent unreachable, shutdown status unknown"},
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
                agent_id=agent.agent_id,
                success=False,
                details={"error": str(e), "error_type": type(e).__name__},
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

            # Run docker-compose up -d to recreate the container
            result = await asyncio.create_subprocess_exec(
                "docker-compose",
                "-f",
                str(compose_file),
                "up",
                "-d",
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
            container_name = f"ciris-agent-{agent_id}"
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

    async def _update_nginx_container(self, gui_image: str) -> bool:
        """
        Update the nginx/GUI container with a new image.

        Args:
            gui_image: New GUI image to deploy

        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(f"Updating nginx/GUI container to {gui_image}")

            # Find and restart the GUI container (usually named ciris-gui)
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
                # This might be OK if there's no separate GUI container
                return True

            for container_name in gui_containers:
                logger.info(f"Restarting GUI container: {container_name}")

                # Stop the container
                stop_result = await asyncio.create_subprocess_exec(
                    "docker",
                    "stop",
                    container_name,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await stop_result.communicate()

                # Remove the container
                rm_result = await asyncio.create_subprocess_exec(
                    "docker",
                    "rm",
                    container_name,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await rm_result.communicate()

                # Docker compose or the container manager should recreate it with the new image
                # If using docker-compose, we need to recreate the service
                compose_result = await asyncio.create_subprocess_exec(
                    "docker-compose",
                    "-f",
                    "/opt/ciris/docker-compose.yml",
                    "up",
                    "-d",
                    "--force-recreate",
                    container_name,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd="/opt/ciris",
                )
                stdout, stderr = await compose_result.communicate()

                if compose_result.returncode != 0:
                    logger.error(f"Failed to recreate GUI container: {stderr.decode()}")
                    return False

            logger.info("Successfully updated nginx/GUI container")
            return True

        except Exception as e:
            logger.error(f"Error updating nginx/GUI container: {e}")
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

            # Update image digests in metadata
            if not hasattr(agent_info, "metadata"):
                agent_info.metadata = {}

            agent_info.metadata["current_images"] = {}

            # Store the resolved digests
            if notification.agent_image:
                digest = await self.registry_client.resolve_image_digest(notification.agent_image)
                if digest:
                    agent_info.metadata["current_images"]["agent"] = digest

            if notification.gui_image:
                digest = await self.registry_client.resolve_image_digest(notification.gui_image)
                if digest:
                    agent_info.metadata["current_images"]["gui"] = digest

            agent_info.metadata["last_updated"] = datetime.now(timezone.utc).isoformat()

            # Save the updated metadata
            self.manager.agent_registry._save_metadata()
            logger.info(f"Updated metadata for agent {agent_id} with new image digests")

        except Exception as e:
            logger.error(f"Failed to update agent metadata: {e}")
