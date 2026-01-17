"""
Wizard session management for adapter configuration.

Provides in-memory storage for wizard sessions with TTL-based expiration.
"""

import secrets
import logging
from datetime import datetime, timezone, timedelta
from threading import Lock
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Session TTL in seconds (1 hour)
SESSION_TTL_SECONDS = 3600


class WizardSession:
    """Represents an active adapter configuration wizard session."""

    def __init__(
        self,
        session_id: str,
        agent_id: str,
        adapter_type: str,
        steps: List[str],
    ):
        self.session_id = session_id
        self.agent_id = agent_id
        self.adapter_type = adapter_type
        self.created_at = datetime.now(timezone.utc)
        self.expires_at = self.created_at + timedelta(seconds=SESSION_TTL_SECONDS)
        self.steps = steps  # Ordered list of step_ids
        self.current_step_index = 0
        self.steps_completed: List[str] = []
        self.collected_data: Dict[str, Any] = {}
        self.oauth_state: Optional[str] = None  # For OAuth flow tracking

    @property
    def current_step(self) -> str:
        """Get current step ID."""
        if self.current_step_index < len(self.steps):
            return self.steps[self.current_step_index]
        return self.steps[-1]  # Return last step if past end

    @property
    def steps_remaining(self) -> List[str]:
        """Get list of remaining step IDs."""
        return self.steps[self.current_step_index :]

    @property
    def is_expired(self) -> bool:
        """Check if session has expired."""
        return datetime.now(timezone.utc) > self.expires_at

    def advance_step(self) -> bool:
        """
        Mark current step as complete and advance to next.

        Returns:
            True if advanced, False if already at last step
        """
        if self.current_step_index < len(self.steps):
            self.steps_completed.append(self.current_step)
            self.current_step_index += 1
            return True
        return False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "adapter_type": self.adapter_type,
            "current_step": self.current_step,
            "steps_completed": self.steps_completed,
            "steps_remaining": self.steps_remaining,
            "collected_data": self._mask_sensitive_data(self.collected_data),
            "expires_at": self.expires_at.isoformat(),
        }

    def _mask_sensitive_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Mask sensitive fields in collected data for API responses."""
        sensitive_keys = {"password", "secret", "token", "api_key", "client_secret"}
        masked: Dict[str, Any] = {}
        for key, value in data.items():
            if any(s in key.lower() for s in sensitive_keys):
                masked[key] = "***"
            elif isinstance(value, dict):
                masked[key] = self._mask_sensitive_data(value)
            else:
                masked[key] = value
        return masked


class WizardSessionManager:
    """
    Manages wizard sessions with in-memory storage.

    Thread-safe session creation, retrieval, and cleanup.
    """

    def __init__(self):
        self._sessions: Dict[str, WizardSession] = {}
        self._lock = Lock()
        # Index by agent_id for listing sessions
        self._by_agent: Dict[str, List[str]] = {}

    def create_session(
        self,
        agent_id: str,
        adapter_type: str,
        steps: List[str],
    ) -> WizardSession:
        """
        Create a new wizard session.

        Args:
            agent_id: Agent being configured
            adapter_type: Type of adapter being configured
            steps: Ordered list of step IDs from manifest

        Returns:
            New WizardSession
        """
        with self._lock:
            # Clean up expired sessions first
            self._cleanup_expired()

            # Generate unique session ID
            session_id = f"wiz_{secrets.token_hex(12)}"

            session = WizardSession(
                session_id=session_id,
                agent_id=agent_id,
                adapter_type=adapter_type,
                steps=steps,
            )

            self._sessions[session_id] = session

            # Index by agent
            if agent_id not in self._by_agent:
                self._by_agent[agent_id] = []
            self._by_agent[agent_id].append(session_id)

            logger.info(
                f"Created wizard session {session_id} for {adapter_type} on agent {agent_id}"
            )

            return session

    def get_session(self, session_id: str) -> Optional[WizardSession]:
        """
        Get a session by ID.

        Args:
            session_id: Session ID to retrieve

        Returns:
            WizardSession if found and not expired, None otherwise
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None

            if session.is_expired:
                self._remove_session(session_id)
                return None

            return session

    def get_sessions_for_agent(self, agent_id: str) -> List[WizardSession]:
        """
        Get all active sessions for an agent.

        Args:
            agent_id: Agent ID to get sessions for

        Returns:
            List of active WizardSessions
        """
        with self._lock:
            self._cleanup_expired()

            session_ids = self._by_agent.get(agent_id, [])
            sessions = []
            for sid in session_ids:
                session = self._sessions.get(sid)
                if session and not session.is_expired:
                    sessions.append(session)
            return sessions

    def delete_session(self, session_id: str) -> bool:
        """
        Delete a session.

        Args:
            session_id: Session ID to delete

        Returns:
            True if deleted, False if not found
        """
        with self._lock:
            return self._remove_session(session_id)

    def _remove_session(self, session_id: str) -> bool:
        """Remove a session (internal, assumes lock held)."""
        session = self._sessions.pop(session_id, None)
        if session:
            # Remove from agent index
            agent_sessions = self._by_agent.get(session.agent_id, [])
            if session_id in agent_sessions:
                agent_sessions.remove(session_id)
            return True
        return False

    def _cleanup_expired(self) -> int:
        """
        Remove all expired sessions.

        Returns:
            Number of sessions removed
        """
        expired = [sid for sid, session in self._sessions.items() if session.is_expired]
        for sid in expired:
            self._remove_session(sid)

        if expired:
            logger.debug(f"Cleaned up {len(expired)} expired wizard sessions")

        return len(expired)


# Global session manager instance
_session_manager: Optional[WizardSessionManager] = None


def get_wizard_session_manager() -> WizardSessionManager:
    """Get or create the global wizard session manager."""
    global _session_manager
    if _session_manager is None:
        _session_manager = WizardSessionManager()
    return _session_manager
