"""
Port management for CIRIS agents.

Handles dynamic port allocation and tracking for agent containers.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Set, Optional

logger = logging.getLogger(__name__)


class PortManager:
    """Manages dynamic port allocation for agents."""
    
    def __init__(self, start_port: int = 8080, end_port: int = 8200, metadata_path: Optional[Path] = None):
        """
        Initialize port manager.
        
        Args:
            start_port: First port in allocation range
            end_port: Last port in allocation range
            metadata_path: Path to metadata.json for persistence
        """
        self.start_port = start_port
        self.end_port = end_port
        self.metadata_path = metadata_path
        
        # Port tracking
        self.allocated_ports: Dict[str, int] = {}  # agent_id -> port
        self.reserved_ports: Set[int] = {8888, 3000, 80, 443}  # Never allocate these
        
        # Load existing allocations if metadata exists
        if self.metadata_path and self.metadata_path.exists():
            self._load_metadata()
    
    def _load_metadata(self) -> None:
        """Load port allocations from metadata file."""
        try:
            with open(self.metadata_path, 'r') as f:
                data = json.load(f)
            
            agents = data.get('agents', {})
            for agent_id, agent_data in agents.items():
                if 'port' in agent_data:
                    self.allocated_ports[agent_id] = agent_data['port']
                    logger.info(f"Loaded port allocation: {agent_id} -> {agent_data['port']}")
        except Exception as e:
            logger.error(f"Failed to load metadata: {e}")
    
    def allocate_port(self, agent_id: str) -> int:
        """
        Allocate a port for an agent.
        
        Args:
            agent_id: Unique agent identifier
            
        Returns:
            Allocated port number
            
        Raises:
            ValueError: If no ports available in range
        """
        # Check if already allocated
        if agent_id in self.allocated_ports:
            return self.allocated_ports[agent_id]
        
        # Find next available port
        used_ports = set(self.allocated_ports.values()) | self.reserved_ports
        
        for port in range(self.start_port, self.end_port + 1):
            if port not in used_ports:
                self.allocated_ports[agent_id] = port
                logger.info(f"Allocated port {port} to agent {agent_id}")
                return port
        
        raise ValueError(f"No available ports in range {self.start_port}-{self.end_port}")
    
    def release_port(self, agent_id: str) -> Optional[int]:
        """
        Release a port allocation.
        
        Args:
            agent_id: Agent identifier
            
        Returns:
            Released port number, or None if not allocated
        """
        if agent_id in self.allocated_ports:
            port = self.allocated_ports[agent_id]
            del self.allocated_ports[agent_id]
            logger.info(f"Released port {port} from agent {agent_id}")
            return port
        return None
    
    def get_port(self, agent_id: str) -> Optional[int]:
        """Get allocated port for an agent."""
        return self.allocated_ports.get(agent_id)
    
    def is_port_available(self, port: int) -> bool:
        """Check if a port is available for allocation."""
        if port in self.reserved_ports:
            return False
        if port < self.start_port or port > self.end_port:
            return False
        return port not in self.allocated_ports.values()
    
    def get_allocated_ports(self) -> Dict[str, int]:
        """Get all current port allocations."""
        return self.allocated_ports.copy()
    
    def add_reserved_port(self, port: int) -> None:
        """Add a port to the reserved list."""
        self.reserved_ports.add(port)
        logger.info(f"Added port {port} to reserved list")