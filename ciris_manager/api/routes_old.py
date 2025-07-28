"""
CIRISManager API routes for agent discovery and management.
"""
from fastapi import APIRouter, HTTPException, Depends, Header
from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field
import docker
import yaml
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/manager/v1", tags=["CIRISManager"])


# --- Schemas ---

class AgentInfo(BaseModel):
    """Information about a running CIRIS agent."""
    agent_id: str = Field(..., description="Unique agent identifier")
    agent_name: str = Field(..., description="Human-friendly agent name")
    container_name: str = Field(..., description="Docker container name")
    status: str = Field(..., description="Container status (running, exited, etc)")
    health: Optional[str] = Field(None, description="Health check status if available")
    api_endpoint: Optional[str] = Field(None, description="API endpoint if exposed")
    created_at: datetime = Field(..., description="Container creation time")
    started_at: Optional[datetime] = Field(None, description="Container start time")
    exit_code: Optional[int] = Field(None, description="Exit code if container stopped")
    update_available: bool = Field(False, description="Whether a newer image is available")
    
    
class AgentCreationRequest(BaseModel):
    """Request to create a new CIRIS agent."""
    agent_name: str = Field(..., description="Name for the new agent")
    agent_type: str = Field(default="standard", description="Type of agent to create")
    adapters: List[str] = Field(default=["api"], description="Adapters to enable")
    environment: Dict[str, str] = Field(default_factory=dict, description="Environment variables")
    wa_signature: Optional[str] = Field(None, description="WA signature authorizing creation")
    

class UpdateNotification(BaseModel):
    """Notification that an update is available."""
    agent_id: str = Field(..., description="Agent to notify")
    new_version: str = Field(..., description="New version available")
    changelog: Optional[str] = Field(None, description="What's new in this version")
    urgency: str = Field(default="normal", description="Update urgency: low, normal, high, critical")
    

class DeploymentStatus(BaseModel):
    """Status of a deployment operation."""
    agent_id: str = Field(..., description="Agent being deployed")
    status: str = Field(..., description="Deployment status")
    message: str = Field(..., description="Status message")
    staged_container: Optional[str] = Field(None, description="Name of staged container if any")
    consent_status: Optional[str] = Field(None, description="Agent consent status")


# --- Helper Functions ---

def get_docker_client():
    """Get Docker client instance."""
    try:
        return docker.from_env()
    except Exception as e:
        logger.error(f"Failed to connect to Docker: {e}")
        raise HTTPException(status_code=500, detail="Docker connection failed")


def get_agent_info(container) -> AgentInfo:
    """Extract agent info from Docker container."""
    labels = container.labels
    attrs = container.attrs
    
    # Extract agent metadata from labels/environment
    env_dict = {}
    for env_var in attrs.get('Config', {}).get('Env', []):
        if '=' in env_var:
            key, value = env_var.split('=', 1)
            env_dict[key] = value
    
    # Determine API endpoint
    api_endpoint = None
    if 'api' in container.name and container.status == 'running':
        # Check port mapping
        ports = attrs.get('NetworkSettings', {}).get('Ports', {})
        if '8080/tcp' in ports and ports['8080/tcp']:
            host_port = ports['8080/tcp'][0]['HostPort']
            api_endpoint = f"http://localhost:{host_port}"
    
    # Check for updates
    update_available = False
    current_image = attrs['Config']['Image']
    try:
        client = get_docker_client()
        latest_image = client.images.get(current_image.split(':')[0] + ':latest')
        if latest_image.id != attrs['Image']:
            update_available = True
    except:
        pass
    
    return AgentInfo(
        agent_id=env_dict.get('CIRIS_AGENT_ID', container.name),
        agent_name=env_dict.get('CIRIS_AGENT_NAME', container.name),
        container_name=container.name,
        status=container.status,
        health=attrs.get('State', {}).get('Health', {}).get('Status'),
        api_endpoint=api_endpoint,
        created_at=datetime.fromisoformat(attrs['Created'].replace('Z', '+00:00')),
        started_at=datetime.fromisoformat(attrs['State']['StartedAt'].replace('Z', '+00:00')) if attrs['State']['StartedAt'] != '0001-01-01T00:00:00Z' else None,
        exit_code=attrs['State'].get('ExitCode'),
        update_available=update_available
    )


def verify_local_auth(authorization: Optional[str] = Header(None)) -> bool:
    """Verify local authentication for sensitive operations."""
    if not authorization:
        return False
    
    # For now, accept local token
    # In production, this would verify against a local-only auth mechanism
    return authorization == "Bearer local-manager-token"


