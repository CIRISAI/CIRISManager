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


class RegisteredAgent:
    """Information about a registered agent stored in the registry."""

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
        current_version: Optional[str] = None,
        last_work_state_at: Optional[str] = None,
        version_transitions: Optional[List[Dict[str, Any]]] = None,
    ):
        self.agent_id = agent_id
        self.name = name
        self.port = port
        self.template = template
        self.compose_file = compose_file
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()
        self.metadata = metadata or {}
        # Set deployment field with default for initial agents
        if "deployment" not in self.metadata:
            self.metadata["deployment"] = "CIRIS_DISCORD_PILOT"
        self.oauth_status = oauth_status
        self.service_token = service_token
        self.current_version = current_version
        self.last_work_state_at = last_work_state_at
        self.version_transitions = version_transitions or []

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
            "current_version": self.current_version,
            "last_work_state_at": self.last_work_state_at,
            "version_transitions": self.version_transitions,
        }

    @classmethod
    def from_dict(cls, agent_id: str, data: Dict[str, Any]) -> "RegisteredAgent":
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
            current_version=data.get("current_version"),
            last_work_state_at=data.get("last_work_state_at"),
            version_transitions=data.get("version_transitions", []),
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
        self.agents: Dict[str, RegisteredAgent] = {}
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
                self.agents[agent_id] = RegisteredAgent.from_dict(agent_id, agent_data)
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
    ) -> RegisteredAgent:
        """
        Register a new agent.

        Args:
            agent_id: Unique agent identifier
            name: Human-friendly agent name
            port: Allocated port number
            template: Template used to create agent
            compose_file: Path to docker-compose.yml

        Returns:
            Created RegisteredAgent object
        """
        with self._lock:
            agent = RegisteredAgent(
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

    def unregister_agent(self, agent_id: str) -> Optional[RegisteredAgent]:
        """
        Unregister an agent.

        Args:
            agent_id: Agent identifier

        Returns:
            Removed RegisteredAgent or None if not found
        """
        with self._lock:
            agent = self.agents.pop(agent_id, None)
            if agent:
                self._save_metadata()
                logger.info(f"Unregistered agent: {agent_id}")
            return agent

    def get_agent(self, agent_id: str) -> Optional[RegisteredAgent]:
        """Get agent by ID."""
        return self.agents.get(agent_id)

    def get_agent_by_name(self, name: str) -> Optional[RegisteredAgent]:
        """Get agent by name."""
        for agent in self.agents.values():
            if agent.name.lower() == name.lower():
                return agent
        return None

    def list_agents(self) -> List[RegisteredAgent]:
        """List all registered agents."""
        return list(self.agents.values())

    def update_agent_token(self, agent_id: str, encrypted_token: str) -> bool:
        """Update the service token for an agent.

        Args:
            agent_id: Agent identifier
            encrypted_token: New encrypted service token

        Returns:
            True if successful, False if agent not found
        """
        agent = self.agents.get(agent_id)
        if not agent:
            logger.error(f"Agent {agent_id} not found for token update")
            return False

        agent.service_token = encrypted_token
        self._save_metadata()
        logger.info(f"Updated service token for agent {agent_id}")
        return True

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

    def set_deployment(self, agent_id: str, deployment: str) -> bool:
        """Set the deployment identifier for an agent.

        Args:
            agent_id: Agent identifier
            deployment: Deployment identifier (e.g., 'CIRIS_DISCORD_PILOT')

        Returns:
            True if successful, False if agent not found
        """
        agent = self.agents.get(agent_id)
        if not agent:
            logger.error(f"Agent {agent_id} not found for deployment update")
            return False

        if not hasattr(agent, "metadata"):
            agent.metadata = {}

        agent.metadata["deployment"] = deployment
        self._save_metadata()
        logger.info(f"Set deployment for {agent_id} to {deployment}")
        return True

    def get_agents_by_deployment(self, deployment: str) -> List[RegisteredAgent]:
        """Get all agents with a specific deployment identifier.

        Args:
            deployment: Deployment identifier to filter by

        Returns:
            List of agents with matching deployment
        """
        result = []
        for agent in self.agents.values():
            metadata = agent.metadata if hasattr(agent, "metadata") else {}
            if metadata.get("deployment") == deployment:
                result.append(agent)
        return result

    def get_agents_by_canary_group(self) -> Dict[str, List[RegisteredAgent]]:
        """Get agents organized by canary group.

        Returns:
            Dict with keys 'explorer', 'early_adopter', 'general', 'unassigned'
        """
        groups: Dict[str, List[RegisteredAgent]] = {
            "explorer": [],
            "early_adopter": [],
            "general": [],
            "unassigned": [],
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

    def update_agent_state(self, agent_id: str, version: str, cognitive_state: str) -> bool:
        """
        Update agent version and cognitive state tracking.

        Args:
            agent_id: Agent identifier
            version: Current agent version
            cognitive_state: Current cognitive state (WAKEUP, WORK, etc.)

        Returns:
            True if updated successfully
        """
        with self._lock:
            if agent_id not in self.agents:
                return False

            agent = self.agents[agent_id]
            now = datetime.now(timezone.utc).isoformat()

            # Check for version change
            if agent.current_version != version:
                # Record version transition
                transition = {
                    "from_version": agent.current_version,
                    "to_version": version,
                    "timestamp": now,
                    "initial_state": cognitive_state,
                    "reached_work": cognitive_state in ["WORK", "work"],
                }
                if cognitive_state in ["WORK", "work"]:
                    transition["work_state_at"] = now
                agent.version_transitions.append(transition)
                agent.current_version = version

            # Track when agent reaches WORK state (handle lowercase from API)
            if cognitive_state in ["WORK", "work"]:
                agent.last_work_state_at = now

                # Mark if this is the first WORK state after version change
                if agent.version_transitions:
                    last_transition = agent.version_transitions[-1]
                    if not last_transition.get("reached_work", False):
                        last_transition["reached_work"] = True
                        last_transition["work_state_at"] = now

            self._save_metadata()
            return True
