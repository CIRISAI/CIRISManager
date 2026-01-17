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
        admin_password: Optional[str] = None,
        current_version: Optional[str] = None,
        last_work_state_at: Optional[str] = None,
        version_transitions: Optional[List[Dict[str, Any]]] = None,
        do_not_autostart: Optional[bool] = None,
        server_id: Optional[str] = None,
        occurrence_id: Optional[str] = None,
        adapter_configs: Optional[Dict[str, Dict[str, Any]]] = None,
        llm_config: Optional[Dict[str, Any]] = None,
        oauth_allowed_domains: Optional[List[str]] = None,
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
        self.admin_password = admin_password  # Encrypted admin password
        self.current_version = current_version
        self.last_work_state_at = last_work_state_at
        self.version_transitions = version_transitions or []
        self.do_not_autostart = do_not_autostart or False
        self.server_id = server_id or "main"  # Default to main server for backward compatibility
        self.occurrence_id = occurrence_id  # For multi-instance deployments on same database
        self.adapter_configs = adapter_configs or {}  # Adapter configurations from wizard
        self.llm_config = llm_config  # Encrypted LLM provider configuration
        self.oauth_allowed_domains = (
            oauth_allowed_domains or []
        )  # Allowed domains for OAuth redirects

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        data = {
            "name": self.name,
            "port": self.port,
            "template": self.template,
            "compose_file": self.compose_file,
            "created_at": self.created_at,
            "metadata": self.metadata,
            "oauth_status": self.oauth_status,
            "service_token": self.service_token,
            "admin_password": self.admin_password,
            "current_version": self.current_version,
            "last_work_state_at": self.last_work_state_at,
            "version_transitions": self.version_transitions,
            "do_not_autostart": self.do_not_autostart,
            "server_id": self.server_id,
            "adapter_configs": self.adapter_configs,
            "llm_config": self.llm_config,
            "oauth_allowed_domains": self.oauth_allowed_domains,
        }
        # Include occurrence_id if set
        if self.occurrence_id:
            data["occurrence_id"] = self.occurrence_id

        # Include agent_id explicitly if:
        # 1. occurrence_id is set (needed to avoid parsing ambiguity), OR
        # 2. agent_id contains dashes (needed to avoid parsing ambiguity with composite keys)
        if self.occurrence_id or "-" in self.agent_id:
            data["agent_id"] = self.agent_id

        return data

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
            admin_password=data.get("admin_password"),
            current_version=data.get("current_version"),
            last_work_state_at=data.get("last_work_state_at"),
            version_transitions=data.get("version_transitions", []),
            do_not_autostart=data.get("do_not_autostart", False),
            server_id=data.get("server_id", "main"),  # Default to main for backward compatibility
            occurrence_id=data.get("occurrence_id"),  # For multi-instance deployments
            adapter_configs=data.get("adapter_configs", {}),  # Adapter configurations
            llm_config=data.get("llm_config"),  # LLM provider configuration
            oauth_allowed_domains=data.get("oauth_allowed_domains", []),  # OAuth redirect domains
        )


