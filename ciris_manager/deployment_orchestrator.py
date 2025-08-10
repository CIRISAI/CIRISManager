"""
Deployment orchestrator for CD operations.

Handles canary deployments, graceful shutdowns, and agent update coordination.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
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
            agents_needing_update = await self._check_agents_need_update(notification, agents)

            # Check if nginx/GUI needs updating (separate from agent updates)
            nginx_needs_update = False
            if notification.gui_image:
                # Always update nginx when a new GUI image is provided
                nginx_needs_update = True
                logger.info("Nginx/GUI container will be updated with new image")

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
                        return image_id

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
    ) -> List[AgentInfo]:
        """
        Check which agents actually need updating based on image digests.

        Args:
            notification: Update notification with new images
            agents: List of all agents

        Returns:
            List of agents that need updating
        """
        # Get digests of newly pulled images from local Docker
        new_agent_digest = None
        new_gui_digest = None

        if notification.agent_image:
            new_agent_digest = await self._get_local_image_digest(notification.agent_image)
            logger.info(f"New agent image digest: {new_agent_digest}")

        if notification.gui_image:
            new_gui_digest = await self._get_local_image_digest(notification.gui_image)
            logger.info(f"New GUI image digest: {new_gui_digest}")

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

            # For GUI/nginx changes, we always update (no need to check current)
            gui_changed = bool(new_gui_digest)

            if agent_changed or gui_changed:
                logger.info(
                    f"Agent {agent.agent_name} needs update: "
                    f"agent_changed={agent_changed}, gui_changed={gui_changed}"
                )
                if agent_changed:
                    logger.debug(f"  Agent image: {current_agent_digest} -> {new_agent_digest}")
                if gui_changed:
                    logger.debug("  GUI image will be updated")
                agents_needing_update.append(agent)
            else:
                logger.info(f"Agent {agent.agent_name} is up to date")

        return agents_needing_update

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

            # Wait and check health
            await asyncio.sleep(60)  # 1 minute observation period
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

            # Wait and check health
            await asyncio.sleep(120)  # 2 minute observation period
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

                    return AgentUpdateResponse(
                        agent_id=agent.agent_id,
                        decision="notified",  # Changed from "accept" to "notified"
                        reason="Shutdown requested but not guaranteed",
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
