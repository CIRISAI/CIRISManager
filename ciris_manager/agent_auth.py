"""
Agent authentication utilities for CIRISManager.

Handles authentication with CIRIS agents using service tokens or fallback credentials.
"""

import logging
import time
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
        # Cache for auth format preferences: agent_id -> "service" or "raw"
        self._auth_format_cache = {}
        # Backoff tracking: agent_id -> {"failures": int, "last_failure": float, "backoff_until": float, "circuit_open": bool}
        self._auth_backoff = {}
        # Circuit breaker threshold - stop trying after this many failures
        self.circuit_breaker_threshold = 10

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
            # Use cached format preference if available
            if agent_id in self._auth_format_cache:
                auth_format = self._auth_format_cache[agent_id]
                if auth_format == "service":
                    logger.debug(f"Using cached service token auth for {agent_id}")
                    return {"Authorization": f"Bearer service:{service_token}"}
                elif auth_format == "raw":
                    logger.debug(f"Using cached raw token auth for {agent_id}")
                    return {"Authorization": f"Bearer {service_token}"}

            # No cached preference - default to service format (works for 5/6 agents)
            logger.debug(f"Using default service token auth for {agent_id}")
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

    def detect_auth_format(self, agent_id: str) -> Optional[str]:
        """
        Detect which authentication format an agent prefers and cache it.

        Tests both "service:" prefixed and raw token formats to determine
        which one the agent accepts. Respects exponential backoff for failed attempts.

        Args:
            agent_id: The agent identifier

        Returns:
            "service" if agent prefers service: prefix, "raw" if raw token, None if neither works
        """
        # Check if we should skip due to backoff
        if self._should_skip_auth_attempt(agent_id):
            return None
        # Get the agent's port and token
        service_token = self._get_service_token(agent_id)
        if not service_token:
            logger.warning(f"No service token for {agent_id} - cannot detect auth format")
            return None

        # Get agent port from registry
        if not self.agent_registry:
            logger.warning(f"No registry available - cannot detect auth format for {agent_id}")
            return None

        registry_agent = self.agent_registry.get_agent(agent_id)
        if not registry_agent or not hasattr(registry_agent, "port"):
            logger.warning(f"Agent {agent_id} not found in registry or missing port")
            return None

        port = registry_agent.port
        url = f"http://localhost:{port}/v1/agent/status"

        try:
            import httpx

            # Test service: prefix format first (preferred format)
            headers_service = {"Authorization": f"Bearer service:{service_token}"}
            try:
                with httpx.Client(timeout=2.0) as client:
                    response = client.get(url, headers=headers_service)
                    if response.status_code == 200:
                        logger.info(f"Agent {agent_id} accepts service: prefix format")
                        self._auth_format_cache[agent_id] = "service"
                        self._record_auth_success(agent_id)
                        return "service"
            except Exception as e:
                logger.debug(f"Service prefix test failed for {agent_id}: {e}")

            # Test raw token format
            headers_raw = {"Authorization": f"Bearer {service_token}"}
            try:
                with httpx.Client(timeout=2.0) as client:
                    response = client.get(url, headers=headers_raw)
                    if response.status_code == 200:
                        logger.info(f"Agent {agent_id} accepts raw token format")
                        self._auth_format_cache[agent_id] = "raw"
                        self._record_auth_success(agent_id)
                        return "raw"
            except Exception as e:
                logger.debug(f"Raw token test failed for {agent_id}: {e}")

            # Both formats failed - record failure and trigger backoff
            logger.warning(f"Neither auth format works for {agent_id}")
            self._record_auth_failure(agent_id)
            return None

        except Exception as e:
            logger.error(f"Failed to detect auth format for {agent_id}: {e}")
            return None

    def _should_skip_auth_attempt(self, agent_id: str) -> bool:
        """
        Check if we should skip authentication attempt due to backoff or circuit breaker.

        Args:
            agent_id: The agent identifier

        Returns:
            True if we should skip the auth attempt due to backoff or circuit breaker
        """
        if agent_id not in self._auth_backoff:
            return False

        backoff_info = self._auth_backoff[agent_id]

        # Check circuit breaker - permanently stop trying after threshold
        if backoff_info.get("circuit_open", False):
            logger.debug(f"Skipping auth attempt for {agent_id} - circuit breaker open")
            return True

        current_time = time.time()

        # Check if we're still in backoff period
        if current_time < backoff_info.get("backoff_until", 0):
            time_remaining = backoff_info["backoff_until"] - current_time
            logger.debug(
                f"Skipping auth attempt for {agent_id} - backoff active for {time_remaining:.1f}s"
            )
            return True

        return False

    def _record_auth_failure(self, agent_id: str) -> None:
        """
        Record an authentication failure and update backoff timing.

        Uses exponential backoff: 30s, 1m, 2m, 4m, 8m, max 15m

        Args:
            agent_id: The agent identifier
        """
        current_time = time.time()

        if agent_id not in self._auth_backoff:
            self._auth_backoff[agent_id] = {
                "failures": 0,
                "last_failure": 0,
                "backoff_until": 0,
                "circuit_open": False,
            }

        backoff_info = self._auth_backoff[agent_id]
        backoff_info["failures"] += 1
        backoff_info["last_failure"] = current_time

        # Exponential backoff: 30s, 1m, 2m, 4m, 8m, max 15m
        failure_count = backoff_info["failures"]
        if failure_count == 1:
            backoff_seconds = 30  # 30 seconds
        elif failure_count == 2:
            backoff_seconds = 60  # 1 minute
        elif failure_count <= 5:
            backoff_seconds = min(60 * (2 ** (failure_count - 2)), 900)  # 2m, 4m, 8m, max 15m
        else:
            backoff_seconds = 900  # Cap at 15 minutes

        backoff_info["backoff_until"] = current_time + backoff_seconds

        # Check if we should open the circuit breaker
        if failure_count >= self.circuit_breaker_threshold:
            backoff_info["circuit_open"] = True
            logger.error(
                f"Circuit breaker OPEN for {agent_id} after {failure_count} failures - "
                f"will stop attempting authentication until manual intervention"
            )
        else:
            logger.warning(
                f"Auth failure #{failure_count} for {agent_id} - backing off for {backoff_seconds}s "
                f"(until {time.strftime('%H:%M:%S', time.localtime(backoff_info['backoff_until']))})"
            )

    def _record_auth_success(self, agent_id: str) -> None:
        """
        Record successful authentication and clear backoff.

        Args:
            agent_id: The agent identifier
        """
        if agent_id in self._auth_backoff:
            failures = self._auth_backoff[agent_id].get("failures", 0)
            if failures > 0:
                logger.info(
                    f"Auth recovered for {agent_id} after {failures} failures - clearing backoff"
                )
            del self._auth_backoff[agent_id]

    def reset_circuit_breaker(self, agent_id: str) -> bool:
        """
        Manually reset the circuit breaker for an agent.

        Args:
            agent_id: The agent identifier

        Returns:
            True if circuit breaker was reset, False if it wasn't open
        """
        if agent_id in self._auth_backoff and self._auth_backoff[agent_id].get(
            "circuit_open", False
        ):
            logger.info(f"Manually resetting circuit breaker for {agent_id}")
            del self._auth_backoff[agent_id]
            # Also clear auth format cache to force re-detection
            if agent_id in self._auth_format_cache:
                del self._auth_format_cache[agent_id]
            return True
        return False

    def get_backoff_status(self, agent_id: str) -> Dict[str, any]:
        """
        Get current backoff/circuit breaker status for an agent.

        Args:
            agent_id: The agent identifier

        Returns:
            Dictionary with status information
        """
        if agent_id not in self._auth_backoff:
            return {"status": "healthy", "failures": 0}

        backoff_info = self._auth_backoff[agent_id]
        current_time = time.time()

        status = {
            "failures": backoff_info["failures"],
            "circuit_open": backoff_info.get("circuit_open", False),
            "last_failure": backoff_info.get("last_failure", 0),
        }

        if backoff_info.get("circuit_open", False):
            status["status"] = "circuit_open"
        elif current_time < backoff_info.get("backoff_until", 0):
            status["status"] = "backing_off"
            status["backoff_until"] = backoff_info["backoff_until"]
            status["time_remaining"] = backoff_info["backoff_until"] - current_time
        else:
            status["status"] = "ready_to_retry"

        return status


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
