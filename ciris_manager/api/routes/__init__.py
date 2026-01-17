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
"""

from typing import Any

from fastapi import APIRouter

# Import the base create_routes from routes_v1 (still has most routes)
from ciris_manager.api.routes_v1 import create_routes as _create_routes_v1

# Re-export items that tests patch for backward compatibility
from ciris_manager.deployment import DeploymentOrchestrator

# Modular route modules (imported as they are created)
from . import system
from . import templates
from . import infrastructure
from . import agents
from . import config
from . import oauth
from . import deployment
from . import adapters

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
]


def create_routes(manager: Any) -> APIRouter:
    """
    Create API routes with manager instance.

    Assembles routes from both routes_v1 (legacy) and modular route files.

    Args:
        manager: CIRISManager instance

    Returns:
        Configured APIRouter with all routes
    """
    # Get base router from routes_v1 (still has most routes defined in closure)
    router = _create_routes_v1(manager)

    # Include modular routes that have been extracted
    # These use Depends(get_manager) to access manager via app.state
    router.include_router(deployment.router, prefix="", tags=["deployment"])
    router.include_router(adapters.router, prefix="", tags=["adapters"])

    return router
