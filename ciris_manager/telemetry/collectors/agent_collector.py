"""
Agent operational metrics collector implementation.

Collects high-level operational metrics from agents via their health API.
Does NOT collect internal audit trails or message content.
"""

import asyncio
import logging
from typing import List, Dict, Optional
import httpx

from ciris_manager.telemetry.base import BaseCollector
from ciris_manager.telemetry.schemas import (
    AgentOperationalMetrics,
    CognitiveState,
)
from ciris_manager.telemetry.debug_helpers import (
    validate_agent_metrics,
    validate_auth_response,
)
from ciris_manager.docker_discovery import DockerAgentDiscovery
from ciris_manager.agent_auth import get_agent_auth

logger = logging.getLogger(__name__)


class AgentMetricsCollector(BaseCollector[AgentOperationalMetrics]):
    """Collects operational metrics from CIRIS agents."""

    def __init__(self, agent_registry=None):
        """
        Initialize agent metrics collector.

        Args:
            agent_registry: Optional agent registry for auth tokens
        """
        super().__init__(name="AgentMetricsCollector", timeout_seconds=30)
        self.agent_registry = agent_registry
        self.discovery = DockerAgentDiscovery(agent_registry)
        self.auth = None
        if agent_registry:
            try:
                self.auth = get_agent_auth(agent_registry)
            except Exception as e:
                logger.warning(f"Failed to initialize agent auth: {e}")

    async def collect(self) -> List[AgentOperationalMetrics]:
        """Implement BaseCollector abstract method."""
        return await self.collect_agent_metrics()

    async def is_available(self) -> bool:
        """Check if Docker is available for discovery."""
        try:
            # Try to discover agents
            agents = self.discovery.discover_agents()
            return agents is not None
        except Exception:
            return False

    async def collect_agent_metrics(self) -> List[AgentOperationalMetrics]:
        """
        Collect operational metrics from all agents.

        Makes only ONE API call per agent, trying /v1/telemetry/overview first,
        then falling back to /v1/system/health if overview fails.
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
        metrics: List[AgentOperationalMetrics] = []
        for result in results:
            if isinstance(result, Exception):
                logger.warning(f"Failed to collect from agent: {result}")
            elif result and not isinstance(result, BaseException):
                metrics.append(result)

        logger.info(f"Collected metrics from {len(metrics)}/{len(agents)} agents")
        return metrics

    async def _collect_single_agent(self, agent) -> Optional[AgentOperationalMetrics]:
        """Collect metrics from a single agent using unified telemetry endpoint."""
        agent_id = agent.agent_id
        port = agent.api_port

        # Get auth headers if available
        headers = {}
        if self.auth:
            try:
                headers = self.auth.get_auth_headers(agent_id)
            except Exception as e:
                logger.debug(f"No auth available for {agent_id}: {e}")

        # Use unified telemetry endpoint which provides ALL metrics
        try:
            async with httpx.AsyncClient(timeout=5.0, headers=headers) as client:
                start_time = asyncio.get_event_loop().time()

                # Get unified telemetry with operational view (includes all metrics we need)
                unified_url = f"http://localhost:{port}/v1/telemetry/unified?view=operational"
                try:
                    response = await client.get(unified_url, headers=headers)
                    response_time_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)

                    # VALIDATE AUTH IMMEDIATELY
                    validate_auth_response(response, agent_id, "telemetry/unified")

                    if response.status_code == 200:
                        result = self._parse_unified_response(agent, response, response_time_ms)
                        # VALIDATE METRICS IMMEDIATELY
                        validate_agent_metrics(
                            result, f"collector._collect_single_agent({agent_id})"
                        )
                        return result
                    else:
                        logger.error(
                            f"❌ FAILED to get telemetry from {agent_id}: HTTP {response.status_code}"
                        )
                        logger.error(f"   Response: {response.text[:500]}")
                        return self._create_unhealthy_metrics(agent, response_time_ms)

                except Exception as e:
                    logger.error(f"❌ EXCEPTION getting telemetry from {agent_id}: {e}")
                    raise  # FAIL FAST AND LOUD

        except asyncio.TimeoutError:
            logger.warning(f"Agent {agent_id} health timeout")
            return self._create_unhealthy_metrics(agent, None)
        except Exception as e:
            logger.warning(f"Failed to get metrics for {agent_id}: {e}")
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
            carbon_24h_grams=0,
            api_port=agent.api_port or 0,
            oauth_configured=agent.has_oauth,
            oauth_providers=[],
        )

    def _parse_unified_response(
        self, agent, response, response_time_ms: int
    ) -> AgentOperationalMetrics:
        """Parse response from /v1/telemetry/unified endpoint."""
        agent_id = agent.agent_id
        port = agent.api_port

        # Parse unified telemetry response
        data = response.json()

        # Handle wrapped response format
        if "data" in data:
            data = data["data"]

        # Extract metrics from unified telemetry
        # The unified endpoint provides ALL metrics in a structured format

        # Get system health and uptime
        system_healthy = data.get("system_healthy", False)
        uptime_seconds = 86400  # Default if not available

        # Infrastructure metrics available at data["infrastructure"] if needed

        # Get bus metrics for LLM usage
        buses = data.get("buses", {})
        llm_bus = buses.get("llm_bus", {})

        # Extract cost and usage metrics from LLM bus
        total_cost_cents = 0
        total_requests = 0
        total_tokens = 0

        if llm_bus:
            # Get cost directly from the bus metrics
            total_cost_cents = llm_bus.get("total_cost_cents", 0)
            total_requests = llm_bus.get("request_count", 0)
            total_tokens = llm_bus.get("total_tokens", 0)

            # If cost is still 0, calculate from model costs
            if total_cost_cents == 0 and "model_costs" in llm_bus:
                for model, cost_data in llm_bus.get("model_costs", {}).items():
                    total_cost_cents += cost_data.get("cost_cents", 0)

        # Get message bus for message counts
        message_bus = buses.get("message_bus", {})
        message_count = message_bus.get("request_count", 0) if message_bus else total_requests

        # Calculate carbon footprint (rough estimate: 0.0001g CO2 per token)
        carbon_grams = total_tokens * 0.0001 if total_tokens else 0

        # Get cognitive state from runtime if available
        cognitive_state = CognitiveState.WORK  # Default
        runtime = data.get("runtime", {})
        if runtime and "cognitive_state" in runtime:
            cognitive_state = self._parse_cognitive_state(runtime["cognitive_state"])

        # Get version from metadata
        version = data.get("version", agent.version or "unknown")

        # Log what we got
        logger.info(
            f"📊 {agent_id} unified telemetry: "
            f"cost={total_cost_cents} cents, "
            f"requests={total_requests}, "
            f"messages={message_count}, "
            f"tokens={total_tokens}, "
            f"healthy={system_healthy}"
        )

        return AgentOperationalMetrics(
            agent_id=agent_id,
            agent_name=agent.agent_name,
            version=version,
            cognitive_state=cognitive_state,
            api_healthy=system_healthy,
            api_response_time_ms=response_time_ms,
            uptime_seconds=uptime_seconds,
            incident_count_24h=0,  # Could extract from error tracking if available
            message_count_24h=message_count,
            cost_cents_24h=total_cost_cents,
            carbon_24h_grams=int(carbon_grams),
            api_port=port,
            oauth_configured=agent.has_oauth,
            oauth_providers=[],
        )

    def _parse_llm_usage_response(
        self, agent, response, response_time_ms: int
    ) -> AgentOperationalMetrics:
        """Parse response from /v1/telemetry/llm/usage endpoint (legacy)."""
        agent_id = agent.agent_id
        port = agent.api_port

        # Parse LLM usage response
        data = response.json()

        # Handle wrapped response format
        if "data" in data:
            data = data["data"]

        # Extract cost and message data from LLM usage
        total_cost_cents = data.get("total_cost_cents", 0)
        total_requests = data.get("total_requests", 0)
        total_tokens = data.get("total_tokens", 0)

        # Calculate carbon footprint (rough estimate: 0.0001g CO2 per token)
        carbon_grams = total_tokens * 0.0001 if total_tokens else 0

        # Log what we got
        logger.info(
            f"📊 {agent_id} LLM usage: cost={total_cost_cents} cents, requests={total_requests}, tokens={total_tokens}"
        )

        # Get uptime from somewhere else if needed
        uptime_seconds = 86400  # Default to 1 day if not available

        return AgentOperationalMetrics(
            agent_id=agent_id,
            agent_name=agent.agent_name,
            version=agent.version or "unknown",
            cognitive_state=CognitiveState.WORK,  # Default to WORK
            api_healthy=True,
            api_response_time_ms=response_time_ms,
            uptime_seconds=uptime_seconds,
            incident_count_24h=0,
            message_count_24h=total_requests,  # Use requests as proxy for messages
            cost_cents_24h=total_cost_cents,
            carbon_24h_grams=int(carbon_grams),
            api_port=port,
            oauth_configured=agent.has_oauth,
            oauth_providers=[],
        )

    def _parse_overview_response(
        self, agent, response, response_time_ms: int
    ) -> AgentOperationalMetrics:
        """Parse response from /v1/telemetry/overview endpoint."""
        agent_id = agent.agent_id
        port = agent.api_port

        # Parse overview response
        overview_data = response.json()

        # Handle wrapped response format
        if "data" in overview_data:
            overview_data = overview_data["data"]

        # Extract fields from SystemOverview object
        version = overview_data.get("version", "unknown")
        cognitive_state = self._parse_cognitive_state(
            overview_data.get("cognitive_state", "unknown")
        )
        uptime_seconds = int(overview_data.get("uptime_seconds", 0))

        # Get telemetry metrics from overview
        cost_cents = overview_data.get("cost_24h_cents", 0)
        carbon_grams = overview_data.get("carbon_24h_grams", 0)
        messages_processed = overview_data.get("messages_processed_24h", 0)

        # Debug logging
        if cost_cents > 0 or carbon_grams > 0:
            logger.info(
                f"Agent {agent_id} metrics: cost={cost_cents} cents, carbon={carbon_grams}g, messages={messages_processed}"
            )
        errors_24h = overview_data.get("errors_24h", 0)
        api_healthy = overview_data.get("api_healthy", True)

        # Get OAuth status from agent info
        oauth_configured = agent.oauth_status in ["configured", "verified"]
        oauth_providers: List[str] = []  # Would need separate API call to get providers

        return AgentOperationalMetrics(
            agent_id=agent_id,
            agent_name=agent.agent_name,
            version=version,
            cognitive_state=cognitive_state,
            api_healthy=api_healthy,
            api_response_time_ms=response_time_ms,
            uptime_seconds=uptime_seconds,
            incident_count_24h=errors_24h,
            message_count_24h=messages_processed,
            cost_cents_24h=cost_cents,
            carbon_24h_grams=carbon_grams,
            api_port=port,
            oauth_configured=oauth_configured,
            oauth_providers=oauth_providers,
        )

    def _parse_health_response(
        self, agent, response, response_time_ms: int
    ) -> AgentOperationalMetrics:
        """Parse response from /v1/system/health endpoint (legacy)."""
        agent_id = agent.agent_id
        port = agent.api_port

        # Parse health response
        health_data = response.json()

        # Handle wrapped response format
        if "data" in health_data:
            health_data = health_data["data"]

        # Extract key fields
        version = health_data.get("version", "unknown")
        cognitive_state = self._parse_cognitive_state(health_data.get("cognitive_state", "unknown"))
        # Convert uptime to int (agents return float)
        uptime_seconds = int(health_data.get("uptime_seconds", 0))

        # Get telemetry summary if available
        incident_count = health_data.get("recent_incidents_count", 0)
        message_count = health_data.get("messages_24h", 0)
        cost_cents = health_data.get("cost_24h_cents", 0)
        # Health endpoint doesn't have carbon data
        carbon_grams = 0

        # Get OAuth status from agent info
        oauth_configured = agent.oauth_status in ["configured", "verified"]
        oauth_providers: List[str] = []  # Would need separate API call to get providers

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
            carbon_24h_grams=carbon_grams,
            api_port=port,
            oauth_configured=oauth_configured,
            oauth_providers=oauth_providers,
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
