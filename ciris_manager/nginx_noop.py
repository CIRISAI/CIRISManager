"""
No-op implementation of NginxManager for environments without nginx.

This module provides a null object pattern implementation that allows
CIRISManager to run without nginx integration when disabled.
"""

import logging
from typing import List

from ciris_manager.models import AgentInfo

logger = logging.getLogger(__name__)


class NoOpNginxManager:
    """
    A Null Object implementation of the NginxManager.

    It provides the same interface but performs no operations,
    allowing the application to run seamlessly without Nginx.
    """

    def __init__(self, config_dir: str = "", container_name: str = ""):
        """Initialize the no-op manager."""
        logger.info("Nginx integration is disabled. Using No-Op Nginx Manager.")

    def update_config(self, agents: List[AgentInfo]) -> bool:
        """
        Mock update_config that always succeeds.

        Args:
            agents: List of agent configurations (ignored)

        Returns:
            Always returns True
        """
        logger.debug(f"Nginx is disabled, skipping configuration update for {len(agents)} agents")
        return True

    async def update_nginx_config(self) -> bool:
        """
        Async version of update_config for compatibility.

        Returns:
            Always returns True
        """
        logger.debug("Nginx is disabled, skipping async configuration update")
        return True

    def remove_agent_routes(self, agent_id: str, agents: List[AgentInfo]) -> bool:
        """
        Mock route removal that always succeeds.

        Args:
            agent_id: ID of agent to remove (ignored)
            agents: Current list of agents (ignored)

        Returns:
            Always returns True
        """
        logger.debug(f"Nginx is disabled, skipping route removal for agent {agent_id}")
        return True

    def reload(self) -> bool:
        """
        Mock reload that always succeeds.

        Returns:
            Always returns True
        """
        logger.debug("Nginx is disabled, skipping reload")
        return True
