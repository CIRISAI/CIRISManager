"""
API routes for CIRISManager v2 with pre-approved template support.

Provides endpoints for agent creation, discovery, and management.
"""

from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import logging
import os
from .auth import get_current_user_dependency as get_current_user
from ciris_manager.models import AgentInfo, UpdateNotification, DeploymentStatus
from ciris_manager.deployment_orchestrator import DeploymentOrchestrator

logger = logging.getLogger(__name__)


class CreateAgentRequest(BaseModel):
    """Request model for agent creation."""

    template: str = Field(..., description="Template name (e.g., 'scout', 'sage')")
    name: str = Field(..., description="Agent name")
    environment: Optional[Dict[str, str]] = Field(
        default=None, description="Additional environment variables"
    )
    wa_signature: Optional[str] = Field(
        default=None, description="WA signature for non-approved templates"
    )


class AgentResponse(BaseModel):
    """Response model for agent information."""

    agent_id: str
    name: str
    container: str
    port: int
    api_endpoint: str
    template: str
    status: str


class AgentListResponse(BaseModel):
    """Response model for agent list."""

    agents: List[AgentInfo]


class StatusResponse(BaseModel):
    """Response model for manager status."""

    status: str
    version: str = "1.0.0"
    components: Dict[str, str]
    auth_mode: Optional[str] = None


class TemplateListResponse(BaseModel):
    """Response model for template list."""

    templates: Dict[str, str]  # Template name -> description
    pre_approved: List[str]


class PortRange(BaseModel):
    """Port range information."""

    start: int
    end: int


class AllocatedPortsResponse(BaseModel):
    """Response model for allocated ports."""

    allocated: List[int]
    reserved: List[int]
    range: PortRange