# --- API Endpoints ---

@router.get("/agents", response_model=List[AgentInfo])
async def list_agents() -> List[AgentInfo]:
    """
    List all CIRIS agents managed by this CIRISManager.
    
    Returns information about running and stopped agents.
    """
    client = get_docker_client()
    agents = []
    
    # Find all CIRIS agent containers
    for container in client.containers.list(all=True):
        if 'ciris-agent' in container.name:
            try:
                agents.append(get_agent_info(container))
            except Exception as e:
                logger.warning(f"Failed to get info for container {container.name}: {e}")
    
    return agents


@router.get("/agents/{agent_id}", response_model=AgentInfo)
async def get_agent(agent_id: str) -> AgentInfo:
    """
    Get detailed information about a specific agent.
    """
    client = get_docker_client()
    
    # Find container by agent_id or container name
    for container in client.containers.list(all=True):
        if container.name == agent_id or container.name == f"ciris-agent-{agent_id}":
            return get_agent_info(container)
    
    raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")


@router.post("/agents", response_model=AgentInfo)
async def create_agent(
    request: AgentCreationRequest,
    authorized: bool = Depends(verify_local_auth)
) -> AgentInfo:
    """
    Create a new CIRIS agent with WA authorization.
    
    Requires local authentication and valid WA signature.
    """
    if not authorized:
        raise HTTPException(status_code=401, detail="Local authentication required")
    
    # TODO: Verify WA signature
    if not request.wa_signature:
        raise HTTPException(status_code=403, detail="WA signature required for agent creation")
    
    # For now, return not implemented
    raise HTTPException(status_code=501, detail="Agent creation not yet implemented")


@router.post("/agents/{agent_id}/notify-update")
async def notify_update(
    agent_id: str,
    notification: UpdateNotification,
    authorized: bool = Depends(verify_local_auth)
) -> Dict[str, str]:
    """
    Notify an agent that an update is available.
    
    The agent will be notified through its standard communication channel,
    allowing it to decide when to gracefully shutdown for the update.
    """
    if not authorized:
        raise HTTPException(status_code=401, detail="Local authentication required")
    
    # Find the agent
    client = get_docker_client()
    container = None
    
    for c in client.containers.list():
        if c.name == agent_id or c.name == f"ciris-agent-{agent_id}":
            container = c
            break
    
    if not container:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    
    if container.status != 'running':
        raise HTTPException(status_code=400, detail=f"Agent {agent_id} is not running")
    
    # TODO: Send notification through agent's API
    # For now, just acknowledge
    return {
        "status": "notified",
        "message": f"Agent {agent_id} has been notified of available update"
    }


@router.get("/deployments/{agent_id}/status", response_model=DeploymentStatus)
async def get_deployment_status(agent_id: str) -> DeploymentStatus:
    """
    Get the deployment status for an agent.
    
    Shows if there's a staged container waiting and consent status.
    """
    client = get_docker_client()
    
    # Check for running container
    running_container = None
    staged_container = None
    
    for container in client.containers.list(all=True):
        if container.name == f"ciris-agent-{agent_id}":
            running_container = container
        elif container.name == f"ciris-agent-{agent_id}-staged":
            staged_container = container
    
    if not running_container and not staged_container:
        raise HTTPException(status_code=404, detail=f"No deployment found for agent {agent_id}")
    
    # Determine status
    if staged_container and running_container:
        if running_container.status == 'running':
            status = "waiting_consent"
            message = "Staged container ready, waiting for agent consent"
        else:
            status = "ready_to_deploy"
            message = "Agent has stopped, ready to deploy staged container"
    elif staged_container:
        status = "staged_only"
        message = "Staged container ready, no running agent"
    else:
        status = "running"
        message = "Agent is running, no staged update"
    
    return DeploymentStatus(
        agent_id=agent_id,
        status=status,
        message=message,
        staged_container=staged_container.name if staged_container else None,
        consent_status="pending"  # TODO: Check actual consent status
    )


@router.get("/health")
async def health_check() -> Dict[str, Any]:
    """Health check endpoint for CIRISManager."""
    try:
        client = get_docker_client()
        docker_info = client.info()
        
        return {
            "status": "healthy",
            "service": "CIRISManager",
            "docker": {
                "connected": True,
                "version": docker_info.get('ServerVersion'),
                "containers": docker_info.get('Containers'),
                "running": docker_info.get('ContainersRunning')
            }
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "service": "CIRISManager",
            "error": str(e)
        }