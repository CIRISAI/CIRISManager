"""
Docker container discovery for CIRISManager.
Discovers running CIRIS agents by querying Docker directly.
"""

import docker
from typing import List, Optional, Dict, Any
import logging

from ciris_manager.models import AgentInfo

logger = logging.getLogger(__name__)


class DockerAgentDiscovery:
    """Discovers CIRIS agents running in Docker containers."""

    def __init__(self) -> None:
        try:
            self.client = docker.from_env()
        except Exception as e:
            logger.error(f"Failed to connect to Docker: {e}")
            self.client = None  # type: ignore[assignment]

    def discover_agents(self) -> List[AgentInfo]:
        """Discover all CIRIS agent containers."""
        if not self.client:
            return []

        agents = []
        try:
            # Find all containers with CIRIS agent characteristics
            containers = self.client.containers.list(all=True)

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
                    agent_info = self._extract_agent_info(container, env_dict)
                    if agent_info:
                        agents.append(agent_info)

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

            # Build agent info - simple and typed
            return AgentInfo(
                agent_id=agent_id,
                agent_name=agent_name,
                container_name=container.name,
                api_port=int(api_port) if api_port else None,
                status=container.status,
                image=config.get("Image"),
                oauth_status=None,  # OAuth status tracked separately in metadata
            )

        except Exception as e:
            logger.error(f"Error extracting info from container {container.name}: {e}")
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
