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

    def __init__(self) -> None:
        try:
            self.client = docker.from_env()
            logger.debug("Connected to Docker daemon successfully")
        except Exception as e:
            logger.error(f"Failed to connect to Docker: {e}")
            self.client = None  # type: ignore[assignment]

    def discover_agents(self) -> List[AgentInfo]:
        """Discover all CIRIS agent containers."""
        if not self.client:
            logger.warning("No Docker client available, returning empty agent list")
            return []

        agents = []
        try:
            # Find all containers with CIRIS agent characteristics
            containers = self.client.containers.list(all=True)
            logger.debug(f"Found {len(containers)} total containers")

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

    def _extract_agent_info(self, container: Any, env_dict: Dict[str, str]) -> Optional[AgentInfo]:
        """Extract agent information from a container."""
        try:
            # Get container details
            attrs = container.attrs
            config = attrs.get("Config", {})
            network_settings = attrs.get("NetworkSettings", {})

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

            # Get port mapping
            api_port = None
            port_bindings = network_settings.get("Ports", {})
            for container_port, host_bindings in port_bindings.items():
                if "8080" in container_port and host_bindings:
                    api_port = host_bindings[0].get("HostPort")
                    break

            # Extract runtime configuration from environment
            # Check if mock LLM is disabled (defaults to true if not set)
            mock_llm_setting = env_dict.get("CIRIS_MOCK_LLM", "true").lower()
            mock_llm = mock_llm_setting != "false"  # Only false if explicitly set to false

            # Discord is enabled if "discord" is in the CIRIS_ADAPTER list
            adapter_list = env_dict.get("CIRIS_ADAPTER", "api").lower()
            discord_enabled = "discord" in adapter_list

            # Build agent info - simple and typed
            agent_info = AgentInfo(
                agent_id=agent_id,
                agent_name=agent_name,
                container_name=container.name,
                api_port=int(api_port) if api_port else None,
                status=container.status,
                image=config.get("Image"),
                oauth_status=None,  # OAuth status tracked separately in metadata
                service_token=None,  # Service tokens are in agent registry, not containers
                version=None,  # Will be populated by query_agent_version
                codename=None,
                code_hash=None,
                mock_llm=mock_llm,
                discord_enabled=discord_enabled,
                template="unknown",  # Template info from registry, not container
                created_at=None,
                health="healthy" if container.status == "running" else "unhealthy",
                api_endpoint=f"http://localhost:{api_port}" if api_port else None,
                update_available=False,
            )

            # Query version info if agent is running
            if agent_info.is_running and agent_info.has_port and agent_info.api_port:
                version_info = self._query_agent_version(agent_id, agent_info.api_port)
                if version_info:
                    agent_info.version = version_info.get("version")
                    agent_info.codename = version_info.get("codename")
                    agent_info.code_hash = version_info.get("code_hash")
                    logger.debug(
                        f"Agent {agent_id} version: {agent_info.version} ({agent_info.codename})"
                    )

            return agent_info

        except Exception as e:
            logger.error(f"Error extracting info from container {container.name}: {e}")
            return None

    def _query_agent_version(self, agent_id: str, port: int) -> Optional[Dict[str, str]]:
        """Query agent's /v1/agent/status endpoint for version information."""
        try:
            # Use synchronous httpx client for simplicity in sync context
            import httpx

            url = f"http://localhost:{port}/v1/agent/status"
            with httpx.Client(timeout=2.0) as client:
                response = client.get(url)
                if response.status_code == 200:
                    data = response.json()
                    return {
                        "version": data.get("version"),
                        "codename": data.get("codename"),
                        "code_hash": data.get("code_hash"),
                    }
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
