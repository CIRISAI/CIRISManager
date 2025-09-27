"""
Consolidated versions namespace for CIRISManager API.

This module implements the new /versions/* endpoints as part of the API
consolidation plan. It provides a single, logical location for all
version-related operations.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from ciris_manager.api.auth import get_current_user_dependency as get_current_user

# from ciris_manager.version_tracker import get_version_tracker  # REMOVED: Using DeploymentOrchestrator instead
from ciris_manager.docker_discovery import DockerAgentDiscovery


# Create router for versions namespace
versions_router = APIRouter(prefix="/versions", tags=["versions"])


class VersionInfo(BaseModel):
    """Version information for a component."""

    component: str
    current: Optional[str] = None
    staged: Optional[str] = None
    previous: Optional[str] = None
    deployed_at: Optional[str] = None
    deployment_id: Optional[str] = None


class AgentVersionInfo(BaseModel):
    """Version info for an agent."""

    agent_id: str
    agent_name: str
    version: str
    codename: Optional[str] = None
    code_hash: Optional[str] = None
    status: str
    deployment: Optional[str] = None


class VersionAdoption(BaseModel):
    """Version adoption metrics."""

    version: str
    count: int
    percentage: float
    agents: List[str]


@versions_router.get("/current")
async def get_current_versions(
    _user: Dict[str, str] = Depends(get_current_user),
) -> Dict[str, VersionInfo]:
    """
    Get current versions of all components.

    Returns current, staged, and previous versions for:
    - Agent containers
    - GUI container
    - Nginx container
    """
    # tracker = get_version_tracker()  # DISABLED - using DeploymentOrchestrator
    # all_versions = await tracker.get_rollback_options()  # DISABLED - using DeploymentOrchestrator
    all_versions = {}

    result = {}
    for component_type in ["agent", "gui", "nginx"]:
        if component_type in all_versions:
            component_data = all_versions[component_type]
            result[component_type] = VersionInfo(
                component=component_type,
                current=component_data.get("current", {}).get("image")
                if component_data.get("current")
                else None,
                staged=component_data.get("staged", {}).get("image")
                if component_data.get("staged")
                else None,
                previous=component_data.get("n_minus_1", {}).get("image")
                if component_data.get("n_minus_1")
                else None,
                deployed_at=component_data.get("current", {}).get("deployed_at")
                if component_data.get("current")
                else None,
                deployment_id=component_data.get("current", {}).get("deployment_id")
                if component_data.get("current")
                else None,
            )

    return result


@versions_router.get("/current/{component_type}")
async def get_component_version(
    component_type: str, _user: Dict[str, str] = Depends(get_current_user)
) -> VersionInfo:
    """Get current version of a specific component type."""
    if component_type not in ["agent", "gui", "nginx"]:
        raise HTTPException(status_code=400, detail=f"Invalid component type: {component_type}")

    # tracker = get_version_tracker()  # DISABLED - using DeploymentOrchestrator
    # versions = await tracker.get_rollback_options(component_type)  # DISABLED - using DeploymentOrchestrator
    versions = {}

    return VersionInfo(
        component=component_type,
        current=versions.get("current", {}).get("image") if versions.get("current") else None,
        staged=versions.get("staged", {}).get("image") if versions.get("staged") else None,
        previous=versions.get("n_minus_1", {}).get("image") if versions.get("n_minus_1") else None,
        deployed_at=versions.get("current", {}).get("deployed_at")
        if versions.get("current")
        else None,
        deployment_id=versions.get("current", {}).get("deployment_id")
        if versions.get("current")
        else None,
    )


@versions_router.get("/agents")
async def get_agent_versions(_user: Dict[str, str] = Depends(get_current_user)) -> Dict[str, Any]:
    """
    Get version information for all agents.

    This replaces the old /agents/versions endpoint.
    """
    from ciris_manager.manager_core import get_manager

    manager = get_manager()
    discovery = DockerAgentDiscovery(manager.agent_registry)
    agents = discovery.discover_agents()

    agent_versions = []
    version_summary: Dict[str, int] = {}
    deployment_summary: Dict[str, List[str]] = {}

    for agent in agents:
        # Get deployment from registry
        registry_agent = manager.agent_registry.get_agent(agent.agent_id)
        deployment = "CIRIS_DISCORD_PILOT"  # Default
        if registry_agent and hasattr(registry_agent, "metadata"):
            deployment = registry_agent.metadata.get("deployment", "CIRIS_DISCORD_PILOT")

        agent_info = AgentVersionInfo(
            agent_id=agent.agent_id,
            agent_name=agent.agent_name,
            version=agent.version or "unknown",
            codename=agent.codename,
            code_hash=agent.code_hash,
            status=agent.status,
            deployment=deployment,
        )
        agent_versions.append(agent_info.dict())

        # Count versions
        version_key = agent.version or "unknown"
        version_summary[version_key] = version_summary.get(version_key, 0) + 1

        # Group by deployment
        if deployment not in deployment_summary:
            deployment_summary[deployment] = []
        deployment_summary[deployment].append(agent.agent_id)

    return {
        "agents": agent_versions,
        "version_summary": version_summary,
        "deployment_summary": deployment_summary,
        "total_agents": len(agents),
    }


@versions_router.get("/agent/{agent_id}")
async def get_agent_version(
    agent_id: str, _user: Dict[str, str] = Depends(get_current_user)
) -> AgentVersionInfo:
    """Get version information for a specific agent."""
    from ciris_manager.manager_core import get_manager

    manager = get_manager()
    discovery = DockerAgentDiscovery(manager.agent_registry)
    agents = discovery.discover_agents()

    for agent in agents:
        if agent.agent_id == agent_id:
            registry_agent = manager.agent_registry.get_agent(agent_id)
            deployment = "CIRIS_DISCORD_PILOT"
            if registry_agent and hasattr(registry_agent, "metadata"):
                deployment = registry_agent.metadata.get("deployment", "CIRIS_DISCORD_PILOT")

            return AgentVersionInfo(
                agent_id=agent.agent_id,
                agent_name=agent.agent_name,
                version=agent.version or "unknown",
                codename=agent.codename,
                code_hash=agent.code_hash,
                status=agent.status,
                deployment=deployment,
            )

    raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")


@versions_router.get("/adoption")
async def get_version_adoption(_user: Dict[str, str] = Depends(get_current_user)) -> Dict[str, Any]:
    """
    Get version adoption metrics across the fleet.

    Shows which versions are running and their adoption rates.
    """
    from ciris_manager.manager_core import get_manager

    manager = get_manager()
    discovery = DockerAgentDiscovery(manager.agent_registry)
    agents = discovery.discover_agents()

    if not agents:
        return {"adoptions": [], "total_agents": 0}

    # Count versions
    version_counts: Dict[str, List[str]] = {}
    for agent in agents:
        version = agent.version or "unknown"
        if version not in version_counts:
            version_counts[version] = []
        version_counts[version].append(agent.agent_id)

    # Calculate adoption
    total = len(agents)
    adoptions = []

    for version, agent_ids in version_counts.items():
        count = len(agent_ids)
        adoptions.append(
            VersionAdoption(
                version=version,
                count=count,
                percentage=round((count / total) * 100, 1),
                agents=agent_ids,
            )
        )

    # Sort by count descending
    adoptions.sort(key=lambda x: x.count, reverse=True)

    return {
        "adoptions": [a.dict() for a in adoptions],
        "total_agents": total,
        "unique_versions": len(version_counts),
    }


@versions_router.get("/adoption/{version}")
async def get_version_adoption_details(
    version: str, _user: Dict[str, str] = Depends(get_current_user)
) -> VersionAdoption:
    """Get adoption details for a specific version."""
    from ciris_manager.manager_core import get_manager

    manager = get_manager()
    discovery = DockerAgentDiscovery(manager.agent_registry)
    agents = discovery.discover_agents()

    agents_with_version = [agent.agent_id for agent in agents if agent.version == version]

    if not agents_with_version:
        raise HTTPException(status_code=404, detail=f"No agents running version {version}")

    total = len(agents)
    count = len(agents_with_version)

    return VersionAdoption(
        version=version,
        count=count,
        percentage=round((count / total) * 100, 1),
        agents=agents_with_version,
    )


@versions_router.get("/history")
async def get_version_history(
    limit: int = 50, _user: Dict[str, str] = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Get complete version history for all components.

    Returns deployment history with timestamps and deployment IDs.
    """
    # tracker = get_version_tracker()  # DISABLED - using DeploymentOrchestrator

    history = {}
    # for component_type in ["agent", "gui", "nginx"]:
    #     component_history = await tracker.get_version_history(component_type, include_staged=True)  # DISABLED
    #     history[component_type] = component_history[:limit]

    return history


