"""
Agent registry for tracking all managed agents.

Maintains metadata about agents including ports, compose files, and status.
"""

import json
import logging
from datetime import datetime
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
        created_at: Optional[str] = None
    ):
        self.agent_id = agent_id
        self.name = name
        self.port = port
        self.template = template
        self.compose_file = compose_file
        self.created_at = created_at or datetime.utcnow().isoformat() + "Z"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "port": self.port,
            "template": self.template,
            "compose_file": self.compose_file,
            "created_at": self.created_at
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
            created_at=data.get("created_at")
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
            with open(self.metadata_path, 'r') as f:
                data = json.load(f)
            
            agents_data = data.get('agents', {})
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
                "updated_at": datetime.utcnow().isoformat() + "Z",
                "agents": {
                    agent_id: agent.to_dict()
                    for agent_id, agent in self.agents.items()
                }
            }
            
            # Write atomically
            temp_path = self.metadata_path.with_suffix('.tmp')
            with open(temp_path, 'w') as f:
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
        compose_file: str
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
                compose_file=compose_file
            )
            
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
    
    def get_allocated_ports(self) -> Dict[str, int]:
        """Get mapping of agent IDs to allocated ports."""
        return {
            agent_id: agent.port
            for agent_id, agent in self.agents.items()
        }