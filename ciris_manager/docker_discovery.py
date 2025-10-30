"""
Docker container discovery for CIRISManager.
Discovers running CIRIS agents by querying Docker directly.
"""

import docker
from typing import List, Optional, Dict, Any
import logging

from ciris_manager.models import AgentInfo

logger = logging.getLogger("ciris_manager.docker_discovery")


class DockerAgentDiscovery:
    """Discovers CIRIS agents running in Docker containers."""

    def __init__(self, agent_registry=None, docker_client_manager=None) -> None:
        """
        Initialize agent discovery.

        Args:
            agent_registry: Agent registry for metadata
            docker_client_manager: MultiServerDockerClient for multi-server support
        """
        # For backward compatibility, support both local-only and multi-server modes
        self.docker_client_manager = docker_client_manager

        if not docker_client_manager:
            # Legacy mode: local Docker only
            try:
                self.client = docker.from_env()
                logger.debug("Connected to Docker daemon successfully")
            except Exception as e:
                logger.error(f"Failed to connect to Docker: {e}")
                self.client = None  # type: ignore[assignment]
        else:
            self.client = None  # type: ignore[assignment]

        self.agent_registry = agent_registry

    def discover_agents(self) -> List[AgentInfo]:
        """Discover all CIRIS agent containers across all servers."""
        if self.docker_client_manager:
            # Multi-server mode: discover from all servers
            return self._discover_multi_server()
        elif self.client:
            # Legacy mode: local Docker only
            return self._discover_local()
        else:
            logger.warning("No Docker client available, returning empty agent list")
            return []

    def _discover_local(self) -> List[AgentInfo]:
        """Discover agents from local Docker daemon (legacy mode)."""
        agents = []
        try:
            # Find all running containers with CIRIS agent characteristics
            # Only list running containers to avoid stale/stopped container data
            containers = self.client.containers.list(all=False)
            logger.debug(f"Found {len(containers)} running containers")

            for container in containers:
                # Check if this is a CIRIS agent by looking at environment variables
                env_vars = container.attrs.get("Config", {}).get("Env", [])
                env_dict = {}
                for env in env_vars:
                    if "=" in env:
                        key, value = env.split("=", 1)
                        env_dict[key] = value

                # Is this a CIRIS agent? Must have CIRIS_AGENT_ID
                if "CIRIS_AGENT_ID" in env_dict:
                    logger.debug(
                        f"Found CIRIS agent container: {container.name} (ID: {env_dict.get('CIRIS_AGENT_ID')})"
                    )
                    agent_info = self._extract_agent_info(container, env_dict)
                    if agent_info:
                        logger.debug(
                            f"Extracted agent info: {agent_info.agent_id} on port {agent_info.api_port}"
                        )
                        agents.append(agent_info)
                    else:
                        logger.warning(
                            f"Could not extract agent info from container {container.name}"
                        )

        except Exception as e:
            logger.error(f"Error discovering agents: {e}")

        return agents

    def _discover_multi_server(self) -> List[AgentInfo]:
        """Discover agents from all configured Docker servers."""
        all_agents = []

        # Get all server IDs
        server_ids = self.docker_client_manager.list_servers()
        logger.debug(f"Discovering agents from {len(server_ids)} servers: {server_ids}")

        for server_id in server_ids:
            try:
                # Get Docker client for this server
                client = self.docker_client_manager.get_client(server_id)
                server_config = self.docker_client_manager.get_server_config(server_id)

                # Find all containers on this server
                containers = client.containers.list(all=True)
                logger.debug(
                    f"Found {len(containers)} total containers on server {server_id} ({server_config.hostname})"
                )

                for container in containers:
                    # Check if this is a CIRIS agent
                    env_vars = container.attrs.get("Config", {}).get("Env", [])
                    env_dict = {}
                    for env in env_vars:
                        if "=" in env:
                            key, value = env.split("=", 1)
                            env_dict[key] = value

                    # Is this a CIRIS agent?
                    if "CIRIS_AGENT_ID" in env_dict:
                        logger.debug(
                            f"Found CIRIS agent on {server_id}: {container.name} (ID: {env_dict.get('CIRIS_AGENT_ID')})"
                        )
                        agent_info = self._extract_agent_info(
                            container, env_dict, server_id=server_id
                        )
                        if agent_info:
                            logger.debug(
                                f"Extracted agent info from {server_id}: {agent_info.agent_id} on port {agent_info.api_port}"
                            )
                            all_agents.append(agent_info)
                        else:
                            logger.warning(
                                f"Could not extract agent info from container {container.name} on {server_id}"
                            )

            except Exception as e:
                logger.error(f"Error discovering agents on server {server_id}: {e}")
                continue

        logger.info(f"Discovered {len(all_agents)} agents across all servers")
        return all_agents

    def _extract_agent_info(
        self, container: Any, env_dict: Dict[str, str], server_id: str = "main"
    ) -> Optional[AgentInfo]:
        """Extract agent information from a container."""
        try:
            # Get container details
            attrs = container.attrs
            config = attrs.get("Config", {})

            # Determine agent ID - REQUIRED for all CIRIS agents
            agent_id = env_dict.get("CIRIS_AGENT_ID")
            if not agent_id:
                logger.warning(f"Container {container.name} has no CIRIS_AGENT_ID - skipping")
                return None

            # Derive display name from agent_id
            # For development: datum -> Datum
            # For production: datum-a3b7c9 -> Datum (a3b7c9)
            parts = agent_id.rsplit("-", 1)
            if len(parts) == 2 and len(parts[1]) == 6 and parts[1].isalnum():
                # Has a 6-char suffix (production agent)
                base_name = parts[0].replace("-", " ").title()
                agent_name = f"{base_name} ({parts[1]})"
            else:
                # No suffix (development) or non-standard format
                agent_name = agent_id.replace("-", " ").title()

            # Extract runtime configuration from environment
            # Check if mock LLM is disabled (defaults to true if not set)
            mock_llm_setting = env_dict.get("CIRIS_MOCK_LLM", "true").lower()
            mock_llm = mock_llm_setting != "false"  # Only false if explicitly set to false

            # Discord is enabled if "discord" is in the CIRIS_ADAPTER list
            adapter_list = env_dict.get("CIRIS_ADAPTER", "api").lower()
            discord_enabled = "discord" in adapter_list

            # Get occurrence_id from environment if present (for multi-instance deployments)
            occurrence_id = env_dict.get("AGENT_OCCURRENCE_ID")

            # Get ALL static configuration from registry - single source of truth
            # Use composite key lookup with occurrence_id and server_id
            registry_agent = (
                self.agent_registry.get_agent(
                    agent_id, occurrence_id=occurrence_id, server_id=server_id
                )
                if self.agent_registry
                else None
            )

            # Registry is the source of truth for port, template, deployment
            api_port = None
            template = "unknown"
            deployment = "CIRIS_DISCORD_PILOT"  # Default deployment

            if registry_agent:
                # ALWAYS use port from registry - it's the allocated port
                # Registry stores it as 'port', not 'api_port'
                api_port = registry_agent.port if hasattr(registry_agent, "port") else None
                template = registry_agent.template
                # Get deployment from metadata
                if hasattr(registry_agent, "metadata") and registry_agent.metadata:
                    deployment = registry_agent.metadata.get("deployment", "CIRIS_DISCORD_PILOT")

            # Determine deployment type based on server
            # Main server (agents.ciris.ai) has FULL deployment (GUI + API)
            # Remote servers are API_ONLY
            deployment_type = "FULL" if server_id == "main" else "API_ONLY"

            # Build agent info - simple and typed
            agent_info = AgentInfo(
                agent_id=agent_id,
                agent_name=agent_name,
                container_name=container.name,
                api_port=int(api_port) if api_port else None,
                status=container.status,
                image=config.get("Image"),
                oauth_status=None,  # OAuth status tracked separately in metadata
                cognitive_state=None,  # Will be populated from agent status API
                service_token=None,  # Service tokens are in agent registry, not containers
                version=None,  # Will be populated by query_agent_version
                codename=None,
                code_hash=None,
                mock_llm=mock_llm,
                discord_enabled=discord_enabled,
                template=template,
                deployment=deployment,
                server_id=server_id,
                occurrence_id=occurrence_id,  # Multi-instance agent identifier
                deployment_type=deployment_type,
                created_at=None,
                health="healthy" if container.status == "running" else "unhealthy",
                api_endpoint=f"http://localhost:{api_port}" if api_port else None,
                update_available=False,
            )

            # Query version info if agent is running
            if agent_info.is_running and agent_info.has_port and agent_info.api_port:
                version_info = self._query_agent_version(
                    agent_id, agent_info.api_port, occurrence_id=occurrence_id, server_id=server_id
                )
                if version_info:
                    agent_info.version = version_info.get("version")
                    agent_info.codename = version_info.get("codename")
                    agent_info.code_hash = version_info.get("code_hash")
                    agent_info.cognitive_state = version_info.get("cognitive_state")
                    logger.debug(
                        f"Agent {agent_id} version: {agent_info.version} ({agent_info.codename}) state: {agent_info.cognitive_state}"
                    )

                    # Update the registry with fresh version info
                    if self.agent_registry and agent_info.version and agent_info.cognitive_state:
                        self.agent_registry.update_agent_state(
                            agent_id,
                            agent_info.version,
                            agent_info.cognitive_state,
                            occurrence_id=occurrence_id,
                            server_id=server_id,
                        )

            return agent_info

        except Exception as e:
            logger.error(f"Error extracting info from container {container.name}: {e}")
            return None

    def _query_agent_version(
        self,
        agent_id: str,
        port: int,
        occurrence_id: Optional[str] = None,
        server_id: str = "main",
    ) -> Optional[Dict[str, str]]:
        """Query agent's /v1/agent/status endpoint for version information."""
        try:
            # Use synchronous httpx client for simplicity in sync context
            import httpx
            from ciris_manager.agent_auth import get_agent_auth

            # Get authentication headers
            auth = get_agent_auth(self.agent_registry, self.docker_client_manager)

            # Check if we should skip auth attempts due to backoff
            if hasattr(auth, "_should_skip_auth_attempt") and auth._should_skip_auth_attempt(
                agent_id
            ):
                logger.debug(f"Skipping version query for {agent_id} due to auth backoff")
                return None

            try:
                headers = auth.get_auth_headers(
                    agent_id, occurrence_id=occurrence_id, server_id=server_id
                )
            except ValueError as e:
                logger.warning(f"Cannot authenticate with agent {agent_id}: {e}")
                return None

            # Build URL based on server location
            if server_id == "main" or not self.docker_client_manager:
                # Local server - use localhost
                base_url = "localhost"
            else:
                # Remote server - get VPC IP from server config
                server_config = self.docker_client_manager.get_server_config(server_id)
                base_url = server_config.vpc_ip if server_config.vpc_ip else server_config.hostname

            url = f"http://{base_url}:{port}/v1/agent/status"
            logger.debug(f"Querying agent version at {url}")
            with httpx.Client(timeout=2.0) as client:
                response = client.get(url, headers=headers)
                if response.status_code == 200:
                    # Record successful authentication
                    if hasattr(auth, "_record_auth_success"):
                        auth._record_auth_success(agent_id)

                    result = response.json()
                    # Handle wrapped response format
                    data = result.get("data", result)

                    # Normalize cognitive state - agents report "AgentState.WORK" but manager expects "WORK"
                    cognitive_state = data.get("cognitive_state", "")
                    if cognitive_state and cognitive_state.startswith("AgentState."):
                        cognitive_state = cognitive_state.replace("AgentState.", "")

                    return {
                        "version": data.get("version"),
                        "codename": data.get("codename"),
                        "code_hash": data.get("code_hash"),
                        "cognitive_state": cognitive_state,
                    }
                elif response.status_code == 401:
                    # Authentication failed - try to detect correct auth format
                    logger.info(f"Auth failed for {agent_id}, attempting format detection...")
                    detected_format = auth.detect_auth_format(
                        agent_id, occurrence_id=occurrence_id, server_id=server_id
                    )
                    if detected_format:
                        # Try again with detected format
                        headers = auth.get_auth_headers(
                            agent_id, occurrence_id=occurrence_id, server_id=server_id
                        )
                        response = client.get(url, headers=headers)
                        if response.status_code == 200:
                            # Record successful authentication
                            if hasattr(auth, "_record_auth_success"):
                                auth._record_auth_success(agent_id)

                            result = response.json()
                            data = result.get("data", result)
                            logger.info(
                                f"Version discovery successful for {agent_id} after format detection"
                            )

                            # Normalize cognitive state - agents report "AgentState.WORK" but manager expects "WORK"
                            cognitive_state = data.get("cognitive_state", "")
                            if cognitive_state and cognitive_state.startswith("AgentState."):
                                cognitive_state = cognitive_state.replace("AgentState.", "")

                            return {
                                "version": data.get("version"),
                                "codename": data.get("codename"),
                                "code_hash": data.get("code_hash"),
                                "cognitive_state": cognitive_state,
                            }
                        else:
                            # Record auth failure if still failing after detection
                            if hasattr(auth, "_record_auth_failure"):
                                auth._record_auth_failure(agent_id)
                            logger.warning(
                                f"Agent {agent_id} still returns {response.status_code} after format detection"
                            )
                    else:
                        # Format detection already recorded failure
                        logger.warning(f"Could not detect working auth format for {agent_id}")
                else:
                    logger.debug(
                        f"Agent {agent_id} status endpoint returned {response.status_code}"
                    )
        except Exception as e:
            logger.debug(f"Could not query version for agent {agent_id}: {e}")

        return None

    def get_agent_logs(self, container_name: str, lines: int = 100) -> str:
        """Get logs from an agent container."""
        if not self.client:
            return ""

        try:
            container = self.client.containers.get(container_name)
            logs = container.logs(tail=lines)
            if isinstance(logs, bytes):
                return logs.decode("utf-8")
            return str(logs)
        except Exception as e:
            logger.error(f"Error getting logs for {container_name}: {e}")
            return ""

    def restart_agent(self, container_name: str) -> bool:
        """Restart an agent container."""
        if not self.client:
            return False

        try:
            container = self.client.containers.get(container_name)
            container.restart()
            return True
        except Exception as e:
            logger.error(f"Error restarting {container_name}: {e}")
            return False

    def stop_agent(self, container_name: str) -> bool:
        """Stop an agent container."""
        if not self.client:
            return False

        try:
            container = self.client.containers.get(container_name)
            container.stop()
            return True
        except Exception as e:
            logger.error(f"Error stopping {container_name}: {e}")
            return False
