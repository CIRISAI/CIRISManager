"""
Modular API routes for CIRISManager.

This package contains route modules organized by domain:
- agents: Agent lifecycle management (start, stop, restart, logs)
- config: Agent configuration
- templates: Template management
- deployment: Update/deployment orchestration
- adapters: Adapter management and configuration
- system: Health, status endpoints
- infrastructure: Ports, tokens
- gui: Manager UI serving
- jailbreaker: Discord OAuth and token rotation
"""

import logging
from typing import Any

from fastapi import APIRouter

# Re-export items that tests patch for backward compatibility
from ciris_manager.deployment import DeploymentOrchestrator

# Modular route modules
from . import system
from . import templates
from . import infrastructure
from . import agents
from . import config
from . import oauth
from . import deployment
from . import adapters
from . import gui
from .jailbreaker import initialize_jailbreaker
from .deployment_tokens_setup import setup_deployment_tokens

logger = logging.getLogger(__name__)

__all__ = [
    "create_routes",
    "DeploymentOrchestrator",
    "system",
    "templates",
    "infrastructure",
    "agents",
    "config",
    "oauth",
    "deployment",
    "adapters",
    "gui",
]


def create_routes(manager: Any) -> APIRouter:
    """
    Create API routes with manager instance.

    Assembles all modular route files and initializes services.

    Args:
        manager: CIRISManager instance

    Returns:
        Configured APIRouter with all routes
    """
    import time

    start_time = time.time()
    logger.info("create_routes() starting...")
    router = APIRouter()

    # Initialize deployment orchestrator
    logger.info(f"[{time.time() - start_time:.2f}s] Creating DeploymentOrchestrator...")
    deployment_orchestrator = DeploymentOrchestrator(manager)
    logger.info(f"[{time.time() - start_time:.2f}s] DeploymentOrchestrator created successfully")

    # Setup deployment tokens
    logger.info(f"[{time.time() - start_time:.2f}s] Setting up deployment tokens...")
    setup_deployment_tokens()
    logger.info(f"[{time.time() - start_time:.2f}s] Deployment tokens configured")

    # Include all modular routes
    # These use Depends(get_manager) to access manager via app.state
    router.include_router(system.router, prefix="", tags=["system"])
    router.include_router(templates.router, prefix="", tags=["templates"])
    router.include_router(infrastructure.router, prefix="", tags=["infrastructure"])
    router.include_router(agents.router, prefix="", tags=["agents"])
    router.include_router(config.router, prefix="", tags=["config"])
    router.include_router(oauth.router, prefix="", tags=["oauth"])
    router.include_router(deployment.router, prefix="", tags=["deployment"])
    router.include_router(adapters.router, prefix="", tags=["adapters"])
    router.include_router(gui.router, prefix="", tags=["gui"])

    # Add debug routes for querying agent persistence
    try:
        from ciris_manager.api.debug_routes import create_debug_routes

        debug_router = create_debug_routes(manager)
        router.include_router(debug_router, prefix="", tags=["debug"])
        logger.info("Debug routes added for agent persistence querying")
    except Exception as e:
        logger.warning(f"Failed to initialize debug routes: {e}")

    # Initialize jailbreaker service if configured
    jailbreaker_router = initialize_jailbreaker(manager, deployment_orchestrator)
    if jailbreaker_router:
        router.include_router(jailbreaker_router, prefix="", tags=["jailbreaker"])
        logger.info("Jailbreaker routes added")

    return router