def create_routes(manager: Any) -> APIRouter:
    """
    Create API routes with manager instance.

    Args:
        manager: CIRISManager instance

    Returns:
        Configured APIRouter
    """
    router = APIRouter()

    # Initialize deployment orchestrator
    deployment_orchestrator = DeploymentOrchestrator()

    # Deployment token for CD authentication
    DEPLOY_TOKEN = os.getenv(
        "CIRIS_DEPLOY_TOKEN", "f1cfb8ee418388a521904ea3a04ce0445471a33e5df891195399f1f5a82fc398"
    )

    # Check if we're in dev mode - if so, create a mock user dependency
    auth_mode = os.getenv("CIRIS_AUTH_MODE", "production")

    if auth_mode == "development":
        # Simple mock user for all endpoints
        async def get_mock_user() -> Dict[str, str]:
            return {"id": "dev-user", "email": "dev@ciris.local", "name": "Development User"}

        auth_dependency = Depends(get_mock_user)
    else:
        # Production uses real auth
        auth_dependency = Depends(get_current_user)

    # Special auth for deployment endpoints
    async def deployment_auth(authorization: Optional[str] = Header(None)) -> Dict[str, str]:
        """Verify deployment token for CD operations."""
        if not authorization:
            raise HTTPException(status_code=401, detail="Missing authorization header")

        # Extract token from "Bearer <token>" format
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise HTTPException(status_code=401, detail="Invalid authorization format")

        token = parts[1]
        if token != DEPLOY_TOKEN:
            raise HTTPException(status_code=401, detail="Invalid deployment token")

        return {"id": "github-actions", "email": "cd@ciris.ai", "name": "GitHub Actions CD"}

    @router.get("/health")
    async def health_check() -> Dict[str, str]:
        """Health check endpoint."""
        return {"status": "healthy", "service": "ciris-manager"}

    @router.get("/status", response_model=StatusResponse)
    async def get_status() -> StatusResponse:
        """Get manager status."""
        status = manager.get_status()
        return StatusResponse(
            status="running" if status["running"] else "stopped",
            components=status["components"],
            auth_mode=auth_mode,
        )

    @router.get("/agents", response_model=AgentListResponse)
    async def list_agents() -> AgentListResponse:
        """List all managed agents by discovering Docker containers."""
        from ciris_manager.docker_discovery import DockerAgentDiscovery

        discovery = DockerAgentDiscovery()
        agents = discovery.discover_agents()

        # Don't update nginx on GET requests - only update when agents change state

        return AgentListResponse(agents=agents)

    @router.get("/agents/{agent_name}")
    async def get_agent(agent_name: str) -> AgentResponse:
        """Get specific agent by name."""
        agent = manager.agent_registry.get_agent_by_name(agent_name)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")

        return AgentResponse(
            agent_id=agent.agent_id,
            name=agent.name,
            container=f"ciris-agent-{agent.agent_id}",
            port=agent.port,
            api_endpoint=f"http://localhost:{agent.port}",
            template=agent.template,
            status="running",
        )

    @router.post("/agents", response_model=AgentResponse)
    async def create_agent(
        request: CreateAgentRequest, user: dict = auth_dependency
    ) -> AgentResponse:
        """Create a new agent."""
        try:
            result = await manager.create_agent(
                template=request.template,
                name=request.name,
                environment=request.environment,
                wa_signature=request.wa_signature,
            )

            return AgentResponse(
                agent_id=result["agent_id"],
                name=request.name,
                container=result["container"],
                port=result["port"],
                api_endpoint=result["api_endpoint"],
                template=request.template,
                status=result["status"],
            )

        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e))
        except Exception as e:
            logger.error(f"Failed to create agent: {e}")
            raise HTTPException(status_code=500, detail="Failed to create agent")

        logger.info(f"Agent {result['agent_id']} created by {user['email']}")

    @router.delete("/agents/{agent_id}")
    async def delete_agent(agent_id: str, user: dict = auth_dependency) -> Dict[str, str]:
        """
        Delete an agent and clean up all resources.

        This will:
        - Stop and remove the agent container
        - Remove nginx routes
        - Free the allocated port
        - Remove agent from registry
        - Clean up agent directory
        """
        # Check if agent exists in registry
        agent = manager.agent_registry.get_agent(agent_id)
        if not agent:
            # Check if it's a discovered agent (not managed by CIRISManager)
            from ciris_manager.docker_discovery import DockerAgentDiscovery

            discovery = DockerAgentDiscovery()
            discovered_agents = discovery.discover_agents()

            discovered_agent = next((a for a in discovered_agents if a.agent_id == agent_id), None)
            if discovered_agent:
                # This is a discovered agent not managed by CIRISManager
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Agent '{agent_id}' was not created by CIRISManager. "
                        "Please stop it manually using docker-compose."
                    ),
                )
            else:
                raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

        # Perform deletion for Manager-created agents
        success = await manager.delete_agent(agent_id)

        if success:
            logger.info(f"Agent {agent_id} deleted by {user['email']}")
            return {
                "status": "deleted",
                "agent_id": agent_id,
                "message": f"Agent {agent_id} and all its resources have been removed",
            }
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to delete agent {agent_id}. Check logs for details.",
            )

    @router.get("/templates", response_model=TemplateListResponse)
    async def list_templates() -> TemplateListResponse:
        """List available templates."""
        from pathlib import Path

        # Get pre-approved templates from manifest (if it exists)
        pre_approved = manager.template_verifier.list_pre_approved_templates()

        # Scan template directory for all available templates
        all_templates = {}
        templates_dir = Path(manager.config.manager.templates_directory)

        if templates_dir.exists():
            for template_file in templates_dir.glob("*.yaml"):
                template_name = template_file.stem
                # For now, just return the template name and description
                # The actual config should be loaded when a specific template is selected
                # Just return template metadata - GUI gets env vars from separate endpoint
                all_templates[template_name] = (
                    f"{template_name.replace('-', ' ').title()} agent template"
                )

        # For development: if no manifest exists, treat some templates as pre-approved
        if not pre_approved and all_templates:
            # Common templates that don't need special approval
            default_pre_approved = ["echo", "scout", "sage", "test"]
            pre_approved_list = [t for t in default_pre_approved if t in all_templates]
        else:
            pre_approved_list = list(pre_approved.keys())

        return TemplateListResponse(templates=all_templates, pre_approved=pre_approved_list)

    @router.get("/env/default")
    async def get_default_env() -> Dict[str, str]:
        """Get default environment variables for agent creation."""
        # Return in .env file format as expected by GUI's parseEnvFile()
        env_vars = [
            # Core CIRIS requirements
            "LLM_PROVIDER=openai",
            "OPENAI_API_KEY=",  # User must provide
            "DATABASE_URL=sqlite:////app/data/ciris_engine.db",
            "API_HOST=0.0.0.0",
            "API_PORT=8080",  # Will be dynamically assigned
            "JWT_SECRET_KEY=generate-with-openssl-rand-hex-32",
            "ENVIRONMENT=production",
            "LOG_LEVEL=INFO",
            # Optional: Admin credentials (not in .env.example but commonly used)
            "ADMIN_USERNAME=admin",
            "ADMIN_PASSWORD=ciris_admin_password",
        ]

        return {"content": "\n".join(env_vars)}

    @router.get("/ports/allocated", response_model=AllocatedPortsResponse)
    async def get_allocated_ports() -> AllocatedPortsResponse:
        """Get allocated ports."""
        return AllocatedPortsResponse(
            allocated=list(manager.port_manager.allocated_ports.values()),
            reserved=list(manager.port_manager.reserved_ports),
            range=PortRange(
                start=manager.port_manager.start_port,
                end=manager.port_manager.end_port,
            ),
        )

    # CD Orchestration endpoints
    @router.post("/updates/notify", response_model=DeploymentStatus)
    async def notify_update(
        notification: UpdateNotification, _user: Dict[str, str] = Depends(deployment_auth)
    ) -> DeploymentStatus:
        """
        Receive update notification from CD pipeline.

        This is the single API call from GitHub Actions to trigger deployment.
        CIRISManager orchestrates everything else.
        """
        try:
            # Get current agents
            agents = await manager.get_agents()

            # Start deployment
            status = await deployment_orchestrator.start_deployment(notification, agents)

            logger.info(
                f"Started deployment {status.deployment_id} with strategy {notification.strategy}"
            )
            return status

        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except Exception as e:
            logger.error(f"Failed to start deployment: {e}")
            raise HTTPException(status_code=500, detail="Failed to start deployment")

    @router.get("/updates/status", response_model=Optional[DeploymentStatus])
    async def get_deployment_status(
        deployment_id: Optional[str] = None, _user: Dict[str, str] = Depends(deployment_auth)
    ) -> Optional[DeploymentStatus]:
        """
        Get deployment status.

        If deployment_id is not provided, returns current active deployment.
        """
        if deployment_id:
            return await deployment_orchestrator.get_deployment_status(deployment_id)
        else:
            return await deployment_orchestrator.get_current_deployment()

    @router.get("/updates/latest/changelog")
    async def get_latest_changelog() -> Dict[str, Any]:
        """
        Get recent commits for changelog information.

        Returns last 10 commits in a simple format for agents to understand changes.
        """
        try:
            # Try to get git log from CIRISAgent repo if available
            import subprocess
            from pathlib import Path

            # Check if we have access to CIRISAgent repo
            agent_repo_path = Path("/home/ciris/CIRISAgent")
            if not agent_repo_path.exists():
                return {"commits": [], "error": "Repository not accessible"}

            # Get last 10 commits with simple format
            result = subprocess.run(
                ["git", "log", "--oneline", "-10", "--format=%h %s (%cr)"],
                cwd=agent_repo_path,
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode != 0:
                return {"commits": [], "error": "Failed to fetch git log"}

            commits = []
            for line in result.stdout.strip().split("\n"):
                if line:
                    commits.append(line)

            return {"commits": commits, "count": len(commits), "repository": "CIRISAgent"}

        except Exception as e:
            logger.error(f"Failed to fetch changelog: {e}")
            return {"commits": [], "error": str(e)}

    return router
