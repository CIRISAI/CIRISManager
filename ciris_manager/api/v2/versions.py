"""
Versions namespace - All version tracking and history.
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any, List, Optional
from datetime import datetime
from pydantic import BaseModel

from .models import Version, FleetVersion, FleetVersions
from ..auth import get_current_user
from ...core import get_manager
from ...version_tracker import get_version_tracker
from ...docker_discovery import DockerAgentDiscovery


router = APIRouter(prefix="/versions", tags=["versions"])


class RollbackRequest(BaseModel):
    """Request to rollback to a previous version."""

    component: str  # agent/gui/nginx
    target_version: str  # Which version to rollback to
    reason: Optional[str] = None


@router.get("")
async def get_current_versions(
    _user: Dict[str, str] = Depends(get_current_user),
) -> Dict[str, Version]:
    """
    Get current versions of all components.
    """
    tracker = get_version_tracker()
    all_versions = await tracker.get_rollback_options()

    result = {}
    for component in ["agent", "gui", "nginx"]:
        if component in all_versions:
            data = all_versions[component]
            if data.get("current"):
                result[component] = Version(
                    component=component,
                    current=data["current"].get("image", "unknown"),
                    previous=data.get("n_minus_1", {}).get("image")
                    if data.get("n_minus_1")
                    else None,
                    rollback=data.get("n_minus_2", {}).get("image")
                    if data.get("n_minus_2")
                    else None,
                    deployed_at=datetime.fromisoformat(data["current"].get("deployed_at"))
                    if data["current"].get("deployed_at")
                    else datetime.utcnow(),
                    deployed_by=data["current"].get("deployed_by", "system"),
                )

    return result


@router.get("/fleet")
async def get_fleet_versions(_user: Dict[str, str] = Depends(get_current_user)) -> FleetVersions:
    """
    Get version information for all agents.
    Replaces old /agents/versions endpoint.
    """
    manager = get_manager()
    discovery = DockerAgentDiscovery(manager.agent_registry)
    agents = discovery.discover_agents()

    fleet_agents = []
    adoption: Dict[str, List[str]] = {}

    for agent in agents:
        # Get deployment from registry
        registry_agent = manager.agent_registry.get_agent(agent.agent_id)
        deployment = "CIRIS_DISCORD_PILOT"

        if registry_agent and hasattr(registry_agent, "metadata"):
            deployment = registry_agent.metadata.get("deployment", "CIRIS_DISCORD_PILOT")

        fleet_agent = FleetVersion(
            agent_id=agent.agent_id,
            agent_name=agent.agent_name,
            version=agent.version or "unknown",
            codename=agent.codename,
            code_hash=agent.code_hash,
            status=agent.status,
            deployment=deployment,
        )
        fleet_agents.append(fleet_agent)

        # Track adoption
        version_key = agent.version or "unknown"
        if version_key not in adoption:
            adoption[version_key] = []
        adoption[version_key].append(agent.agent_id)

    return FleetVersions(agents=fleet_agents, adoption=adoption, total_agents=len(agents))


@router.get("/fleet/{agent_id}")
async def get_agent_version(
    agent_id: str, _user: Dict[str, str] = Depends(get_current_user)
) -> FleetVersion:
    """
    Get version information for a specific agent.
    """
    manager = get_manager()
    discovery = DockerAgentDiscovery(manager.agent_registry)
    agents = discovery.discover_agents()

    for agent in agents:
        if agent.agent_id == agent_id:
            registry_agent = manager.agent_registry.get_agent(agent_id)
            deployment = "CIRIS_DISCORD_PILOT"

            if registry_agent and hasattr(registry_agent, "metadata"):
                deployment = registry_agent.metadata.get("deployment", "CIRIS_DISCORD_PILOT")

            return FleetVersion(
                agent_id=agent.agent_id,
                agent_name=agent.agent_name,
                version=agent.version or "unknown",
                codename=agent.codename,
                code_hash=agent.code_hash,
                status=agent.status,
                deployment=deployment,
            )

    raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")


@router.get("/{component}")
async def get_component_version(
    component: str, _user: Dict[str, str] = Depends(get_current_user)
) -> Version:
    """
    Get current version of a specific component.
    """
    if component not in ["agent", "gui", "nginx"]:
        raise HTTPException(status_code=400, detail=f"Invalid component: {component}")

    tracker = get_version_tracker()
    versions = await tracker.get_rollback_options(component)

    if not versions.get("current"):
        raise HTTPException(status_code=404, detail=f"No version info for {component}")

    return Version(
        component=component,
        current=versions["current"].get("image", "unknown"),
        previous=versions.get("n_minus_1", {}).get("image") if versions.get("n_minus_1") else None,
        rollback=versions.get("n_minus_2", {}).get("image") if versions.get("n_minus_2") else None,
        deployed_at=datetime.fromisoformat(versions["current"].get("deployed_at"))
        if versions["current"].get("deployed_at")
        else datetime.utcnow(),
        deployed_by=versions["current"].get("deployed_by", "system"),
    )


@router.get("/history")
async def get_version_history(
    limit: int = 50, _user: Dict[str, str] = Depends(get_current_user)
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Get complete version history for all components.
    """
    tracker = get_version_tracker()

    history = {}
    for component in ["agent", "gui", "nginx"]:
        component_history = await tracker.get_version_history(component, include_staged=False)
        history[component] = component_history[:limit]

    return history


@router.get("/history/{component}")
async def get_component_history(
    component: str, limit: int = 50, _user: Dict[str, str] = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    """
    Get version history for a specific component.
    """
    if component not in ["agent", "gui", "nginx"]:
        raise HTTPException(status_code=400, detail=f"Invalid component: {component}")

    tracker = get_version_tracker()
    history = await tracker.get_version_history(component, include_staged=False)

    return history[:limit]


@router.get("/rollback")
async def get_rollback_options(
    _user: Dict[str, str] = Depends(get_current_user),
) -> Dict[str, Dict[str, Any]]:
    """
    Get available rollback versions for all components.
    """
    tracker = get_version_tracker()
    options = await tracker.get_rollback_options()

    result = {}
    for component in ["agent", "gui", "nginx"]:
        if component in options:
            data = options[component]
            result[component] = {
                "current": data.get("current"),
                "options": [
                    opt for opt in [data.get("n_minus_1"), data.get("n_minus_2")] if opt is not None
                ],
            }

    return result


@router.post("/rollback")
async def execute_rollback(
    request: RollbackRequest, _user: Dict[str, str] = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Execute a version rollback.
    """
    if request.component not in ["agent", "gui", "nginx"]:
        raise HTTPException(status_code=400, detail=f"Invalid component: {request.component}")

    # Get deployment orchestrator
    from ...deployment_orchestrator import get_deployment_orchestrator

    orchestrator = get_deployment_orchestrator()

    # Create rollback deployment
    deployment_id = f"rollback-{request.component}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

    # Start rollback
    await orchestrator.start_rollback(
        deployment_id=deployment_id,
        target_version=request.target_version,
        rollback_targets={request.component: ["all"]},
        reason=request.reason or "Manual rollback via v2 API",
    )

    return {
        "status": "initiated",
        "deployment_id": deployment_id,
        "component": request.component,
        "target_version": request.target_version,
        "message": f"Rollback of {request.component} to {request.target_version} initiated",
    }