class AgentRegistry:
    """Registry for tracking all managed agents.

    Supports multiple redundant instances of the same agent_id on the same or different servers,
    using composite key (agent_id, occurrence_id, server_id) for unique identification.

    Key format: "agent_id-occurrence_id-server_id" (e.g., "scout-scout_lb_1-scout")
    """

    def __init__(self, metadata_path: Path):
        """
        Initialize agent registry.

        Args:
            metadata_path: Path to metadata.json file
        """
        self.metadata_path = metadata_path
        # Key format: "agent_id-occurrence_id-server_id" for composite key support
        self.agents: Dict[str, RegisteredAgent] = {}
        self._lock = Lock()

        # Ensure directory exists
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing metadata
        self._load_metadata()

    @staticmethod
    def _make_key(agent_id: str, occurrence_id: Optional[str], server_id: str) -> str:
        """Create composite key from agent_id, occurrence_id, and server_id.

        Args:
            agent_id: Agent identifier
            occurrence_id: Occurrence ID for database isolation (optional)
            server_id: Server identifier

        Returns:
            Composite key string in format "agent_id-occurrence_id-server_id"
            or "agent_id-server_id" if no occurrence_id
        """
        if occurrence_id:
            return f"{agent_id}-{occurrence_id}-{server_id}"
        else:
            # For backward compatibility with agents without occurrence_id
            return f"{agent_id}-{server_id}"

    @staticmethod
    def _parse_key(key: str) -> tuple[str, Optional[str], str]:
        """Parse composite key back to (agent_id, occurrence_id, server_id).

        Args:
            key: Composite key string

        Returns:
            Tuple of (agent_id, occurrence_id, server_id)
        """
        parts = key.split("-")
        known_servers = {"main", "scout", "scout2"}  # Known server IDs

        # Check if last part is a known server ID
        if len(parts) >= 2 and parts[-1] in known_servers:
            # Composite key format: agent_id-[occurrence_id]-server_id
            server_id = parts[-1]
            if len(parts) == 2:
                # Format: agent_id-server_id (no occurrence_id)
                return (parts[0], None, server_id)
            else:
                # Format: agent_id-occurrence_id-server_id
                agent_id = parts[0]
                occurrence_id = "-".join(parts[1:-1])  # Middle part(s) are occurrence_id
                return (agent_id, occurrence_id, server_id)
        else:
            # Backward compatibility: key doesn't end with server_id
            # Treat entire key as agent_id, default to main server
            return (key, None, "main")

    def _load_metadata(self) -> None:
        """Load metadata from disk with backward compatibility."""
        if not self.metadata_path.exists():
            logger.info(f"No existing metadata at {self.metadata_path}")
            return

        try:
            with open(self.metadata_path, "r") as f:
                data = json.load(f)

            agents_data = data.get("agents", {})
            for stored_key, agent_data in agents_data.items():
                # For composite keys with occurrence_id, agent_id is stored in data to avoid ambiguity
                # For backward compatibility, parse the key if agent_id not in data
                if "agent_id" in agent_data:
                    # Use explicit agent_id and server_id from data
                    # When agent_id is explicitly stored, trust the data completely
                    agent_id = agent_data["agent_id"]

                    # Create agent with data from file (includes correct server_id and occurrence_id)
                    agent = RegisteredAgent.from_dict(agent_id, agent_data)
                    server_id = agent.server_id  # Use explicit server_id from data
                    occurrence_id = (
                        agent.occurrence_id
                    )  # Use explicit occurrence_id from data (may be None)
                else:
                    # Parse the stored key (old format or no explicit agent_id in data)
                    agent_id, occurrence_id_from_key, server_id_from_key = self._parse_key(
                        stored_key
                    )

                    # Create RegisteredAgent with data from file
                    agent = RegisteredAgent.from_dict(agent_id, agent_data)

                    # For backward compatibility, use key-parsed server_id ONLY if key has explicit server suffix
                    # Otherwise, prefer server_id from data
                    parts = stored_key.split("-")
                    key_has_server_suffix = len(parts) >= 2 and parts[-1] in {
                        "main",
                        "scout",
                        "scout2",
                    }

                    if key_has_server_suffix and agent.server_id != server_id_from_key:
                        logger.warning(
                            f"Agent {agent_id} server_id mismatch: "
                            f"key={server_id_from_key}, data={agent.server_id}. Using key value."
                        )
                        server_id = server_id_from_key
                        agent.server_id = server_id
                    else:
                        # Use server_id from data
                        server_id = agent.server_id

                    # Set occurrence_id from key if not in data
                    occurrence_id = agent.occurrence_id or occurrence_id_from_key
                    if occurrence_id:
                        agent.occurrence_id = occurrence_id

                # Store using composite key
                composite_key = self._make_key(agent_id, occurrence_id, server_id)
                self.agents[composite_key] = agent

                if occurrence_id:
                    logger.info(
                        f"Loaded agent: {agent_id} (occurrence: {occurrence_id}) on server {server_id}"
                    )
                else:
                    logger.info(f"Loaded agent: {agent_id} on server {server_id}")

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
        admin_password: Optional[str] = None,
        server_id: str = "main",
        occurrence_id: Optional[str] = None,
        custom_environment: Optional[Dict[str, str]] = None,
    ) -> RegisteredAgent:
        """
        Register a new agent.

        Args:
            agent_id: Agent identifier (can be shared across instances)
            name: Human-friendly agent name
            port: Allocated port number
            template: Template used to create agent
            compose_file: Path to docker-compose.yml
            service_token: Encrypted service token for authentication
            admin_password: Encrypted admin password for agent
            server_id: Server hosting the agent (default: "main")
            occurrence_id: Occurrence ID for database isolation (optional, for multi-instance)
            custom_environment: Custom environment variables passed during creation (optional)

        Returns:
            Created RegisteredAgent object
        """
        with self._lock:
            # Store custom environment in metadata
            metadata = {}
            if custom_environment:
                metadata["custom_environment"] = custom_environment

            agent = RegisteredAgent(
                agent_id=agent_id,
                name=name,
                port=port,
                template=template,
                compose_file=compose_file,
                metadata=metadata,
                service_token=service_token,
                admin_password=admin_password,
                server_id=server_id,
                occurrence_id=occurrence_id,
            )

            # Store using composite key
            composite_key = self._make_key(agent_id, occurrence_id, server_id)
            self.agents[composite_key] = agent
            self._save_metadata()

            if occurrence_id:
                logger.info(
                    f"Registered agent: {agent_id} (occurrence: {occurrence_id}) "
                    f"on port {port} (server: {server_id})"
                )
            else:
                logger.info(f"Registered agent: {agent_id} on port {port} (server: {server_id})")

            return agent

    def unregister_agent(
        self,
        agent_id: str,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> Optional[RegisteredAgent]:
        """
        Unregister an agent.

        Args:
            agent_id: Agent identifier
            occurrence_id: Occurrence ID (optional, for composite key lookup)
            server_id: Server ID (optional, for composite key lookup)

        Returns:
            Removed RegisteredAgent or None if not found
        """
        with self._lock:
            if occurrence_id and server_id:
                # Precise lookup using composite key
                composite_key = self._make_key(agent_id, occurrence_id, server_id)
                agent = self.agents.pop(composite_key, None)
            elif server_id:
                # Lookup by agent_id and server_id (no occurrence_id)
                composite_key = self._make_key(agent_id, None, server_id)
                agent = self.agents.pop(composite_key, None)
            else:
                # Backward compatibility: try direct agent_id lookup
                agent = self.agents.pop(agent_id, None)
                # Also try with default server
                if not agent:
                    composite_key = self._make_key(agent_id, None, "main")
                    agent = self.agents.pop(composite_key, None)

            if agent:
                self._save_metadata()
                if occurrence_id:
                    logger.info(
                        f"Unregistered agent: {agent_id} (occurrence: {occurrence_id}, "
                        f"server: {server_id})"
                    )
                else:
                    logger.info(f"Unregistered agent: {agent_id}")
            return agent

    def get_agent(
        self,
        agent_id: str,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> Optional[RegisteredAgent]:
        """Get agent by ID with optional occurrence_id and server_id for precise lookup.

        Args:
            agent_id: Agent identifier
            occurrence_id: Occurrence ID (optional)
            server_id: Server ID (optional)

        Returns:
            RegisteredAgent or None if not found
        """
        if occurrence_id and server_id:
            # Precise composite key lookup
            composite_key = self._make_key(agent_id, occurrence_id, server_id)
            return self.agents.get(composite_key)
        elif server_id:
            # Lookup by agent_id and server_id (no occurrence_id)
            composite_key = self._make_key(agent_id, None, server_id)
            return self.agents.get(composite_key)
        else:
            # Backward compatibility: try direct agent_id lookup first
            agent = self.agents.get(agent_id)
            if agent:
                return agent
            # Try with default server
            composite_key = self._make_key(agent_id, None, "main")
            agent = self.agents.get(composite_key)
            if agent:
                return agent
            # Last resort: search for any agent with matching agent_id across all servers
            # This handles cases where caller doesn't know the server_id
            matches = self.get_agents_by_agent_id(agent_id)
            if matches:
                if len(matches) > 1:
                    logger.warning(
                        f"Multiple agents found with agent_id={agent_id}. "
                        f"Returning first match. Use server_id parameter for precise lookup."
                    )
                return matches[0]
            return None

    def get_agents_by_agent_id(self, agent_id: str) -> List[RegisteredAgent]:
        """Get all agent instances with the same agent_id across all servers/occurrences.

        Args:
            agent_id: Agent identifier

        Returns:
            List of RegisteredAgent instances matching the agent_id
        """
        return [agent for agent in self.agents.values() if agent.agent_id == agent_id]

    def get_agent_by_name(self, name: str) -> Optional[RegisteredAgent]:
        """Get agent by name."""
        for agent in self.agents.values():
            if agent.name.lower() == name.lower():
                return agent
        return None

    def list_agents(self) -> List[RegisteredAgent]:
        """List all registered agents."""
        return list(self.agents.values())

    def update_agent_token(
        self,
        agent_id: str,
        encrypted_token: str,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> bool:
        """Update the service token for an agent.

        Args:
            agent_id: Agent identifier
            encrypted_token: New encrypted service token
            occurrence_id: Occurrence ID (optional, for composite key lookup)
            server_id: Server ID (optional, for composite key lookup)

        Returns:
            True if successful, False if agent not found
        """
        agent = self.get_agent(agent_id, occurrence_id, server_id)
        if not agent:
            logger.error(f"Agent {agent_id} not found for token update")
            return False

        agent.service_token = encrypted_token
        self._save_metadata()
        logger.info(f"Updated service token for agent {agent_id}")
        return True

    def set_canary_group(
        self,
        agent_id: str,
        group: str,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> bool:
        """Set the canary deployment group for an agent.

        Args:
            agent_id: Agent identifier
            group: Canary group ('explorer', 'early_adopter', 'general', or None)
            occurrence_id: Occurrence ID (optional, for composite key lookup)
            server_id: Server ID (optional, for composite key lookup)

        Returns:
            True if successful, False if agent not found
        """
        agent = self.get_agent(agent_id, occurrence_id, server_id)
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

    def set_deployment(
        self,
        agent_id: str,
        deployment: str,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> bool:
        """Set the deployment identifier for an agent.

        Args:
            agent_id: Agent identifier
            deployment: Deployment identifier (e.g., 'CIRIS_DISCORD_PILOT')
            occurrence_id: Occurrence ID (optional, for composite key lookup)
            server_id: Server ID (optional, for composite key lookup)

        Returns:
            True if successful, False if agent not found
        """
        agent = self.get_agent(agent_id, occurrence_id, server_id)
        if not agent:
            logger.error(f"Agent {agent_id} not found for deployment update")
            return False

        if not hasattr(agent, "metadata"):
            agent.metadata = {}

        agent.metadata["deployment"] = deployment
        self._save_metadata()
        logger.info(f"Set deployment for {agent_id} to {deployment}")
        return True

    def set_do_not_autostart(
        self,
        agent_id: str,
        do_not_autostart: bool,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> bool:
        """Set the do_not_autostart flag for an agent.

        Args:
            agent_id: Agent identifier
            do_not_autostart: Whether to prevent automatic restart of this agent
            occurrence_id: Occurrence ID (optional, for composite key lookup)
            server_id: Server ID (optional, for composite key lookup)

        Returns:
            True if successful, False if agent not found
        """
        agent = self.get_agent(agent_id, occurrence_id, server_id)
        if not agent:
            logger.warning(f"Agent {agent_id} not found when setting do_not_autostart flag")
            return False

        agent.do_not_autostart = do_not_autostart
        self._save_metadata()

        status = "enabled" if do_not_autostart else "disabled"
        logger.info(f"Autostart prevention {status} for agent {agent_id}")
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

    def update_agent_state(
        self,
        agent_id: str,
        version: str,
        cognitive_state: str,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> bool:
        """
        Update agent version and cognitive state tracking.

        Args:
            agent_id: Agent identifier
            version: Current agent version
            cognitive_state: Current cognitive state (WAKEUP, WORK, etc.)
            occurrence_id: Occurrence ID (optional, for composite key lookup)
            server_id: Server ID (optional, for composite key lookup)

        Returns:
            True if updated successfully
        """
        with self._lock:
            agent = self.get_agent(agent_id, occurrence_id, server_id)
            if not agent:
                return False

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

    def get_adapter_configs(
        self,
        agent_id: str,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Get adapter configurations for an agent.

        Args:
            agent_id: Agent identifier
            occurrence_id: Occurrence ID (optional, for composite key lookup)
            server_id: Server ID (optional, for composite key lookup)

        Returns:
            Dictionary of adapter configs, empty dict if agent not found
        """
        agent = self.get_agent(agent_id, occurrence_id, server_id)
        if not agent:
            return {}
        return agent.adapter_configs

    def set_adapter_config(
        self,
        agent_id: str,
        adapter_type: str,
        config: Dict[str, Any],
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> bool:
        """
        Set or update configuration for a specific adapter.

        Args:
            agent_id: Agent identifier
            adapter_type: Type of adapter (e.g., 'home_assistant', 'reddit')
            config: Adapter configuration dictionary containing:
                - enabled: bool
                - configured_at: ISO timestamp
                - config: dict of adapter-specific settings
                - env_vars: dict mapping to environment variables
                - consent_given: bool (for consent-required adapters)
                - consent_timestamp: ISO timestamp (for consent)
            occurrence_id: Occurrence ID (optional, for composite key lookup)
            server_id: Server ID (optional, for composite key lookup)

        Returns:
            True if successful, False if agent not found
        """
        with self._lock:
            agent = self.get_agent(agent_id, occurrence_id, server_id)
            if not agent:
                logger.error(f"Agent {agent_id} not found for adapter config update")
                return False

            # Ensure configured_at is set
            if "configured_at" not in config:
                config["configured_at"] = datetime.now(timezone.utc).isoformat()

            agent.adapter_configs[adapter_type] = config
            self._save_metadata()
            logger.info(f"Updated adapter config for {adapter_type} on agent {agent_id}")
            return True

    def remove_adapter_config(
        self,
        agent_id: str,
        adapter_type: str,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> bool:
        """
        Remove configuration for a specific adapter.

        Args:
            agent_id: Agent identifier
            adapter_type: Type of adapter to remove
            occurrence_id: Occurrence ID (optional, for composite key lookup)
            server_id: Server ID (optional, for composite key lookup)

        Returns:
            True if removed, False if agent or config not found
        """
        with self._lock:
            agent = self.get_agent(agent_id, occurrence_id, server_id)
            if not agent:
                logger.error(f"Agent {agent_id} not found for adapter config removal")
                return False

            if adapter_type not in agent.adapter_configs:
                logger.warning(f"Adapter {adapter_type} config not found for agent {agent_id}")
                return False

            del agent.adapter_configs[adapter_type]
            self._save_metadata()
            logger.info(f"Removed adapter config for {adapter_type} on agent {agent_id}")
            return True

    def get_llm_config(
        self,
        agent_id: str,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Get LLM configuration for an agent with API keys decrypted.

        Args:
            agent_id: Agent identifier
            occurrence_id: Occurrence ID (optional, for composite key lookup)
            server_id: Server ID (optional, for composite key lookup)

        Returns:
            LLM config dictionary with decrypted keys, or None if not configured
        """
        from ciris_manager.crypto import get_token_encryption

        agent = self.get_agent(agent_id, occurrence_id, server_id)
        if not agent or not agent.llm_config:
            return None

        try:
            encryption = get_token_encryption()
            config = agent.llm_config.copy()

            # Decrypt primary API key
            if "primary" in config and config["primary"].get("api_key"):
                primary = config["primary"].copy()
                encrypted_key = primary["api_key"]
                if encrypted_key.startswith("gAAAAA"):
                    primary["api_key"] = encryption.decrypt_token(encrypted_key)
                config["primary"] = primary

            # Decrypt backup API key if present
            if "backup" in config and config["backup"] and config["backup"].get("api_key"):
                backup = config["backup"].copy()
                encrypted_key = backup["api_key"]
                if encrypted_key.startswith("gAAAAA"):
                    backup["api_key"] = encryption.decrypt_token(encrypted_key)
                config["backup"] = backup

            return config
        except Exception as e:
            logger.error(f"Failed to decrypt LLM config for {agent_id}: {e}")
            return None

    def set_llm_config(
        self,
        agent_id: str,
        config: Dict[str, Any],
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> bool:
        """
        Set LLM configuration for an agent with API keys encrypted.

        Args:
            agent_id: Agent identifier
            config: LLM config dictionary with plain-text API keys
                Expected format:
                {
                    "primary": {"provider": "openai", "api_key": "sk-...", "model": "gpt-4o"},
                    "backup": {"provider": "groq", "api_key": "gsk_...", "model": "llama-3.1-70b"}
                }
            occurrence_id: Occurrence ID (optional, for composite key lookup)
            server_id: Server ID (optional, for composite key lookup)

        Returns:
            True if successful, False if agent not found or encryption failed
        """
        from ciris_manager.crypto import get_token_encryption

        with self._lock:
            agent = self.get_agent(agent_id, occurrence_id, server_id)
            if not agent:
                logger.error(f"Agent {agent_id} not found for LLM config update")
                return False

            try:
                encryption = get_token_encryption()
                encrypted_config = config.copy()

                # Encrypt primary API key
                if "primary" in encrypted_config and encrypted_config["primary"].get("api_key"):
                    primary = encrypted_config["primary"].copy()
                    api_key = primary["api_key"]
                    # Only encrypt if not already encrypted
                    if not api_key.startswith("gAAAAA"):
                        primary["api_key"] = encryption.encrypt_token(api_key)
                    encrypted_config["primary"] = primary

                # Encrypt backup API key if present
                if (
                    "backup" in encrypted_config
                    and encrypted_config["backup"]
                    and encrypted_config["backup"].get("api_key")
                ):
                    backup = encrypted_config["backup"].copy()
                    api_key = backup["api_key"]
                    # Only encrypt if not already encrypted
                    if not api_key.startswith("gAAAAA"):
                        backup["api_key"] = encryption.encrypt_token(api_key)
                    encrypted_config["backup"] = backup

                agent.llm_config = encrypted_config
                self._save_metadata()
                logger.info(f"Updated LLM config for agent {agent_id}")
                return True

            except Exception as e:
                logger.error(f"Failed to encrypt LLM config for {agent_id}: {e}")
                return False

    def clear_llm_config(
        self,
        agent_id: str,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> bool:
        """
        Clear LLM configuration for an agent.

        Args:
            agent_id: Agent identifier
            occurrence_id: Occurrence ID (optional, for composite key lookup)
            server_id: Server ID (optional, for composite key lookup)

        Returns:
            True if cleared, False if agent not found
        """
        with self._lock:
            agent = self.get_agent(agent_id, occurrence_id, server_id)
            if not agent:
                logger.error(f"Agent {agent_id} not found for LLM config clear")
                return False

            agent.llm_config = None
            self._save_metadata()
            logger.info(f"Cleared LLM config for agent {agent_id}")
            return True
