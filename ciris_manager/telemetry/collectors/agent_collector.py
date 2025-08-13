"""
Agent operational metrics collector implementation.

Collects high-level operational metrics from agents via their health API.
Does NOT collect internal audit trails or message content.
"""

import asyncio
import logging
from typing import List, Dict, Optional
import httpx

from ciris_manager.telemetry.schemas import (
    AgentOperationalMetrics,
    CognitiveState,
)
from ciris_manager.docker_discovery import DockerAgentDiscovery
from ciris_manager.agent_auth import get_agent_auth

logger = logging.getLogger(__name__)


class AgentMetricsCollector:
    """Collects operational metrics from CIRIS agents."""

    def __init__(self, agent_registry=None):
        """
        Initialize agent metrics collector.

        Args:
            agent_registry: Optional agent registry for auth tokens
        """
        self.agent_registry = agent_registry
        self.discovery = DockerAgentDiscovery(agent_registry)
        self.auth = None
        if agent_registry:
            try:
                self.auth = get_agent_auth(agent_registry)
            except Exception as e:
                logger.warning(f"Failed to initialize agent auth: {e}")

    async def collect_agent_metrics(self) -> List[AgentOperationalMetrics]:
        """
        Collect operational metrics from all agents.

        Makes only ONE API call per agent to /v1/system/health.
        Returns partial results if some agents fail.
        """
        # Discover all agents
        agents = self.discovery.discover_agents()

        if not agents:
            logger.info("No agents discovered")
            return []

        # Collect metrics in parallel with timeout
        tasks = []
        for agent in agents:
            if agent.has_port:
                tasks.append(self._collect_single_agent(agent))

        if not tasks:
            logger.warning("No agents with valid ports")
            return []

        # Wait for all with timeout
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out failures
        metrics = []
        for result in results:
            if isinstance(result, Exception):
                logger.warning(f"Failed to collect from agent: {result}")
            elif result:
                metrics.append(result)

        logger.info(f"Collected metrics from {len(metrics)}/{len(agents)} agents")
        return metrics

    async def _collect_single_agent(self, agent) -> Optional[AgentOperationalMetrics]:
        """Collect metrics from a single agent."""
        agent_id = agent.agent_id
        port = agent.api_port

        # Get auth headers if available
        headers = {}
        if self.auth:
            try:
                headers = self.auth.get_auth_headers(agent_id)
            except Exception as e:
                logger.debug(f"No auth available for {agent_id}: {e}")

        # Make health API call with timeout
        url = f"http://localhost:{port}/v1/system/health"

        try:
            async with httpx.AsyncClient(timeout=5.0, headers=headers) as client:
                start_time = asyncio.get_event_loop().time()
                response = await client.get(url)
                response_time_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)

                if response.status_code != 200:
                    logger.warning(f"Agent {agent_id} health returned {response.status_code}")
                    return self._create_unhealthy_metrics(agent, response_time_ms)

                # Parse health response
                health_data = response.json()

                # Handle wrapped response format
                if "data" in health_data:
                    health_data = health_data["data"]

                # Extract key fields
                version = health_data.get("version", "unknown")
                cognitive_state = self._parse_cognitive_state(
                    health_data.get("cognitive_state", "unknown")
                )
                uptime_seconds = health_data.get("uptime_seconds", 0)

                # Get telemetry summary if available
                incident_count = health_data.get("recent_incidents_count", 0)
                message_count = health_data.get("messages_24h", 0)
                cost_cents = health_data.get("cost_24h_cents", 0)

                # Get OAuth status from agent info
                oauth_configured = agent.oauth_status in ["configured", "verified"]
                oauth_providers = []  # Would need separate API call to get providers

                return AgentOperationalMetrics(
                    agent_id=agent_id,
                    agent_name=agent.agent_name,
                    version=version,
                    cognitive_state=cognitive_state,
                    api_healthy=True,
                    api_response_time_ms=response_time_ms,
                    uptime_seconds=uptime_seconds,
                    incident_count_24h=incident_count,
                    message_count_24h=message_count,
                    cost_cents_24h=cost_cents,
                    api_port=port,
                    oauth_configured=oauth_configured,
                    oauth_providers=oauth_providers,
                )

        except asyncio.TimeoutError:
            logger.warning(f"Agent {agent_id} health timeout")
            return self._create_unhealthy_metrics(agent, None)
        except Exception as e:
            logger.warning(f"Failed to get health for {agent_id}: {e}")
            return self._create_unhealthy_metrics(agent, None)

    def _create_unhealthy_metrics(
        self, agent, response_time_ms: Optional[int]
    ) -> AgentOperationalMetrics:
        """Create metrics for unhealthy/unreachable agent."""
        return AgentOperationalMetrics(
            agent_id=agent.agent_id,
            agent_name=agent.agent_name,
            version="unknown",
            cognitive_state=CognitiveState.UNKNOWN,
            api_healthy=False,
            api_response_time_ms=response_time_ms,
            uptime_seconds=0,
            incident_count_24h=0,
            message_count_24h=0,
            cost_cents_24h=0,
            api_port=agent.api_port or 0,
            oauth_configured=agent.has_oauth,
            oauth_providers=[],
        )

    def _parse_cognitive_state(self, state: str) -> CognitiveState:
        """Parse cognitive state string to enum."""
        state_upper = state.upper()

        try:
            return CognitiveState(state_upper)
        except ValueError:
            # Handle any unexpected values
            if state_upper in ["WAKEUP", "WAKE_UP"]:
                return CognitiveState.WAKEUP
            elif state_upper == "WORK":
                return CognitiveState.WORK
            elif state_upper == "PLAY":
                return CognitiveState.PLAY
            elif state_upper == "SOLITUDE":
                return CognitiveState.SOLITUDE
            elif state_upper == "DREAM":
                return CognitiveState.DREAM
            elif state_upper == "SHUTDOWN":
                return CognitiveState.SHUTDOWN
            else:
                return CognitiveState.UNKNOWN

    async def get_agent_ports(self) -> Dict[str, int]:
        """
        Get port mappings for all agents.

        Uses agent registry as source of truth.
        """
        agents = self.discovery.discover_agents()

        port_map = {}
        for agent in agents:
            if agent.has_port:
                port_map[agent.agent_id] = agent.api_port

        return port_map