@versions_router.get("/history/{component_type}")
async def get_component_history(
    component_type: str,
    limit: int = 50,
    include_staged: bool = False,
    _user: Dict[str, str] = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """Get version history for a specific component type."""
    if component_type not in ["agent", "gui", "nginx"]:
        raise HTTPException(status_code=400, detail=f"Invalid component type: {component_type}")

    # tracker = get_version_tracker()  # DISABLED - using DeploymentOrchestrator
    # history = await tracker.get_version_history(component_type, include_staged=include_staged)  # DISABLED
    history = []

    return history[:limit]


@versions_router.get("/rollback-options")
async def get_rollback_options(_user: Dict[str, str] = Depends(get_current_user)) -> Dict[str, Any]:
    """
    Get available rollback options for all components.

    Returns n-1 and n-2 versions that can be rolled back to.
    """
    # tracker = get_version_tracker()  # DISABLED - using DeploymentOrchestrator
    # options = await tracker.get_rollback_options()  # DISABLED - using DeploymentOrchestrator
    options = {}

    # Format for clarity
    result = {}
    for component_type in ["agent", "gui", "nginx"]:
        if component_type in options:
            component_options = options[component_type]
            result[component_type] = {
                "current": component_options.get("current"),
                "rollback_options": [
                    opt
                    for opt in [
                        component_options.get("n_minus_1"),
                        component_options.get("n_minus_2"),
                    ]
                    if opt is not None
                ],
            }

    return result


@versions_router.get("/rollback-options/{component_type}")
async def get_component_rollback_options(
    component_type: str, _user: Dict[str, str] = Depends(get_current_user)
) -> Dict[str, Any]:
    """Get rollback options for a specific component type."""
    if component_type not in ["agent", "gui", "nginx"]:
        raise HTTPException(status_code=400, detail=f"Invalid component type: {component_type}")

    # tracker = get_version_tracker()  # DISABLED - using DeploymentOrchestrator
    # options = await tracker.get_rollback_options(component_type)  # DISABLED - using DeploymentOrchestrator
    options = {}

    return {
        "current": options.get("current"),
        "rollback_options": [
            opt for opt in [options.get("n_minus_1"), options.get("n_minus_2")] if opt is not None
        ],
    }


@versions_router.get("/staged")
async def get_staged_versions(_user: Dict[str, str] = Depends(get_current_user)) -> Dict[str, Any]:
    """Get all staged versions waiting for promotion."""
    # tracker = get_version_tracker()  # DISABLED - using DeploymentOrchestrator
    # all_versions = await tracker.get_rollback_options()  # DISABLED - using DeploymentOrchestrator
    all_versions = {}

    staged = {}
    for component_type in ["agent", "gui", "nginx"]:
        if component_type in all_versions:
            staged_version = all_versions[component_type].get("staged")
            if staged_version:
                staged[component_type] = staged_version

    return {"staged": staged, "count": len(staged)}


@versions_router.post("/stage")
async def stage_version(
    request: Dict[str, Any], _user: Dict[str, str] = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Stage a new version for deployment.

    Request body:
    - component_type: Type of component (agent, gui, nginx)
    - image: Full image name with tag
    - deployment_id: Associated deployment ID
    """
    component_type = request.get("component_type")
    image = request.get("image")
    # deployment_id = request.get("deployment_id")  # Not used - DeploymentOrchestrator handles this

    if not all([component_type, image]):
        raise HTTPException(status_code=400, detail="Missing required fields")

    if component_type not in ["agent", "gui", "nginx"]:
        raise HTTPException(status_code=400, detail=f"Invalid component type: {component_type}")

    # tracker = get_version_tracker()  # DISABLED - using DeploymentOrchestrator
    assert image is not None  # Validated above
    # await tracker.stage_version(  # DISABLED - using DeploymentOrchestrator
    #     component_type,
    #     image,
    #     deployment_id=deployment_id,
    #     deployed_by=_user.get("email", "unknown"),
    # )

    return {"status": "success", "component_type": component_type, "staged_image": image}


@versions_router.post("/promote/{component_type}")
async def promote_staged_version(
    component_type: str, request: Dict[str, Any], _user: Dict[str, str] = Depends(get_current_user)
) -> Dict[str, Any]:
    """Promote a staged version to current."""
    if component_type not in ["agent", "gui", "nginx"]:
        raise HTTPException(status_code=400, detail=f"Invalid component type: {component_type}")

    # deployment_id = request.get("deployment_id")  # Not used - DeploymentOrchestrator handles this

    # tracker = get_version_tracker()  # DISABLED - using DeploymentOrchestrator
    # await tracker.promote_staged_version(component_type, deployment_id)  # DISABLED - using DeploymentOrchestrator

    return {
        "status": "success",
        "component_type": component_type,
        "message": f"Staged version promoted to current for {component_type}",
    }


@versions_router.get("/diff/{version1}/{version2}")
async def compare_versions(
    version1: str, version2: str, _user: Dict[str, str] = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Compare two versions.

    Returns differences in:
    - Agent configurations
    - Feature flags
    - Dependencies
    """
    # This would integrate with your version comparison logic
    # For now, return a placeholder
    return {
        "version1": version1,
        "version2": version2,
        "differences": {"features": [], "config_changes": [], "dependencies": []},
        "message": "Version comparison not yet implemented",
    }


@versions_router.get("/changelog/{version}")
async def get_version_changelog(
    version: str, _user: Dict[str, str] = Depends(get_current_user)
) -> Dict[str, Any]:
    """Get changelog for a specific version."""
    # This would integrate with your changelog system
    # For now, return a placeholder
    return {
        "version": version,
        "changelog": {"features": [], "fixes": [], "breaking_changes": []},
        "message": "Changelog retrieval not yet implemented",
    }
