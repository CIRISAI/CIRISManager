"""
Jailbreaker service initialization.

This module provides initialization for the jailbreaker service,
which handles Discord OAuth and agent token rotation.
"""

import logging
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter

logger = logging.getLogger(__name__)


def initialize_jailbreaker(manager: Any, deployment_orchestrator: Any) -> Optional[APIRouter]:
    """
    Initialize jailbreaker service if Discord credentials are configured.

    Args:
        manager: CIRISManager instance
        deployment_orchestrator: DeploymentOrchestrator instance

    Returns:
        Jailbreaker router if configured, None otherwise
    """
    print("CRITICAL DEBUG: Before jailbreaker initialization section", flush=True)
    print("CRITICAL DEBUG: About to call logger.info", flush=True)
    logger.info("DEBUG: About to start jailbreaker initialization block")
    print("CRITICAL DEBUG: logger.info call completed", flush=True)

    # DEBUG: Log actual environment variables
    discord_client_id = os.getenv("DISCORD_CLIENT_ID")
    discord_client_secret = os.getenv("DISCORD_CLIENT_SECRET")
    print(
        f"CRITICAL DEBUG: Environment check - DISCORD_CLIENT_ID exists: {bool(discord_client_id)}",
        flush=True,
    )
    print(
        f"CRITICAL DEBUG: Environment check - DISCORD_CLIENT_SECRET exists: {bool(discord_client_secret)}",
        flush=True,
    )
    logger.info(f"DEBUG: Environment check - DISCORD_CLIENT_ID exists: {bool(discord_client_id)}")
    logger.info(
        f"DEBUG: Environment check - DISCORD_CLIENT_SECRET exists: {bool(discord_client_secret)}"
    )

    try:
        print("CRITICAL DEBUG: Entering jailbreaker try block", flush=True)
        logger.info("Starting jailbreaker initialization...")
        from ciris_manager.jailbreaker import (
            JailbreakerConfig,
            JailbreakerService,
            create_jailbreaker_routes,
        )

        print("CRITICAL DEBUG: Jailbreaker imports successful", flush=True)
        logger.info("Jailbreaker imports successful")

        # Check if Discord credentials are available
        discord_client_id = os.getenv("DISCORD_CLIENT_ID")
        discord_client_secret = os.getenv("DISCORD_CLIENT_SECRET")
        print(
            f"CRITICAL DEBUG: Discord credentials - client_id={bool(discord_client_id)}, client_secret={bool(discord_client_secret)}",
            flush=True,
        )
        logger.info(
            f"Discord credentials check: client_id={bool(discord_client_id)}, client_secret={bool(discord_client_secret)}"
        )
        logger.debug(
            f"All environment variables containing DISCORD: {[(k, '***' if 'SECRET' in k else v) for k, v in os.environ.items() if 'DISCORD' in k]}"
        )

        if discord_client_id and discord_client_secret:
            print("CRITICAL DEBUG: Discord credentials found, creating config...", flush=True)
            logger.info("Discord credentials found, creating config...")
            # Create jailbreaker config
            jailbreaker_config = JailbreakerConfig.from_env()
            print(
                f"CRITICAL DEBUG: Config created for target agent: {jailbreaker_config.target_agent_id}",
                flush=True,
            )
            logger.info(f"Config created for target agent: {jailbreaker_config.target_agent_id}")

            # Get agent directory from manager config
            agents_dir = Path(manager.config.manager.agents_directory)
            logger.info(f"Agents directory: {agents_dir}")

            # Initialize jailbreaker service
            logger.info("Creating jailbreaker service...")

            # Use the real manager instance instead of SimpleContainerManager
            # so that jailbreaker can update the agent registry service tokens
            print("CRITICAL DEBUG: Using real manager for jailbreaker", flush=True)

            jailbreaker_service = JailbreakerService(
                config=jailbreaker_config,
                agent_dir=agents_dir,
                container_manager=deployment_orchestrator,
            )
            logger.info("Jailbreaker service created")

            # Create jailbreaker routes
            logger.info("Creating jailbreaker routes...")
            jailbreaker_router = create_jailbreaker_routes(jailbreaker_service)
            logger.info("Jailbreaker routes created")

            print("CRITICAL DEBUG: Jailbreaker service initialized successfully", flush=True)
            logger.info("Jailbreaker service initialized successfully")

            return jailbreaker_router
        else:
            print(
                "CRITICAL DEBUG: Jailbreaker service not initialized - Discord credentials not configured",
                flush=True,
            )
            logger.info("Jailbreaker service not initialized - Discord credentials not configured")
            return None

    except Exception as e:
        print(f"CRITICAL DEBUG: Exception in jailbreaker initialization: {e}", flush=True)
        logger.error(f"DEBUG: Exception in jailbreaker initialization: {e}", exc_info=True)
        logger.error(f"Failed to initialize jailbreaker service: {e}", exc_info=True)
        return None
