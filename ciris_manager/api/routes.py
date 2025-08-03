"""
API routes for CIRISManager v2 with pre-approved template support.

Provides endpoints for agent creation, discovery, and management.
"""

from fastapi import APIRouter, HTTPException, Depends, Header, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import logging
import os
from pathlib import Path
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
    deployment_orchestrator = DeploymentOrchestrator(manager)

    # Deployment token for CD authentication
    DEPLOY_TOKEN = os.getenv("CIRIS_DEPLOY_TOKEN")

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
        if not DEPLOY_TOKEN:
            raise HTTPException(status_code=500, detail="Deployment token not configured")

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

    # Manager UI Routes - Protected by OAuth
    @router.get("/")
    async def manager_home(user: dict = auth_dependency) -> FileResponse:
        """Serve manager dashboard for @ciris.ai users."""
        # In production mode, check for @ciris.ai email
        if auth_mode == "production" and not user.get("email", "").endswith("@ciris.ai"):
            raise HTTPException(status_code=403, detail="Access restricted to @ciris.ai users")

        # Serve the manager UI
        static_path = Path(__file__).parent.parent.parent / "static" / "manager" / "index.html"
        if not static_path.exists():
            raise HTTPException(status_code=404, detail="Manager UI not found")

        return FileResponse(static_path)

    @router.get("/manager.js")
    async def manager_js(user: dict = auth_dependency) -> FileResponse:
        """Serve manager JavaScript."""
        if auth_mode == "production" and not user.get("email", "").endswith("@ciris.ai"):
            raise HTTPException(status_code=403, detail="Access restricted to @ciris.ai users")

        static_path = Path(__file__).parent.parent.parent / "static" / "manager" / "manager.js"
        if not static_path.exists():
            raise HTTPException(status_code=404, detail="Manager JS not found")

        return FileResponse(static_path, media_type="application/javascript")

    @router.get("/callback")
    async def manager_callback(token: Optional[str] = None) -> Response:
        """Handle OAuth callback redirect to Manager UI with token."""
        from fastapi.responses import HTMLResponse

        # Serve a minimal HTML page that extracts the token and redirects
        html_content = """
<!DOCTYPE html>
<html>
<head>
    <title>Redirecting...</title>
    <style>
        body {
            background-color: #1a1a1a;
            color: #ffffff;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
        }
        .loading {
            text-align: center;
        }
        .spinner {
            border: 3px solid #333;
            border-top: 3px solid #3b82f6;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
            margin: 0 auto 20px;
        }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
    </style>
</head>
<body>
    <div class="loading">
        <div class="spinner"></div>
        <p>Completing authentication...</p>
    </div>
    <script>
        // Extract token from URL
        const urlParams = new URLSearchParams(window.location.search);
        const token = urlParams.get('token');
        
        if (token) {
            // Store token in localStorage
            localStorage.setItem('managerToken', token);
            
            // Redirect to manager dashboard
            window.location.href = '/manager/';
        } else {
            // No token, redirect to login
            window.location.href = '/manager/';
        }
    </script>
</body>
</html>
"""

        return HTMLResponse(content=html_content)

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

    @router.get("/agents/{agent_id}/oauth/verify")
    async def verify_agent_oauth(agent_id: str, user: dict = auth_dependency) -> Dict[str, Any]:
        """
        Verify OAuth configuration for an agent.
        
        Checks if OAuth is properly configured and working.
        """
        # Get agent from registry
        agent = manager.agent_registry.get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
        
        # For now, we check if the agent has OAuth status
        # In a full implementation, this would actually test the OAuth flow
        oauth_configured = agent.oauth_status in ["configured", "verified"]
        oauth_working = agent.oauth_status == "verified"
        
        return {
            "agent_id": agent_id,
            "configured": oauth_configured,
            "working": oauth_working,
            "status": agent.oauth_status or "pending",
            "callback_urls": {
                "google": f"https://agents.ciris.ai/v1/auth/oauth/{agent_id}/google/callback",
                "github": f"https://agents.ciris.ai/v1/auth/oauth/{agent_id}/github/callback",
                "discord": f"https://agents.ciris.ai/v1/auth/oauth/{agent_id}/discord/callback",
            }
        }

    @router.post("/agents/{agent_id}/oauth/complete")
    async def mark_oauth_complete(agent_id: str, user: dict = auth_dependency) -> Dict[str, str]:
        """
        Mark OAuth as configured for an agent.
        
        Called after admin has registered callback URLs in provider dashboards.
        """
        # Get agent from registry
        agent = manager.agent_registry.get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
        
        # Update OAuth status
        agent.oauth_status = "configured"
        
        # Save to registry
        manager.agent_registry.save_metadata()
        
        logger.info(f"OAuth marked as configured for agent {agent_id} by {user['email']}")
        
        return {
            "status": "success",
            "agent_id": agent_id,
            "oauth_status": "configured",
            "message": "OAuth configuration marked as complete. Run verification to test."
        }

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
            # Get current agents with runtime status
            from ciris_manager.docker_discovery import DockerAgentDiscovery

            discovery = DockerAgentDiscovery()
            agents = discovery.discover_agents()

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

        Returns formatted changelog entries that can be included in update notifications.
        This endpoint returns mock data for now but could be enhanced to fetch from
        actual repositories or CI/CD systems.
        """
        # For now, return structured changelog data
        # In production, this could:
        # 1. Fetch from GitHub API using the commit SHA
        # 2. Parse from a CHANGELOG.md file
        # 3. Extract from CI/CD metadata

        return {
            "latest": {
                "version": "latest",
                "date": "2025-08-01",
                "changes": [
                    {
                        "type": "fix",
                        "description": "Memory leak in telemetry service",
                        "risk": "low",
                    },
                    {
                        "type": "feat",
                        "description": "Enhanced update notifications with context",
                        "risk": "low",
                    },
                    {
                        "type": "security",
                        "description": "Removed hardcoded deployment token",
                        "risk": "critical",
                    },
                ],
            },
            "summary": "3 changes: 1 fix, 1 feature, 1 security update",
            "recommended_action": "update",
            "breaking_changes": False,
        }

    @router.get("/versions/adoption")
    async def get_version_adoption(
        _user: Dict[str, str] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """
        Get version adoption data for all agents.

        Returns information about:
        - Current latest versions
        - Agent adoption status
        - Deployment history
        """
        # Get all agents with their metadata
        from ciris_manager.docker_discovery import DockerAgentDiscovery

        discovery = DockerAgentDiscovery()
        agents = discovery.discover_agents()

        # Get agent metadata from registry
        agent_versions = []
        for agent in agents:
            registry_agent = manager.agent_registry.get_agent(agent.agent_id)
            if registry_agent:
                metadata = registry_agent.metadata if hasattr(registry_agent, "metadata") else {}
                current_images = metadata.get("current_images", {})

                agent_versions.append(
                    {
                        "agent_id": agent.agent_id,
                        "agent_name": agent.agent_name,
                        "status": agent.status,
                        "current_agent_image": current_images.get("agent", "unknown"),
                        "current_gui_image": current_images.get("gui", "unknown"),
                        "last_updated": metadata.get("last_updated", "never"),
                    }
                )
            else:
                agent_versions.append(
                    {
                        "agent_id": agent.agent_id,
                        "agent_name": agent.agent_name,
                        "status": agent.status,
                        "current_agent_image": "unknown",
                        "current_gui_image": "unknown",
                        "last_updated": "never",
                    }
                )

        # Get latest versions from environment or config
        latest_agent_image = os.getenv(
            "CIRIS_LATEST_AGENT_IMAGE", "ghcr.io/cirisai/ciris-agent:latest"
        )
        latest_gui_image = os.getenv("CIRIS_LATEST_GUI_IMAGE", "ghcr.io/cirisai/ciris-gui:latest")

        # Get current deployment if any
        current_deployment = await deployment_orchestrator.get_current_deployment()

        # Get recent deployments
        recent_deployments = []
        for deployment_id, status in deployment_orchestrator.deployments.items():
            if status.completed_at:  # Only show completed deployments
                recent_deployments.append(
                    {
                        "deployment_id": deployment_id,
                        "started_at": status.started_at,
                        "completed_at": status.completed_at,
                        "agents_updated": status.agents_updated,
                        "agents_total": status.agents_total,
                        "message": status.message,
                        "status": status.status,
                    }
                )

        # Sort by completed_at descending
        recent_deployments.sort(key=lambda x: str(x["completed_at"] or ""), reverse=True)
        recent_deployments = recent_deployments[:10]  # Last 10 deployments

        return {
            "latest_versions": {
                "agent_image": latest_agent_image,
                "gui_image": latest_gui_image,
            },
            "agent_versions": agent_versions,
            "current_deployment": current_deployment.model_dump() if current_deployment else None,
            "recent_deployments": recent_deployments,
        }

    return router
