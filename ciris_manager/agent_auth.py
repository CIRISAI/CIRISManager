"""
Agent authentication utilities for CIRISManager.

Handles authentication with CIRIS agents using service tokens or fallback credentials.
"""

import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)


class AgentAuth:
    """Manages authentication for agent API calls."""

    def __init__(self, agent_registry=None):
        """
        Initialize agent auth handler.

        Args:
            agent_registry: Optional agent registry instance to avoid circular imports
        """
        self.agent_registry = agent_registry
        self._encryption = None

    def get_auth_headers(self, agent_id: str) -> Dict[str, str]:
        """
        Get authentication headers for an agent.

        Args:
            agent_id: The agent identifier

        Returns:
            Dictionary with Authorization header

        Raises:
            ValueError: If no service token exists for the agent
        """
        # Try to get service token
        service_token = self._get_service_token(agent_id)

        if service_token:
            logger.debug(f"Using service token auth for {agent_id}")
            return {"Authorization": f"Bearer service:{service_token}"}
        else:
            # No fallback - agents MUST have service tokens
            error_msg = f"No service token found for agent {agent_id}. Cannot authenticate."
            logger.error(error_msg)
            raise ValueError(error_msg)

    def _get_service_token(self, agent_id: str) -> Optional[str]:
        """
        Get decrypted service token for an agent.

        Args:
            agent_id: The agent identifier

        Returns:
            Decrypted service token or None
        """
        try:
            # Get agent from registry
            if not self.agent_registry:
                # Skip if no registry provided - can't get tokens without it
                logger.debug("No agent registry available")
                return None
            else:
                registry = self.agent_registry

            registry_agent = registry.get_agent(agent_id)

            if not registry_agent:
                logger.debug(f"Agent {agent_id} not found in registry")
                return None

            # Check if agent has a service token
            if not hasattr(registry_agent, "service_token") or not registry_agent.service_token:
                logger.debug(f"Agent {agent_id} has no service token")
                return None

            # Decrypt the token
            if not self._encryption:
                from ciris_manager.crypto import get_token_encryption

                self._encryption = get_token_encryption()

            decrypted_token = self._encryption.decrypt_token(registry_agent.service_token)
            return str(decrypted_token)

        except ValueError as e:
            # Invalid token format - this is a critical error
            logger.error(f"Invalid token format for {agent_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to decrypt service token for {agent_id}: {e}")
            raise

    def verify_token(self, provided_token: str, agent_id: str) -> bool:
        """
        Verify if a provided token matches the agent's service token.

        Args:
            provided_token: Token to verify
            agent_id: The agent identifier

        Returns:
            True if token is valid
        """
        try:
            expected_token = self._get_service_token(agent_id)
            if not expected_token:
                return False

            # Use constant-time comparison to prevent timing attacks
            import hmac

            return hmac.compare_digest(provided_token, expected_token)

        except Exception as e:
            logger.error(f"Failed to verify token for {agent_id}: {e}")
            return False


# Singleton instance for easy access
_default_auth = None


def get_agent_auth(agent_registry=None) -> AgentAuth:
    """
    Get the default agent auth instance.

    Args:
        agent_registry: Optional agent registry to use

    Returns:
        AgentAuth instance
    """
    global _default_auth
    if _default_auth is None or agent_registry:
        _default_auth = AgentAuth(agent_registry)
    return _default_auth
