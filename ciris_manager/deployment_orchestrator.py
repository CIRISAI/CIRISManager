"""
Deployment orchestrator for CD operations.

Handles canary deployments, graceful shutdowns, and agent update coordination.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import uuid4
import httpx

from ciris_manager.models import (
    AgentInfo,
    UpdateNotification,
    DeploymentStatus,
    AgentUpdateResponse,
)

logger = logging.getLogger(__name__)


class DeploymentOrchestrator:
    """Orchestrates deployments across agent fleet."""

    def __init__(self) -> None:
        """Initialize deployment orchestrator."""
        self.deployments: Dict[str, DeploymentStatus] = {}
        self.current_deployment: Optional[str] = None
        self._deployment_lock = asyncio.Lock()

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

            deployment_id = str(uuid4())
            status = DeploymentStatus(
                deployment_id=deployment_id,
                agents_total=len(agents),
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

            # Start deployment in background
            asyncio.create_task(self._run_deployment(deployment_id, notification, agents))

            return status

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
            logger.error(f"Deployment {deployment_id} failed: {e}")
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

    async def _run_canary_deployment(
        self,
        deployment_id: str,
        notification: UpdateNotification,
        agents: List[AgentInfo],
    ) -> None:
        """
        Run canary deployment (explorers → early adopters → general).

        Args:
            deployment_id: Deployment identifier
            notification: Update notification
            agents: List of agents
        """
        status = self.deployments[deployment_id]

        # Group agents by update readiness
        # Simple split: 10% explorers, 20% early adopters, 70% general
        running_agents = [a for a in agents if a.is_running]

        if not running_agents:
            status.message = "No running agents to update"
            return

        explorer_count = max(1, len(running_agents) // 10)
        early_adopter_count = max(1, len(running_agents) // 5)

        explorers = running_agents[:explorer_count]
        early_adopters = running_agents[explorer_count : explorer_count + early_adopter_count]
        general = running_agents[explorer_count + early_adopter_count :]

        # Phase 1: Explorers
        status.canary_phase = "explorers"
        status.message = f"Updating {len(explorers)} explorer agents"
        await self._update_agent_group(deployment_id, notification, explorers)

        # Wait and check health
        await asyncio.sleep(60)  # 1 minute observation period

        # Phase 2: Early Adopters
        status.canary_phase = "early_adopters"
        status.message = f"Updating {len(early_adopters)} early adopter agents"
        await self._update_agent_group(deployment_id, notification, early_adopters)

        # Wait and check health
        await asyncio.sleep(120)  # 2 minute observation period

        # Phase 3: General Population
        status.canary_phase = "general"
        status.message = f"Updating {len(general)} general agents"
        await self._update_agent_group(deployment_id, notification, general)

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
        try:
            # Get deployment status for peer results
            status = self.deployments.get(deployment_id)
            peer_results = ""
            if status:
                total_attempted = status.agents_updated + status.agents_deferred + status.agents_failed
                if total_attempted > 0:
                    peer_results = f"{status.agents_updated}/{total_attempted} peers updated successfully"
            
            # Build enhanced notification
            update_payload = {
                "new_image": notification.agent_image,
                "message": notification.message,
                "deployment_id": deployment_id,
                "version": notification.version,
                "changelog": notification.changelog or notification.message,
                "risk_level": notification.risk_level,
                "peer_results": peer_results,
                "commit_sha": notification.commit_sha,
            }
            
            # Call agent's graceful shutdown endpoint
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"http://localhost:{agent.api_port}/v1/system/update",
                    json=update_payload,
                    timeout=30.0,
                )

                if response.status_code == 200:
                    data = response.json()
                    return AgentUpdateResponse(
                        agent_id=agent.agent_id,
                        decision=data.get("decision", "accept"),
                        reason=data.get("reason"),
                        ready_at=data.get("ready_at"),
                    )
                else:
                    return AgentUpdateResponse(
                        agent_id=agent.agent_id,
                        decision="reject",
                        reason=f"HTTP {response.status_code}",
                        ready_at=None,
                    )

        except httpx.ConnectError:
            # Agent not reachable, might already be shutting down
            return AgentUpdateResponse(
                agent_id=agent.agent_id,
                decision="accept",
                reason="Agent not reachable (possibly shutting down)",
                ready_at=None,
            )
        except Exception as e:
            logger.error(f"Failed to update agent {agent.agent_id}: {e}")
            return AgentUpdateResponse(
                agent_id=agent.agent_id,
                decision="reject",
                reason=str(e),
                ready_at=None,
            )
