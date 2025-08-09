"""
Agent registry for tracking all managed agents.

Maintains metadata about agents including ports, compose files, and status.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
from threading import Lock

logger = logging.getLogger(__name__)


class AgentInfo:
    """Information about a managed agent."""

    def __init__(
        self,
        agent_id: str,
        name: str,
        port: int,
        template: str,
        compose_file: str,
        created_at: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        oauth_status: Optional[str] = None,
        service_token: Optional[str] = None,
    ):
        self.agent_id = agent_id
        self.name = name
        self.port = port
        self.template = template
        self.compose_file = compose_file
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()
        self.metadata = metadata or {}
        self.oauth_status = oauth_status
        self.service_token = service_token

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "port": self.port,
            "template": self.template,
            "compose_file": self.compose_file,
            "created_at": self.created_at,
            "metadata": self.metadata,
            "oauth_status": self.oauth_status,
            "service_token": self.service_token,
        }

    @classmethod
    def from_dict(cls, agent_id: str, data: Dict[str, Any]) -> "AgentInfo":
        """Create from dictionary."""
        return cls(
            agent_id=agent_id,
            name=data["name"],
            port=data["port"],
            template=data["template"],
            compose_file=data["compose_file"],
            created_at=data.get("created_at"),
            metadata=data.get("metadata", {}),
            oauth_status=data.get("oauth_status"),
            service_token=data.get("service_token"),
        )


class AgentRegistry:
    """Registry for tracking all managed agents."""

    def __init__(self, metadata_path: Path):
        """
        Initialize agent registry.

        Args:
            metadata_path: Path to metadata.json file
        """
        self.metadata_path = metadata_path
        self.agents: Dict[str, AgentInfo] = {}
        self._lock = Lock()

        # Ensure directory exists
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing metadata
        self._load_metadata()

    def _load_metadata(self) -> None:
        """Load metadata from disk."""
        if not self.metadata_path.exists():
            logger.info(f"No existing metadata at {self.metadata_path}")
            return

        try:
            with open(self.metadata_path, "r") as f:
                data = json.load(f)

            agents_data = data.get("agents", {})
            for agent_id, agent_data in agents_data.items():
                self.agents[agent_id] = AgentInfo.from_dict(agent_id, agent_data)
                logger.info(f"Loaded agent: {agent_id}")

        except Exception as e:
            logger.error(f"Failed to load metadata: {e}")

    def _save_metadata(self) -> None:
        """Save metadata to disk."""
        try:
            data = {
                "version": "1.0",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "agents": {agent_id: agent.to_dict() for agent_id, agent in self.agents.items()},
            }

            # Write atomically
            temp_path = self.metadata_path.with_suffix(".tmp")
            with open(temp_path, "w") as f:
                json.dump(data, f, indent=2)

            temp_path.replace(self.metadata_path)
            logger.debug("Saved metadata to disk")

        except Exception as e:
            logger.error(f"Failed to save metadata: {e}")

    def register_agent(
        self,
        agent_id: str,
        name: str,
        port: int,
        template: str,
        compose_file: str,
        service_token: Optional[str] = None,
    ) -> AgentInfo:
        """
        Register a new agent.

        Args:
            agent_id: Unique agent identifier
            name: Human-friendly agent name
            port: Allocated port number
            template: Template used to create agent
            compose_file: Path to docker-compose.yml

        Returns:
            Created AgentInfo object
        """
        with self._lock:
            agent = AgentInfo(
                agent_id=agent_id,
                name=name,
                port=port,
                template=template,
                compose_file=compose_file,
                service_token=service_token,
            )

            agent.service_token = service_token

            self.agents[agent_id] = agent
            self._save_metadata()

            logger.info(f"Registered agent: {agent_id} on port {port}")
            return agent

    def unregister_agent(self, agent_id: str) -> Optional[AgentInfo]:
        """
        Unregister an agent.

        Args:
            agent_id: Agent identifier

        Returns:
            Removed AgentInfo or None if not found
        """
        with self._lock:
            agent = self.agents.pop(agent_id, None)
            if agent:
                self._save_metadata()
                logger.info(f"Unregistered agent: {agent_id}")
            return agent

    def get_agent(self, agent_id: str) -> Optional[AgentInfo]:
        """Get agent by ID."""
        return self.agents.get(agent_id)

    def get_agent_by_name(self, name: str) -> Optional[AgentInfo]:
        """Get agent by name."""
        for agent in self.agents.values():
            if agent.name.lower() == name.lower():
                return agent
        return None

    def list_agents(self) -> List[AgentInfo]:
        """List all registered agents."""
        return list(self.agents.values())

    def set_canary_group(self, agent_id: str, group: str) -> bool:
        """Set the canary deployment group for an agent.

        Args:
            agent_id: Agent identifier
            group: Canary group ('explorer', 'early_adopter', 'general', or None)

        Returns:
            True if successful, False if agent not found
        """
        agent = self.agents.get(agent_id)
        if not agent:
            return False

        if not hasattr(agent, "metadata"):
            agent.metadata = {}

        if group:
            agent.metadata["canary_group"] = group
        else:
            # Remove canary group assignment
            agent.metadata.pop("canary_group", None)

        self._save_metadata()
        logger.info(f"Set canary group for {agent_id} to {group}")
        return True

    def get_agents_by_canary_group(self) -> Dict[str, List[AgentInfo]]:
        """Get agents organized by canary group.

        Returns:
            Dict with keys 'explorer', 'early_adopter', 'general', 'unassigned'
        """
        groups: Dict[str, List[AgentInfo]] = {
            "explorer": [],
            "early_adopter": [],
            "general": [],
            "unassigned": []
        }

        for agent in self.agents.values():
            metadata = agent.metadata if hasattr(agent, "metadata") else {}
            group = metadata.get("canary_group", "unassigned")
            if group not in groups:
                group = "unassigned"
            groups[group].append(agent)

        return groups

    def get_allocated_ports(self) -> Dict[str, int]:
        """Get mapping of agent IDs to allocated ports."""
        return {agent_id: agent.port for agent_id, agent in self.agents.items()}
