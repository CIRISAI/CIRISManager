"""
Agents namespace - Agent lifecycle and configuration.
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Dict, Any, List, Optional
from pydantic import BaseModel

from .models import Agent
from ciris_manager.api.auth import get_current_user_dependency as get_current_user
from ciris_manager.manager_core import get_manager
from ciris_manager.docker_discovery import DockerAgentDiscovery


router = APIRouter(prefix="/agents", tags=["agents"])


class CreateAgentRequest(BaseModel):
    """Request to create a new agent."""

    name: str
    template: str
    deployment: str = "CIRIS_DISCORD_PILOT"
    environment: Optional[Dict[str, str]] = None


class AgentConfig(BaseModel):
    """Agent configuration update."""

    environment: Optional[Dict[str, str]] = None
    deployment: Optional[str] = None


@router.get("")
async def list_agents(
    deployment: Optional[str] = Query(None, description="Filter by deployment"),
    template: Optional[str] = Query(None, description="Filter by template"),
    status: Optional[str] = Query(None, description="Filter by status"),
    _user: Dict[str, str] = Depends(get_current_user),
) -> List[Agent]:
    """
    List all agents with optional filters.
    """
    manager = get_manager()
    discovery = DockerAgentDiscovery(manager.agent_registry)
    agents = discovery.discover_agents()

    # Convert to clean Agent models
    result = []
    for agent in agents:
        # Get deployment from registry
        registry_agent = manager.agent_registry.get_agent(agent.agent_id)
        deployment_value = "CIRIS_DISCORD_PILOT"
        template_value = agent.template

        if registry_agent:
            if hasattr(registry_agent, "metadata"):
                deployment_value = registry_agent.metadata.get("deployment", "CIRIS_DISCORD_PILOT")
            if hasattr(registry_agent, "template"):
                template_value = registry_agent.template

        clean_agent = Agent(
            agent_id=agent.agent_id,
            name=agent.agent_name,
            container_name=agent.container_name,
            template=template_value,
            deployment=deployment_value,
            status=agent.status,
            port=agent.api_port or 0,
            health=agent.health or "unknown",
        )
        result.append(clean_agent)

    # Apply filters
    if deployment:
        result = [a for a in result if a.deployment == deployment]
    if template:
        result = [a for a in result if a.template == template]
    if status:
        result = [a for a in result if a.status == status]

    return result


@router.post("")
async def create_agent(
    request: CreateAgentRequest, _user: Dict[str, str] = Depends(get_current_user)
) -> Agent:
    """
    Create a new agent.
    """
    manager = get_manager()

    # Create agent
    result = await manager.create_agent(
        template=request.template, name=request.name, environment=request.environment
    )

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to create agent"))

    # Set deployment
    agent_id = result["agent_id"]
    manager.agent_registry.set_deployment(agent_id, request.deployment)

    # Return created agent
    return Agent(
        agent_id=agent_id,
        name=request.name,
        container_name=result.get("container_name", f"ciris-agent-{agent_id}"),
        template=request.template,
        deployment=request.deployment,
        status="starting",
        port=result.get("port", 0),
        health="unknown",
    )


@router.get("/{agent_id}")
async def get_agent(agent_id: str, _user: Dict[str, str] = Depends(get_current_user)) -> Agent:
    """
    Get specific agent by ID.
    """
    manager = get_manager()
    discovery = DockerAgentDiscovery(manager.agent_registry)
    agents = discovery.discover_agents()

    for agent in agents:
        if agent.agent_id == agent_id:
            registry_agent = manager.agent_registry.get_agent(agent_id)
            deployment = "CIRIS_DISCORD_PILOT"
            template = agent.template

            if registry_agent:
                if hasattr(registry_agent, "metadata"):
                    deployment = registry_agent.metadata.get("deployment", "CIRIS_DISCORD_PILOT")
                if hasattr(registry_agent, "template"):
                    template = registry_agent.template

            return Agent(
                agent_id=agent.agent_id,
                name=agent.agent_name,
                container_name=agent.container_name,
                template=template,
                deployment=deployment,
                status=agent.status,
                port=agent.api_port or 0,
                health=agent.health or "unknown",
            )

    raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: str, _user: Dict[str, str] = Depends(get_current_user)
) -> Dict[str, str]:
    """
    Delete an agent.
    """
    manager = get_manager()

    # Stop and remove agent
    result = await manager.remove_agent(agent_id)

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to delete agent"))

    return {"status": "deleted", "agent_id": agent_id}


@router.post("/{agent_id}/start")
async def start_agent(
    agent_id: str, _user: Dict[str, str] = Depends(get_current_user)
) -> Dict[str, str]:
    """
    Start an agent.
    """
    try:
        import docker

        client = docker.from_env()

        # Find container
        container_name = f"ciris-agent-{agent_id}"
        container = client.containers.get(container_name)
        container.start()

        return {"status": "started", "agent_id": agent_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{agent_id}/stop")
async def stop_agent(
    agent_id: str, _user: Dict[str, str] = Depends(get_current_user)
) -> Dict[str, str]:
    """
    Stop an agent.
    """
    try:
        import docker

        client = docker.from_env()

        # Find container
        container_name = f"ciris-agent-{agent_id}"
        container = client.containers.get(container_name)
        container.stop()

        return {"status": "stopped", "agent_id": agent_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{agent_id}/restart")
async def restart_agent(
    agent_id: str, _user: Dict[str, str] = Depends(get_current_user)
) -> Dict[str, str]:
    """
    Restart an agent.
    """
    try:
        import docker

        client = docker.from_env()

        # Find container
        container_name = f"ciris-agent-{agent_id}"
        container = client.containers.get(container_name)
        container.restart()

        return {"status": "restarted", "agent_id": agent_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{agent_id}/config")
async def get_agent_config(
    agent_id: str, _user: Dict[str, str] = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Get agent configuration.
    """
    manager = get_manager()
    registry_agent = manager.agent_registry.get_agent(agent_id)

    if not registry_agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    config = {
        "agent_id": agent_id,
        "name": registry_agent.name,
        "template": registry_agent.template,
        "port": registry_agent.port,
        "deployment": "CIRIS_DISCORD_PILOT",
    }

    if hasattr(registry_agent, "metadata"):
        config["deployment"] = registry_agent.metadata.get("deployment", "CIRIS_DISCORD_PILOT")
        config["metadata"] = registry_agent.metadata

    return config


@router.patch("/{agent_id}/config")
async def update_agent_config(
    agent_id: str, config: AgentConfig, _user: Dict[str, str] = Depends(get_current_user)
) -> Dict[str, str]:
    """
    Update agent configuration.
    """
    manager = get_manager()

    # Update deployment if provided
    if config.deployment:
        manager.agent_registry.set_deployment(agent_id, config.deployment)

    # Update environment if provided (would require container restart)
    if config.environment:
        # This would update the docker-compose and restart
        pass  # TODO: Implement environment update

    return {"status": "updated", "agent_id": agent_id}


@router.post("/{agent_id}/oauth")
async def setup_oauth(
    agent_id: str, _user: Dict[str, str] = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Setup OAuth for an agent.
    """
    # Simplified OAuth setup
    return {
        "status": "configured",
        "agent_id": agent_id,
        "oauth_url": f"https://agents.ciris.ai/oauth/authorize?agent={agent_id}",
    }


@router.delete("/{agent_id}/oauth")
async def remove_oauth(
    agent_id: str, _user: Dict[str, str] = Depends(get_current_user)
) -> Dict[str, str]:
    """
    Remove OAuth configuration from an agent.
    """
    return {"status": "removed", "agent_id": agent_id}
