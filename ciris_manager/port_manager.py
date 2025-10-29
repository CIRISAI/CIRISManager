"""
Port management for CIRIS agents.

Handles dynamic port allocation and tracking for agent containers.
"""

import json
import logging
import socket
from pathlib import Path
from typing import Dict, Set, Optional

logger = logging.getLogger(__name__)


class PortManager:
    """Manages dynamic port allocation for agents."""

    def __init__(
        self, start_port: int = 8080, end_port: int = 8200, metadata_path: Optional[Path] = None
    ):
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
        if self.metadata_path is None:
            return
        try:
            with open(self.metadata_path, "r") as f:
                data = json.load(f)

            agents = data.get("agents", {})
            for key, agent_data in agents.items():
                if "port" in agent_data:
                    # Determine if this is a composite key or simple agent_id
                    if "agent_id" in agent_data:
                        # Agent has occurrence_id, use agent_id from data
                        agent_id = agent_data["agent_id"]
                    elif "server_id" in agent_data:
                        # This is a composite key format, parse it
                        # Format is "agent_id-server_id" or "agent_id-occurrence_id-server_id"
                        agent_id = self._parse_agent_id_from_key(key)
                    else:
                        # Simple agent_id (not composite key), use key as-is
                        agent_id = key

                    self.allocated_ports[agent_id] = agent_data["port"]
                    logger.info(f"Loaded port allocation: {agent_id} -> {agent_data['port']}")
        except Exception as e:
            logger.error(f"Failed to load metadata: {e}")

    @staticmethod
    def _parse_agent_id_from_key(composite_key: str) -> str:
        """Extract agent_id from composite key.

        Args:
            composite_key: Composite key in format "agent_id-server_id" or "agent_id-occurrence_id-server_id"
                         Note: agent_id itself may contain dashes (e.g., "scout1-abc123-main")

        Returns:
            The agent_id portion of the key
        """
        # For backward compatibility with old single-part keys
        if "-" not in composite_key:
            return composite_key

        # Split the composite key
        parts = composite_key.split("-")

        if len(parts) >= 3:
            # Format could be:
            # 1. "agent_id-occurrence_id-server_id" where agent_id has no dashes
            # 2. "agent-with-dashes-server_id" where agent_id has dashes
            #
            # Since we can't distinguish these cases without more context, and the most
            # common case is agents without occurrence_id (format "agent_id-server_id"),
            # we'll assume the last part is server_id and everything before is agent_id
            return "-".join(parts[:-1])
        elif len(parts) == 2:
            # Format: "simple_agent_id-server_id"
            return parts[0]
        else:
            # Single part - should not happen but return as-is
            return composite_key

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
                # Check if port is actually available on the system
                if self._is_port_in_use(port):
                    logger.warning(
                        f"Port {port} is marked as available but is in use on system, skipping"
                    )
                    continue

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

    def _is_port_in_use(self, port: int, host: str = "0.0.0.0") -> bool:
        """
        Check if a port is actually in use on the system.

        Args:
            port: Port number to check
            host: Host to check (default: 0.0.0.0 for all interfaces)

        Returns:
            True if port is in use, False if available
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((host, port))
                return False  # Port is available
            except OSError:
                return True  # Port is in use

    def get_allocated_ports(self) -> Dict[str, int]:
        """Get all current port allocations."""
        return self.allocated_ports.copy()

    def add_reserved_port(self, port: int) -> None:
        """Add a port to the reserved list."""
        self.reserved_ports.add(port)
        logger.info(f"Added port {port} to reserved list")
