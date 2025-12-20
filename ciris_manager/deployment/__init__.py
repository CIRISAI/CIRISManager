"""
Deployment orchestration module.

Provides deployment management for CIRIS agents including:
- Canary deployments with phased rollouts
- Graceful agent shutdowns
- Rollback capabilities
- Version tracking

Usage:
    from ciris_manager.deployment import DeploymentOrchestrator, get_deployment_orchestrator

    # Get singleton instance
    orchestrator = get_deployment_orchestrator()

    # Or create new instance
    orchestrator = DeploymentOrchestrator(manager)
"""

# Re-export main classes from new location
from ciris_manager.deployment.orchestrator import (
    DeploymentOrchestrator,
    get_deployment_orchestrator,
)

# Export sub-module classes
from ciris_manager.deployment.containers import ContainerOperations
from ciris_manager.deployment.helpers import (
    build_version_reason,
    format_changelog_for_agent,
    get_risk_indicator,
)
from ciris_manager.deployment.state import DeploymentState, add_event

__all__ = [
    # Main orchestrator
    "DeploymentOrchestrator",
    "get_deployment_orchestrator",
    # Sub-modules
    "ContainerOperations",
    "DeploymentState",
    # Helper functions
    "add_event",
    "build_version_reason",
    "format_changelog_for_agent",
    "get_risk_indicator",
]
