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

# Re-export from routes_v1 for backward compatibility during modularization
# Once modularization is complete, create_routes will be defined here
from ciris_manager.api.routes_v1 import create_routes

# Re-export items that tests patch for backward compatibility
from ciris_manager.deployment import DeploymentOrchestrator

__all__ = ["create_routes", "DeploymentOrchestrator"]

# Modular route modules (imported as they are created)
from . import system
from . import templates
from . import infrastructure

# More modules to come:
# from . import agents
# from . import config
# from . import oauth
# from . import deployment
# from . import adapters
