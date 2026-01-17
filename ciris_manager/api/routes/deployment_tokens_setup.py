"""
Deployment token setup.

This module provides initialization for deployment tokens,
setting up environment variables for backwards compatibility.
"""

import logging
import os
from typing import Dict

from ciris_manager.deployment_tokens import DeploymentTokenManager

logger = logging.getLogger(__name__)


def setup_deployment_tokens() -> Dict[str, str]:
    """
    Initialize deployment tokens and set environment variables.

    Creates a DeploymentTokenManager, loads or generates tokens,
    and sets them as environment variables for backwards compatibility.

    Returns:
        Dictionary mapping repo names to tokens
    """
    logger.info("Creating DeploymentTokenManager...")
    token_manager = DeploymentTokenManager()
    logger.info("DeploymentTokenManager created")

    # Load deployment tokens (auto-generates if missing)
    logger.info("Loading deployment tokens...")
    deploy_tokens = token_manager.get_all_tokens()
    logger.info("Deployment tokens loaded")

    # Set as environment variables for backwards compatibility
    for repo, token in deploy_tokens.items():
        if repo == "legacy":
            os.environ["CIRIS_DEPLOY_TOKEN"] = token
        else:
            os.environ[f"CIRIS_{repo.upper()}_DEPLOY_TOKEN"] = token

    return deploy_tokens
