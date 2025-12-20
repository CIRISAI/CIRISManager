"""
API routes for CIRISManager v2 with pre-approved template support.

Provides endpoints for agent creation, discovery, and management.
"""

from fastapi import APIRouter, HTTPException, Depends, Header, Response, Request
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any, List, Union
import asyncio
import httpx
import logging
import os  # noqa: F401 - used in jailbreaker section
import aiofiles  # type: ignore
from .auth import get_current_user_dependency as get_current_user
from ciris_manager.models import AgentInfo, UpdateNotification, DeploymentStatus, CreateAgentRequest
from ciris_manager.deployment import DeploymentOrchestrator
from ciris_manager.utils.log_sanitizer import sanitize_agent_id
from .rate_limit import create_limit

logger = logging.getLogger(__name__)

# CRITICAL DEBUG: Test if routes.py module is being imported at all
print("ROUTES.PY MODULE LOADED - JAILBREAKER DEBUG", flush=True)
logger.info("CRITICAL DEBUG: routes.py module imported successfully")


# CreateAgentRequest is now imported from models.py


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
    version: str = "2.2.0"
    components: Dict[str, str]
    auth_mode: Optional[str] = None
    uptime_seconds: Optional[int] = None
    start_time: Optional[str] = None
    system_metrics: Optional[Dict[str, Any]] = None


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
    import time

    start_time = time.time()
    logger.info("create_routes() starting...")
    router = APIRouter()

    # Initialize deployment orchestrator
    logger.info(f"[{time.time() - start_time:.2f}s] Creating DeploymentOrchestrator...")
    deployment_orchestrator = DeploymentOrchestrator(manager)
    logger.info(f"[{time.time() - start_time:.2f}s] DeploymentOrchestrator created successfully")

    # Initialize deployment token manager
    logger.info(f"[{time.time() - start_time:.2f}s] Creating DeploymentTokenManager...")
    from ciris_manager.deployment_tokens import DeploymentTokenManager

    token_manager = DeploymentTokenManager()
    logger.info(f"[{time.time() - start_time:.2f}s] DeploymentTokenManager created")

    # Load deployment tokens (auto-generates if missing)
    logger.info(f"[{time.time() - start_time:.2f}s] Loading deployment tokens...")
    DEPLOY_TOKENS = token_manager.get_all_tokens()
    logger.info(f"[{time.time() - start_time:.2f}s] Deployment tokens loaded")

    # Also set them as environment variables for backwards compatibility
    for repo, token in DEPLOY_TOKENS.items():
        if repo == "legacy":
            os.environ["CIRIS_DEPLOY_TOKEN"] = token
        else:
            os.environ[f"CIRIS_{repo.upper()}_DEPLOY_TOKEN"] = token

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

    # Helper function for resolving agent lookups with composite keys
    def resolve_agent(
        agent_id: str, occurrence_id: Optional[str] = None, server_id: Optional[str] = None
    ):
        """
        Resolve an agent lookup with composite key support.

        Handles cases where multiple instances have the same agent_id but different occurrence_ids.

        Args:
            agent_id: The agent ID to look up
            occurrence_id: Optional occurrence ID for disambiguation
            server_id: Optional server ID for disambiguation

        Returns:
            RegisteredAgent if found uniquely

        Raises:
            HTTPException: If agent not found or multiple instances exist without disambiguation
        """
        if occurrence_id or server_id:
            # Precise lookup with composite key
            agent = manager.agent_registry.get_agent(
                agent_id, occurrence_id=occurrence_id, server_id=server_id
            )
            if not agent:
                raise HTTPException(
                    status_code=404,
                    detail=f"Agent '{agent_id}' with occurrence_id='{occurrence_id}' and server_id='{server_id}' not found",
                )
            return agent
        else:
            # No disambiguation provided - check if there are multiple instances
            all_instances = manager.agent_registry.get_agents_by_agent_id(agent_id)

            if len(all_instances) == 0:
                raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
            elif len(all_instances) == 1:
                # Only one instance - unambiguous
                return all_instances[0]
            else:
                # Multiple instances exist - need disambiguation
                instance_details = [
                    f"  - occurrence_id={a.occurrence_id or 'none'}, server_id={a.server_id}"
                    for a in all_instances
                ]
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Multiple instances of agent '{agent_id}' exist. "
                        f"Please specify occurrence_id and/or server_id query parameters:\n"
                        + "\n".join(instance_details)
                    ),
                )

    # Special auth for deployment endpoints
    async def deployment_auth(authorization: Optional[str] = Header(None)) -> Dict[str, str]:
        """Verify deployment token for CD operations and identify the source."""
        if not any(DEPLOY_TOKENS.values()):
            raise HTTPException(status_code=500, detail="Deployment tokens not configured")

        if not authorization:
            raise HTTPException(status_code=401, detail="Missing authorization header")

        # Extract token from "Bearer <token>" format
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise HTTPException(status_code=401, detail="Invalid authorization format")

        token = parts[1]

        # Identify which repo this token belongs to
        source_repo = None
        for repo_type, repo_token in DEPLOY_TOKENS.items():
            if repo_token and token == repo_token:
                source_repo = repo_type
                break

        if not source_repo:
            raise HTTPException(status_code=401, detail="Invalid deployment token")

        return {
            "id": "github-actions",
            "email": "cd@ciris.ai",
            "name": "GitHub Actions CD",
            "source_repo": source_repo,  # Track which repo is making the request
        }

    # Manager UI Routes - Protected by OAuth
    @router.get("/", response_model=None)
    async def manager_home(
        request: Request, authorization: Optional[str] = Header(None)
    ) -> Union[FileResponse, RedirectResponse]:
        """Serve manager dashboard for @ciris.ai users."""
        # Check authentication manually
        try:
            from .auth_routes import get_auth_service

            auth_service = get_auth_service()
            if not auth_service:
                return RedirectResponse(url="/manager/v1/oauth/login", status_code=303)

            # Try authorization header first
            user = auth_service.get_current_user(authorization)
            # If no auth header, try cookie
            if not user:
                token = request.cookies.get("manager_token")
                if token:
                    user = auth_service.get_current_user(f"Bearer {token}")

            if not user:
                return RedirectResponse(url="/manager/v1/oauth/login", status_code=303)

        except Exception:
            # Not authenticated - redirect to OAuth login
            return RedirectResponse(url="/manager/v1/oauth/login", status_code=303)

        # In production mode, check for @ciris.ai email
        if auth_mode == "production" and not user.get("email", "").endswith("@ciris.ai"):
            raise HTTPException(status_code=403, detail="Access restricted to @ciris.ai users")

        # Serve the manager UI
        static_path = Path(__file__).parent.parent.parent / "static" / "manager" / "index.html"
        if not static_path.exists():
            raise HTTPException(status_code=404, detail="Manager UI not found")

        return FileResponse(
            static_path,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )

    @router.get("/manager.js", response_model=None)
    async def manager_js(
        request: Request, authorization: Optional[str] = Header(None)
    ) -> Union[FileResponse, RedirectResponse]:
        """Serve manager JavaScript."""
        # Check authentication manually
        try:
            from .auth_routes import get_auth_service

            auth_service = get_auth_service()
            if not auth_service:
                return RedirectResponse(url="/manager/v1/oauth/login", status_code=303)

            # Try authorization header first
            user = auth_service.get_current_user(authorization)
            # If no auth header, try cookie
            if not user:
                token = request.cookies.get("manager_token")
                if token:
                    user = auth_service.get_current_user(f"Bearer {token}")

            if not user:
                return RedirectResponse(url="/manager/v1/oauth/login", status_code=303)

        except Exception:
            # Not authenticated - redirect to OAuth login
            return RedirectResponse(url="/manager/v1/oauth/login", status_code=303)

        if auth_mode == "production" and not user.get("email", "").endswith("@ciris.ai"):
            raise HTTPException(status_code=403, detail="Access restricted to @ciris.ai users")

        static_path = Path(__file__).parent.parent.parent / "static" / "manager" / "manager.js"
        if not static_path.exists():
            raise HTTPException(status_code=404, detail="Manager JS not found")

        return FileResponse(
            static_path,
            media_type="application/javascript",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )

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
            uptime_seconds=status.get("uptime_seconds"),
            start_time=status.get("start_time"),
            system_metrics=status.get("system_metrics"),
        )

    @router.get("/agents", response_model=AgentListResponse)
    async def list_agents() -> AgentListResponse:
        """List all managed agents by discovering Docker containers."""
        from ciris_manager.docker_discovery import DockerAgentDiscovery

        discovery = DockerAgentDiscovery(
            manager.agent_registry, docker_client_manager=manager.docker_client
        )
        agents = discovery.discover_agents()

        # Don't update nginx on GET requests - only update when agents change state

        return AgentListResponse(agents=agents)

    @router.get("/agents/versions")
    async def get_agent_versions(_user: Dict[str, str] = auth_dependency) -> Dict[str, Any]:
        """
        Get version information for all agents including version history.

        Returns version, codename, code hash, and version history for rollback.
        Uses DeploymentOrchestrator as single source of truth for version data.
        """
        from ciris_manager.docker_discovery import DockerAgentDiscovery
        from ciris_manager.deployment import get_deployment_orchestrator

        discovery = DockerAgentDiscovery(
            manager.agent_registry, docker_client_manager=manager.docker_client
        )
        agents = discovery.discover_agents()

        # Get version history from deployment orchestrator (single source of truth)
        deployment_orchestrator = get_deployment_orchestrator()

        # Build deployment options from all available deployments
        deployment_options: List[Dict[str, Any]] = []

        # Add current active deployment if exists
        current_deployment_data: Optional[Dict[str, Any]] = None
        if deployment_orchestrator.current_deployment:
            current = deployment_orchestrator.deployments.get(
                deployment_orchestrator.current_deployment
            )
            if current and current.notification and current.notification.agent_image:
                current_deployment_data = {
                    "image": current.notification.agent_image,
                    "tag": current.notification.version,
                    "digest": current.notification.commit_sha,
                    "deployed_at": current.started_at,
                    "deployment_id": current.deployment_id,
                    "status": "current",
                }
                deployment_options.append(current_deployment_data)

        # Add pending/staged deployments
        staged_deployment_data: Optional[Dict[str, Any]] = None
        for deployment_id, deployment in deployment_orchestrator.pending_deployments.items():
            if deployment.notification and deployment.notification.agent_image:
                staged_deployment_data = {
                    "image": deployment.notification.agent_image,
                    "tag": deployment.notification.version,
                    "digest": deployment.notification.commit_sha,
                    "staged_at": deployment.staged_at,
                    "deployment_id": deployment_id,
                    "status": "staged",
                }
                deployment_options.append(staged_deployment_data)
                break  # Use first pending deployment

        # Add deployments as rollback options (completed, failed, cancelled - any with valid version data)
        completed_deployments: List[Dict[str, Any]] = []
        for deployment_id, deployment in deployment_orchestrator.deployments.items():
            if (
                deployment.status in ["completed", "failed", "cancelled", "rejected"]
                and deployment.notification
                and deployment.notification.agent_image
                and deployment.notification.version  # Must have a version tag
                and deployment_id != deployment_orchestrator.current_deployment
            ):
                completed_deployments.append(
                    {
                        "image": deployment.notification.agent_image,
                        "tag": deployment.notification.version,
                        "digest": deployment.notification.commit_sha,
                        "deployed_at": deployment.completed_at or deployment.started_at,
                        "deployment_id": deployment_id,
                        "status": "available"
                        if deployment.status == "completed"
                        else deployment.status,
                        "agents_updated": deployment.agents_updated,
                        "agents_total": deployment.agents_total,
                    }
                )

        # Sort completed deployments by completion time (newest first) and take last 5
        completed_deployments.sort(key=lambda x: x["deployed_at"] or "", reverse=True)
        deployment_options.extend(completed_deployments[:5])

        # If no current deployment, use staged deployment as current for UI compatibility
        if not current_deployment_data and staged_deployment_data:
            current_deployment_data = staged_deployment_data.copy()
            current_deployment_data["status"] = "current"

        # Build version response
        agent_versions = []
        version_summary: Dict[str, int] = {}

        for agent in agents:
            agent_version = {
                "agent_id": agent.agent_id,
                "agent_name": agent.agent_name,
                "version": agent.version or "unknown",
                "codename": agent.codename or "unknown",
                "code_hash": agent.code_hash or "unknown",
                "status": agent.status,
            }
            agent_versions.append(agent_version)

            # Count versions for summary
            version_key = agent.version or "unknown"
            version_summary[version_key] = version_summary.get(version_key, 0) + 1

        return {
            "agents": agent_versions,
            "version_summary": version_summary,
            "total_agents": len(agents),
            # Full deployment options list for UI selection
            "deployment_options": deployment_options,
            # Backward compatibility with legacy UI structure
            "agent": {
                "current": current_deployment_data,
                "staged": staged_deployment_data,
                "n_minus_1": completed_deployments[0] if len(completed_deployments) > 0 else None,
                "n_minus_2": completed_deployments[1] if len(completed_deployments) > 1 else None,
            },
            "gui": {
                "current": None,  # GUI versions tracked separately
                "staged": None,
                "n_minus_1": None,
                "n_minus_2": None,
            },
        }

    @router.post("/agents/{agent_id}/deployment")
    async def set_agent_deployment(
        agent_id: str,
        request: Dict[str, Any],
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
        _user: Dict[str, str] = auth_dependency,
    ) -> Dict[str, Any]:
        """
        Set the deployment identifier for an agent.

        Supports composite keys for multi-instance deployments.
        """
        deployment = request.get("deployment")
        if not deployment:
            raise HTTPException(status_code=400, detail="Deployment field is required")

        # Resolve agent to ensure it exists
        _ = resolve_agent(agent_id, occurrence_id=occurrence_id, server_id=server_id)

        # Update deployment using composite key
        if not manager.agent_registry.set_deployment(
            agent_id, deployment, occurrence_id=occurrence_id, server_id=server_id
        ):
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

        return {"status": "success", "agent_id": agent_id, "deployment": deployment}

    @router.get("/agents/by-deployment/{deployment}")
    async def get_agents_by_deployment(
        deployment: str, _user: Dict[str, str] = auth_dependency
    ) -> Dict[str, Any]:
        """Get all agents with a specific deployment identifier."""
        agents = manager.agent_registry.get_agents_by_deployment(deployment)

        # Convert to API response format
        agent_list = []
        for agent in agents:
            agent_list.append(
                {
                    "agent_id": agent.agent_id,
                    "name": agent.name,
                    "template": agent.template,
                    "port": agent.port,
                    "deployment": deployment,
                    "metadata": agent.metadata if hasattr(agent, "metadata") else {},
                }
            )

        return {"deployment": deployment, "agents": agent_list, "count": len(agent_list)}

    @router.get("/agents/{agent_id}")
    async def get_agent(
        agent_id: str,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> AgentResponse:
        """
        Get specific agent by ID.

        Supports composite keys for multi-instance deployments:
        - occurrence_id: Optional occurrence ID for disambiguation
        - server_id: Optional server ID for disambiguation

        If multiple instances exist with the same agent_id, you must specify
        occurrence_id and/or server_id to disambiguate.
        """
        agent = resolve_agent(agent_id, occurrence_id=occurrence_id, server_id=server_id)

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
    @create_limit
    async def create_agent(
        request: Request, agent_request: CreateAgentRequest, user: dict = auth_dependency
    ) -> AgentResponse:
        """Create a new agent."""
        try:
            # Check if template requires WA review (Tier 4/5)
            from pathlib import Path
            import yaml

            try:
                # Validate template name to prevent path traversal
                import re

                if not re.match(r"^[a-zA-Z0-9_-]+$", agent_request.template):
                    raise HTTPException(status_code=400, detail="Invalid template name")

                templates_dir = Path(manager.config.manager.templates_directory)
                template_file = templates_dir / f"{agent_request.template}.yaml"

                # Ensure the resolved path is within the templates directory
                template_file = template_file.resolve()
                templates_dir_resolved = templates_dir.resolve()
                if not str(template_file).startswith(str(templates_dir_resolved)):
                    raise HTTPException(status_code=400, detail="Invalid template path")

                if template_file.exists():
                    async with aiofiles.open(template_file, "r") as f:
                        content = await f.read()
                        template_data = yaml.safe_load(content)
                    stewardship_tier = template_data.get("stewardship", {}).get(
                        "stewardship_tier", 1
                    )

                    # Validate WA review for Tier 4/5 agents
                    if stewardship_tier >= 4:
                        if not agent_request.wa_review_completed:
                            raise HTTPException(
                                status_code=400,
                                detail=f"WA review confirmation required for Tier {stewardship_tier} agent",
                            )
                        # Log the WA review confirmation for audit
                        logger.info(
                            f"WA review confirmed for Tier {stewardship_tier} agent '{agent_request.name}' "
                            f"(template: {agent_request.template}) by {user['email']}"
                        )
            except (TypeError, AttributeError) as e:
                # In test environment or when templates_directory is not properly configured
                logger.debug(f"Could not check template stewardship tier: {e}")
                pass

            result = await manager.create_agent(
                template=agent_request.template,
                name=agent_request.name,
                environment=agent_request.environment,
                wa_signature=agent_request.wa_signature,
                use_mock_llm=agent_request.use_mock_llm,
                enable_discord=agent_request.enable_discord,
                billing_enabled=agent_request.billing_enabled,
                billing_api_key=agent_request.billing_api_key,
                server_id=agent_request.server_id,
                database_url=agent_request.database_url,
                database_ssl_cert_path=agent_request.database_ssl_cert_path,
                agent_occurrence_id=agent_request.agent_occurrence_id,
            )

            logger.info(f"Agent {result['agent_id']} created by {user['email']}")

            return AgentResponse(
                agent_id=result["agent_id"],
                name=agent_request.name,
                container=result["container"],
                port=result["port"],
                api_endpoint=result["api_endpoint"],
                template=agent_request.template,
                status=result["status"],
            )

        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e))
        except HTTPException:
            raise  # Re-raise HTTP exceptions as-is
        except Exception as e:
            logger.error(f"Failed to create agent: {e}")
            raise HTTPException(status_code=500, detail="Failed to create agent")

    @router.delete("/agents/{agent_id}")
    async def delete_agent(
        agent_id: str,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
        user: dict = auth_dependency,
    ) -> Dict[str, str]:
        """
        Delete an agent and clean up all resources.

        This will:
        - Stop and remove the agent container
        - Remove nginx routes
        - Free the allocated port
        - Remove agent from registry
        - Clean up agent directory

        Supports composite keys for multi-instance deployments.
        """
        # Check if agent exists in registry
        try:
            _ = resolve_agent(agent_id, occurrence_id=occurrence_id, server_id=server_id)
        except HTTPException as e:
            if e.status_code == 404:
                # Check if it's a discovered agent (not managed by CIRISManager)
                from ciris_manager.docker_discovery import DockerAgentDiscovery

                discovery = DockerAgentDiscovery(
                    manager.agent_registry, docker_client_manager=manager.docker_client
                )
                discovered_agents = discovery.discover_agents()

                discovered_agent = next(
                    (a for a in discovered_agents if a.agent_id == agent_id), None
                )
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
            else:
                # Re-raise other exceptions (e.g., multiple instances without disambiguation)
                raise

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

    @router.get("/agents/{agent_id}/logs")
    async def get_agent_logs(
        agent_id: str,
        lines: int = 100,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
        _user: dict = auth_dependency,
    ) -> PlainTextResponse:
        """
        Get container logs for an agent.

        Args:
            agent_id: Agent identifier
            lines: Number of log lines to return (default 100)
            occurrence_id: Optional occurrence ID for multi-instance agents
            server_id: Optional server ID for multi-server deployments
        """
        try:
            # Resolve the agent
            agent = resolve_agent(agent_id, occurrence_id=occurrence_id, server_id=server_id)

            # Get container name
            container_name = f"ciris-agent-{agent_id}"

            # Get the correct Docker client for this agent's server
            client = manager.docker_client.get_client(agent.server_id)

            try:
                container = client.containers.get(container_name)
                logs = container.logs(tail=lines, timestamps=True).decode("utf-8")
                return PlainTextResponse(content=logs)
            except Exception as e:
                logger.warning(f"Failed to get logs for container {container_name}: {e}")
                raise HTTPException(
                    status_code=404,
                    detail=f"Container {container_name} not found or logs unavailable",
                )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting logs for agent {agent_id}: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/agents/{agent_id}/logs/file/{filename}")
    async def get_agent_log_file(
        agent_id: str,
        filename: str,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
        _user: dict = auth_dependency,
    ) -> PlainTextResponse:
        """
        Get a specific log file from an agent container.

        Supported filenames:
        - latest.log: Current application log
        - incidents_latest.log: Current incidents log

        Args:
            agent_id: Agent identifier
            filename: Log filename (latest.log or incidents_latest.log)
            occurrence_id: Optional occurrence ID for multi-instance agents
            server_id: Optional server ID for multi-server agents

        Returns:
            PlainTextResponse with log file contents
        """
        # Validate filename to prevent path traversal
        allowed_files = ["latest.log", "incidents_latest.log"]
        if filename not in allowed_files:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid filename. Allowed: {allowed_files}",
            )

        try:
            # Resolve the agent
            agent = resolve_agent(agent_id, occurrence_id=occurrence_id, server_id=server_id)

            # Get container name - include occurrence_id if present
            if agent.occurrence_id:
                container_name = f"ciris-{agent_id}-{agent.occurrence_id}"
            else:
                container_name = f"ciris-{agent_id}"

            # Get Docker client for the appropriate server
            client = manager.docker_client.get_client(agent.server_id)

            try:
                container = client.containers.get(container_name)
                # Use docker exec to cat the log file
                exit_code, output = container.exec_run(
                    f"cat /app/logs/{filename}",
                    demux=False,
                )
                if exit_code != 0:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Log file {filename} not found in container {container_name}",
                    )
                content = output.decode("utf-8") if isinstance(output, bytes) else output
                return PlainTextResponse(content=content)
            except HTTPException:
                raise
            except Exception as e:
                logger.warning(
                    f"Failed to get log file {filename} for container {container_name}: {e}"
                )
                raise HTTPException(
                    status_code=404,
                    detail=f"Container {container_name} not found or log file unavailable: {e}",
                )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting log file for agent {agent_id}: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/agents/{agent_id}/start")
    async def start_agent(
        agent_id: str,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
        user: dict = auth_dependency,
    ) -> Dict[str, str]:
        """
        Start a stopped agent container using Docker.
        If the image has changed, recreate the container with the new image.

        Supports composite keys for multi-instance deployments.
        """
        try:
            # Check if agent exists in registry
            agent = resolve_agent(agent_id, occurrence_id=occurrence_id, server_id=server_id)

            # Get container name
            container_name = f"ciris-agent-{agent_id}"

            # Use Docker API to check container state
            import docker

            # Get the correct Docker client for this agent's server
            client = manager.docker_client.get_client(agent.server_id)

            try:
                container = client.containers.get(container_name)

                # Check if container is already running
                if container.status == "running":
                    return {
                        "status": "already_running",
                        "agent_id": agent_id,
                        "message": f"Agent {agent_id} is already running",
                        "container": container_name,
                    }

                # Check if the container's image matches what we expect
                expected_image = "ghcr.io/cirisai/ciris-agent:latest"
                container_image = ""
                if container.image and container.image.tags:
                    container_image = container.image.tags[0]

                # If image has changed or we have a compose file, recreate the container
                if container_image != expected_image or (agent and agent.compose_file):
                    logger.info(
                        f"Container image changed from {container_image} to {expected_image}, recreating container"
                    )

                    # Use docker-compose to recreate with new image
                    if agent and agent.compose_file:
                        compose_path = Path(agent.compose_file)
                        if compose_path.exists():
                            result = await asyncio.create_subprocess_exec(
                                "docker-compose",
                                "-f",
                                str(compose_path),
                                "up",
                                "-d",
                                "--pull",
                                "always",
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.PIPE,
                            )
                            stdout, stderr = await result.communicate()

                            if result.returncode == 0:
                                logger.info(
                                    f"Agent {agent_id} recreated with new image by {user['email']}"
                                )
                                return {
                                    "status": "success",
                                    "agent_id": agent_id,
                                    "message": f"Agent {agent_id} is starting with updated image",
                                    "container": container_name,
                                }
                            else:
                                raise HTTPException(
                                    status_code=500,
                                    detail=f"Failed to recreate agent: {stderr.decode()}",
                                )
                    else:
                        # No compose file, just start the existing container
                        container.start()
                else:
                    # Same image, just start the container
                    container.start()

                logger.info(f"Agent {agent_id} started by {user['email']}")

                return {
                    "status": "success",
                    "agent_id": agent_id,
                    "message": f"Agent {agent_id} is starting",
                    "container": container_name,
                }
            except docker.errors.NotFound:
                # Try alternative container names
                try:
                    container = client.containers.get(f"ciris-{agent_id}")
                    if container.status != "running":
                        container.start()
                    return {
                        "status": "success",
                        "agent_id": agent_id,
                        "message": f"Agent {agent_id} is starting",
                    }
                except docker.errors.NotFound:
                    # If container doesn't exist, try using docker-compose
                    if agent and agent.compose_file:
                        compose_path = Path(agent.compose_file)
                        if compose_path.exists():
                            result = await asyncio.create_subprocess_exec(
                                "docker-compose",
                                "-f",
                                str(compose_path),
                                "up",
                                "-d",
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.PIPE,
                            )
                            stdout, stderr = await result.communicate()

                            if result.returncode == 0:
                                return {
                                    "status": "success",
                                    "agent_id": agent_id,
                                    "message": f"Agent {agent_id} is starting via docker-compose",
                                }
                            else:
                                raise HTTPException(
                                    status_code=500,
                                    detail=f"Failed to start agent: {stderr.decode()}",
                                )

                    raise HTTPException(
                        status_code=404, detail=f"Container for agent '{agent_id}' not found"
                    )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to start agent {agent_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to start agent: {str(e)}")

    @router.post("/agents/{agent_id}/stop")
    async def stop_agent(
        agent_id: str,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
        user: dict = auth_dependency,
    ) -> Dict[str, str]:
        """
        Force stop an agent container immediately using Docker.

        Supports composite keys for multi-instance deployments.
        """
        try:
            # Check if agent exists in registry
            agent = resolve_agent(agent_id, occurrence_id=occurrence_id, server_id=server_id)

            # Get container name
            container_name = f"ciris-agent-{agent_id}"

            # Use Docker API to stop the container
            import docker

            # Get the correct Docker client for this agent's server
            client = manager.docker_client.get_client(agent.server_id)

            try:
                container = client.containers.get(container_name)
                container.stop(timeout=10)  # 10 second timeout for graceful stop

                logger.info(f"Agent {agent_id} force stopped by {user['email']}")

                return {
                    "status": "success",
                    "agent_id": agent_id,
                    "message": f"Agent {agent_id} has been stopped",
                    "container": container_name,
                }
            except docker.errors.NotFound:
                # Try alternative container name
                try:
                    container = client.containers.get(f"ciris-{agent_id}")
                    container.stop(timeout=10)
                    return {
                        "status": "success",
                        "agent_id": agent_id,
                        "message": f"Agent {agent_id} has been stopped",
                    }
                except docker.errors.NotFound:
                    raise HTTPException(
                        status_code=404, detail=f"Container for agent '{agent_id}' not found"
                    )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to stop agent {agent_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to stop agent: {str(e)}")

    @router.post("/agents/{agent_id}/shutdown")
    async def request_shutdown_agent(
        agent_id: str,
        request: Dict[str, str],
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
        user: dict = auth_dependency,
    ) -> Dict[str, str]:
        """
        Request a graceful shutdown of an agent with a reason.
        This sends a shutdown request to the agent's API.

        Supports composite keys for multi-instance deployments.
        """
        try:
            # Check if agent exists and get its port
            agent = resolve_agent(agent_id, occurrence_id=occurrence_id, server_id=server_id)

            reason = request.get("reason", "Operator requested shutdown")

            # Get agent auth headers
            from ciris_manager.agent_auth import get_agent_auth

            auth = get_agent_auth()

            # Send shutdown request to agent's API
            async with httpx.AsyncClient(timeout=30.0) as client:
                try:
                    headers = auth.get_auth_headers(agent_id)

                    # Get the correct URL for this agent's server
                    server_config = manager.docker_client.get_server_config(agent.server_id)
                    if server_config.is_local:
                        agent_url = f"http://localhost:{agent.port}"
                    else:
                        agent_url = f"http://{server_config.vpc_ip}:{agent.port}"

                    response = await client.post(
                        f"{agent_url}/v1/system/shutdown",
                        headers=headers,
                        json={"reason": reason},
                    )

                    if response.status_code == 200:
                        logger.info(
                            f"Shutdown requested for agent {agent_id} by {user['email']}: {reason}"
                        )
                        return {
                            "status": "success",
                            "agent_id": agent_id,
                            "message": f"Shutdown request sent to agent {agent_id}",
                            "reason": reason,
                        }
                    else:
                        logger.warning(
                            f"Agent {sanitize_agent_id(agent_id)} returned {response.status_code} for shutdown request"
                        )
                        return {
                            "status": "accepted",
                            "agent_id": agent_id,
                            "message": "Agent may not support graceful shutdown, use force stop if needed",
                        }

                except httpx.ConnectError:
                    return {
                        "status": "unreachable",
                        "agent_id": agent_id,
                        "message": "Agent is not responding, use force stop if needed",
                    }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to request shutdown for agent {agent_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to request shutdown: {str(e)}")

    @router.post("/agents/{agent_id}/restart")
    async def restart_agent(
        agent_id: str,
        occurrence_id: Optional[str] = None,
        server_id_param: Optional[str] = None,
        user: dict = auth_dependency,
    ) -> Dict[str, str]:
        """
        Restart an agent container using Docker.

        This will perform a docker restart on the container,
        which is faster than stop/start and preserves the container state.

        Supports composite keys for multi-instance deployments.
        """
        try:
            # Check if agent exists in registry
            try:
                agent = resolve_agent(
                    agent_id, occurrence_id=occurrence_id, server_id=server_id_param
                )
                server_id = agent.server_id
            except HTTPException as e:
                if e.status_code != 404:
                    raise
                agent = None
                server_id = "main"  # Default to main server

            if not agent:
                # Check if it's a discovered agent
                from ciris_manager.docker_discovery import DockerAgentDiscovery

                discovery = DockerAgentDiscovery(
                    manager.agent_registry, docker_client_manager=manager.docker_client
                )
                discovered_agents = discovery.discover_agents()

                discovered_agent = next(
                    (a for a in discovered_agents if a.agent_id == agent_id), None
                )
                if not discovered_agent:
                    raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

                # Use server_id from discovered agent if available
                if hasattr(discovered_agent, "server_id"):
                    server_id = discovered_agent.server_id
            else:
                # Use server_id from registered agent
                server_id = agent.server_id

            # Get container name
            container_name = f"ciris-agent-{agent_id}"

            # Use Docker API to restart the container
            import docker

            # Get the correct Docker client for this agent's server
            client = manager.docker_client.get_client(server_id)

            try:
                container = client.containers.get(container_name)
                container.restart(timeout=30)

                logger.info(f"Agent {agent_id} restarted by {user['email']}")

                return {
                    "status": "success",
                    "agent_id": agent_id,
                    "message": f"Agent {agent_id} is restarting",
                    "container": container_name,
                }
            except docker.errors.NotFound:
                # Try with just the agent_id as container name
                try:
                    container = client.containers.get(f"ciris-{agent_id}")
                    container.restart(timeout=30)

                    logger.info(f"Agent {agent_id} restarted by {user['email']}")

                    return {
                        "status": "success",
                        "agent_id": agent_id,
                        "message": f"Agent {agent_id} is restarting",
                        "container": f"ciris-{agent_id}",
                    }
                except docker.errors.NotFound:
                    raise HTTPException(
                        status_code=404, detail=f"Container for agent '{agent_id}' not found"
                    )
            except docker.errors.APIError as e:
                logger.error(f"Docker API error restarting {agent_id}: {e}")
                raise HTTPException(
                    status_code=500, detail=f"Failed to restart container: {str(e)}"
                )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to restart agent {agent_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to restart agent: {str(e)}")

    @router.post("/agents/{agent_id}/maintenance")
    async def set_agent_maintenance(
        agent_id: str,
        request: Dict[str, bool],
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
        user: dict = auth_dependency,
    ) -> Dict[str, Any]:
        """
        Set maintenance mode for an agent to prevent automatic restart.

        When maintenance mode is enabled, the container manager will not
        automatically restart the agent if it crashes or stops.

        Body should contain: {"do_not_autostart": true/false}

        Supports composite keys for multi-instance deployments.
        """
        try:
            do_not_autostart = request.get("do_not_autostart", False)

            # Validate boolean
            if not isinstance(do_not_autostart, bool):
                raise HTTPException(
                    status_code=400, detail="do_not_autostart must be a boolean value"
                )

            # Resolve agent to ensure it exists
            _ = resolve_agent(agent_id, occurrence_id=occurrence_id, server_id=server_id)

            # Update the agent registry using composite key
            success = manager.agent_registry.set_do_not_autostart(
                agent_id, do_not_autostart, occurrence_id=occurrence_id, server_id=server_id
            )

            if not success:
                raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

            action = "enabled" if do_not_autostart else "disabled"
            logger.info(f"Maintenance mode {action} for {agent_id} by {user['email']}")

            return {
                "status": "success",
                "agent_id": agent_id,
                "do_not_autostart": do_not_autostart,
                "message": f"Maintenance mode {action} for agent {agent_id}",
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to set maintenance mode for {agent_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to set maintenance mode: {str(e)}")

    @router.get("/agents/{agent_id}/maintenance")
    async def get_agent_maintenance(
        agent_id: str,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
        user: dict = auth_dependency,
    ) -> Dict[str, Any]:
        """
        Get maintenance mode status for an agent.

        Supports composite keys for multi-instance deployments.
        """
        try:
            agent = resolve_agent(agent_id, occurrence_id=occurrence_id, server_id=server_id)

            do_not_autostart = hasattr(agent, "do_not_autostart") and agent.do_not_autostart

            return {
                "agent_id": agent_id,
                "do_not_autostart": do_not_autostart,
                "maintenance_mode": "enabled" if do_not_autostart else "disabled",
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to get maintenance mode for {agent_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to get maintenance mode: {str(e)}")

    @router.get("/agents/{agent_id}/config")
    async def get_agent_config(agent_id: str, user: dict = auth_dependency) -> Dict[str, Any]:
        """Get agent configuration from docker-compose.yml."""
        import yaml
        from pathlib import Path
        import re

        try:
            # Validate agent_id to prevent directory traversal
            if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9\-_]{0,63}$", agent_id):
                raise HTTPException(status_code=400, detail="Invalid agent ID format")

            # Path to agent's docker-compose file - use Path to safely join
            base_path = Path("/opt/ciris/agents")
            compose_path = (base_path / agent_id / "docker-compose.yml").resolve()

            # Ensure the resolved path is still within the agents directory
            if not str(compose_path).startswith(str(base_path)):
                raise HTTPException(status_code=400, detail="Invalid agent path")

            if not compose_path.exists():
                raise HTTPException(
                    status_code=404, detail=f"Agent '{agent_id}' configuration not found"
                )

            # Read docker-compose.yml
            async with aiofiles.open(compose_path, "r") as f:
                content = await f.read()
                compose_data = yaml.safe_load(content)

            # Extract environment variables
            environment = {}
            if "services" in compose_data:
                for service in compose_data["services"].values():
                    # First, load from env_file if specified
                    if "env_file" in service:
                        env_files = service["env_file"]
                        if not isinstance(env_files, list):
                            env_files = [env_files]

                        for env_file in env_files:
                            env_file_path = compose_path.parent / env_file
                            if env_file_path.exists():
                                async with aiofiles.open(env_file_path, "r") as ef:
                                    content = await ef.read()
                                    for line in content.split("\n"):
                                        line = line.strip()
                                        if line and not line.startswith("#") and "=" in line:
                                            key, value = line.split("=", 1)
                                            # Remove quotes if present
                                            value = value.strip()
                                            if (value.startswith('"') and value.endswith('"')) or (
                                                value.startswith("'") and value.endswith("'")
                                            ):
                                                value = value[1:-1]
                                            environment[key.strip()] = value

                    # Then, override with explicit environment variables
                    if "environment" in service:
                        environment.update(service["environment"])
                    break

            return {
                "agent_id": agent_id,
                "environment": environment,
                "compose_file": str(compose_path),
            }

        except HTTPException:
            raise  # Re-raise HTTP exceptions as-is
        except FileNotFoundError:
            raise HTTPException(
                status_code=404, detail=f"Configuration not found for agent '{agent_id}'"
            )
        except Exception as e:
            logger.error(f"Failed to get agent config: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.patch("/agents/{agent_id}/config")
    async def update_agent_config(
        agent_id: str, config_update: Dict[str, Any], user: dict = auth_dependency
    ) -> Dict[str, str]:
        """Update agent configuration by modifying docker-compose.yml."""
        import yaml
        import subprocess
        from pathlib import Path
        import re

        try:
            # Validate agent_id to prevent directory traversal
            if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9\-_]{0,63}$", agent_id):
                raise HTTPException(status_code=400, detail="Invalid agent ID format")

            # Path to agent's docker-compose file - use Path to safely join
            base_path = Path("/opt/ciris/agents")
            compose_path = (base_path / agent_id / "docker-compose.yml").resolve()

            # Ensure the resolved path is still within the agents directory
            if not str(compose_path).startswith(str(base_path)):
                raise HTTPException(status_code=400, detail="Invalid agent path")

            if not compose_path.exists():
                raise HTTPException(
                    status_code=404, detail=f"Agent '{agent_id}' configuration not found"
                )

            # Read current docker-compose.yml
            async with aiofiles.open(compose_path, "r") as f:
                content = await f.read()
                compose_data = yaml.safe_load(content)

            # Update environment variables
            if "environment" in config_update:
                if "services" in compose_data:
                    for service in compose_data["services"].values():
                        if "environment" in service:
                            # Special handling for CIRIS_ENABLE_DISCORD
                            if "CIRIS_ENABLE_DISCORD" in config_update["environment"]:
                                # Get current CIRIS_ADAPTER value
                                current_adapter = service["environment"].get("CIRIS_ADAPTER", "api")
                                adapters = [a.strip() for a in current_adapter.split(",")]

                                # Add or remove discord based on the toggle
                                enable_discord = (
                                    config_update["environment"]["CIRIS_ENABLE_DISCORD"] == "true"
                                )
                                if enable_discord:
                                    if "discord" not in adapters:
                                        adapters.append("discord")
                                else:
                                    if "discord" in adapters:
                                        adapters.remove("discord")

                                # Update CIRIS_ADAPTER with modified list
                                service["environment"]["CIRIS_ADAPTER"] = ",".join(adapters)

                                # Don't save CIRIS_ENABLE_DISCORD itself
                                del config_update["environment"]["CIRIS_ENABLE_DISCORD"]

                            # Update other environment variables
                            # Handle deletions (when value is None or empty string from UI)
                            for key, value in config_update["environment"].items():
                                if value is None or value == "":
                                    # Remove the variable if it exists
                                    service["environment"].pop(key, None)
                                else:
                                    # Update or add the variable
                                    service["environment"][key] = value

            # Backup current config
            backup_path = compose_path.with_suffix(".yml.bak")

            # Try to create backup, handling permission issues gracefully
            try:
                # Read the original content
                async with aiofiles.open(compose_path, "r") as f:
                    original_content = await f.read()

                # Try to write backup
                try:
                    async with aiofiles.open(backup_path, "w") as f:
                        await f.write(original_content)
                except PermissionError:
                    # If we can't write backup, that's okay - continue with update
                    logger.warning(
                        f"Could not create backup file at {backup_path} - continuing without backup"
                    )
            except Exception as e:
                logger.warning(f"Could not read original file for backup: {e}")

            # Write updated docker-compose.yml
            content = yaml.dump(compose_data, default_flow_style=False, sort_keys=False)

            # Try to write directly first
            try:
                async with aiofiles.open(compose_path, "w") as f:
                    await f.write(content)
            except PermissionError:
                # If direct write fails, write to temp location and move
                import tempfile
                import shutil

                # Write to temp file in /tmp (always writable)
                with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as tmp:
                    tmp.write(content)
                    temp_path = tmp.name

                # Try to move file - this might work even if direct write doesn't
                try:
                    shutil.move(temp_path, str(compose_path))
                except Exception as move_error:
                    # Clean up temp file
                    try:
                        Path(temp_path).unlink()
                    except Exception:
                        pass
                    raise RuntimeError(f"Failed to update config file: {move_error}")

            # Check if we should restart the container
            should_restart = config_update.get(
                "restart", True
            )  # Default to True for backward compatibility

            if should_restart:
                # Get agent from registry to check server location
                # Note: For this endpoint, agent_id is path param and we need to use the same lookup
                # The config file is already validated to exist, so we can safely get the agent
                try:
                    agent = manager.agent_registry.get_agent(agent_id)
                except Exception:
                    agent = None

                if not agent:
                    raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

                server_id = agent.server_id if hasattr(agent, "server_id") else "main"

                # Use different recreation strategy for remote vs local agents
                if server_id != "main":
                    # Remote server - use Docker API to avoid port conflicts
                    from ciris_manager.deployment import get_deployment_orchestrator

                    orchestrator = get_deployment_orchestrator()
                    success = await orchestrator._recreate_agent_container(
                        agent_id, server_id=server_id, new_image=None
                    )
                    if not success:
                        raise RuntimeError("Failed to recreate remote agent container")
                else:
                    # Local server - use docker-compose
                    agent_dir = Path("/opt/ciris/agents") / agent_id
                    proc = await asyncio.create_subprocess_exec(
                        "docker-compose",
                        "up",
                        "-d",
                        cwd=str(agent_dir),
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    stdout, stderr = await proc.communicate()
                    if proc.returncode != 0:
                        raise RuntimeError(f"Failed to recreate container: {stderr.decode()}")

                logger.info(f"Agent {agent_id} config updated and restarted by {user['email']}")
                return {
                    "status": "updated",
                    "agent_id": agent_id,
                    "message": "Configuration updated and container recreated",
                }
            else:
                logger.info(f"Agent {agent_id} config updated (no restart) by {user['email']}")
                return {
                    "status": "updated",
                    "agent_id": agent_id,
                    "message": "Configuration saved. Changes will be applied on next restart.",
                }

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to recreate container: {e}")
            raise HTTPException(status_code=500, detail="Failed to apply configuration")
        except Exception as e:
            logger.error(f"Failed to update agent config: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/agents/{agent_id}/oauth/verify")
    async def verify_agent_oauth(
        agent_id: str,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
        user: dict = auth_dependency,
    ) -> Dict[str, Any]:
        """
        Verify OAuth configuration for an agent.

        Checks if OAuth is properly configured and working.

        Supports composite keys for multi-instance deployments.
        """
        # Get agent from registry
        agent = resolve_agent(agent_id, occurrence_id=occurrence_id, server_id=server_id)

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
            },
        }

    @router.post("/agents/{agent_id}/oauth/complete")
    async def mark_oauth_complete(
        agent_id: str,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
        user: dict = auth_dependency,
    ) -> Dict[str, str]:
        """
        Mark OAuth as configured for an agent.

        Called after admin has registered callback URLs in provider dashboards.

        Supports composite keys for multi-instance deployments.
        """
        # Get agent from registry
        agent = resolve_agent(agent_id, occurrence_id=occurrence_id, server_id=server_id)

        # Update OAuth status
        agent.oauth_status = "configured"

        # Save to registry
        manager.agent_registry.save_metadata()

        logger.info(f"OAuth marked as configured for agent {agent_id} by {user['email']}")

        return {
            "status": "success",
            "agent_id": agent_id,
            "oauth_status": "configured",
            "message": "OAuth configuration marked as complete. Run verification to test.",
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
                desc = f"{template_name.replace('-', ' ').title()} agent template"
                all_templates[template_name] = desc

        # For development: if no manifest exists, treat some templates as pre-approved
        if not pre_approved and all_templates:
            # Common templates that don't need special approval
            default_pre_approved = ["echo", "scout", "sage", "test"]
            pre_approved_list = [t for t in default_pre_approved if t in all_templates]
        else:
            pre_approved_list = list(pre_approved.keys())

        return TemplateListResponse(templates=all_templates, pre_approved=pre_approved_list)

    @router.get("/templates/{template_name}/details")
    async def get_template_details(template_name: str) -> Dict[str, Any]:
        """Get detailed information about a specific template including stewardship tier."""
        from pathlib import Path
        import yaml
        import re

        # Validate template name to prevent path traversal
        if not re.match(r"^[a-zA-Z0-9_-]+$", template_name):
            raise HTTPException(status_code=400, detail="Invalid template name")

        # Additional check for path traversal attempts
        if ".." in template_name or "/" in template_name or "\\" in template_name:
            raise HTTPException(status_code=400, detail="Invalid template name")

        templates_dir = Path(manager.config.manager.templates_directory)
        template_file = templates_dir / f"{template_name}.yaml"

        # Ensure the resolved path is within the templates directory
        try:
            template_file = template_file.resolve()
            templates_dir_resolved = templates_dir.resolve()
            if not str(template_file).startswith(str(templates_dir_resolved)):
                raise HTTPException(status_code=400, detail="Invalid template path")
        except (OSError, RuntimeError):
            raise HTTPException(status_code=400, detail="Invalid template path")

        if not template_file.exists():
            raise HTTPException(status_code=404, detail=f"Template '{template_name}' not found")

        try:
            async with aiofiles.open(template_file, "r") as f:
                content = await f.read()
                template_data = yaml.safe_load(content)

            # Extract stewardship tier from stewardship section
            stewardship_tier = template_data.get("stewardship", {}).get("stewardship_tier", 1)

            return {
                "name": template_name,
                "description": template_data.get("description", ""),
                "stewardship_tier": stewardship_tier,
                "requires_wa_review": stewardship_tier >= 4,
            }
        except Exception as e:
            logger.error(f"Failed to load template {template_name}: {e}")
            raise HTTPException(status_code=500, detail="Failed to load template details")

    @router.get("/env/default")
    async def get_default_env(user: dict = auth_dependency) -> Dict[str, str]:
        """Get default environment variables for agent creation."""
        from pathlib import Path

        # Try to read from production .env file first
        env_file_path = Path("/home/ciris/.env")
        if env_file_path.exists():
            try:
                async with aiofiles.open(env_file_path, "r") as f:
                    content = await f.read()
                # Filter out sensitive values and keep only keys we want to expose
                lines = []
                sensitive_keys = {
                    "DISCORD_BOT_TOKEN",
                    "OPENAI_API_KEY",
                    "CIRIS_OPENAI_API_KEY_2",
                    "CIRIS_OPENAI_VISION_KEY",
                }

                for line in content.split("\n"):
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key = line.split("=", 1)[0].strip()
                        # Keep the key but clear sensitive values
                        if key in sensitive_keys:
                            lines.append(f"{key}=")
                        else:
                            lines.append(line)

                # Add any missing essential keys
                existing_keys = {line.split("=")[0] for line in lines if "=" in line}
                if "CIRIS_API_PORT" not in existing_keys:
                    lines.append("CIRIS_API_PORT=8080")
                if "CIRIS_API_HOST" not in existing_keys:
                    lines.append("CIRIS_API_HOST=0.0.0.0")

                return {"content": "\n".join(lines)}
            except Exception as e:
                logger.warning(f"Failed to read default .env file: {e}")

        # Fallback to hardcoded defaults if file doesn't exist
        env_vars = [
            # Core CIRIS requirements
            "LLM_PROVIDER=openai",
            "OPENAI_API_KEY=",  # User must provide
            "DATABASE_URL=sqlite:////app/data/ciris_engine.db",
            "CIRIS_API_HOST=0.0.0.0",
            "CIRIS_API_PORT=8080",  # Will be dynamically assigned
            "JWT_SECRET_KEY=generate-with-openssl-rand-hex-32",
            "ENVIRONMENT=production",
            "LOG_LEVEL=INFO",
            # Discord
            "DISCORD_BOT_TOKEN=",
            "DISCORD_CHANNEL_IDS=",
            "DISCORD_DEFERRAL_CHANNEL_ID=",
            "WA_USER_IDS=",
            # OAuth
            "OAUTH_CALLBACK_BASE_URL=https://agents.ciris.ai",
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

    # Deployment token management endpoint (protected)
    @router.get("/deployment/tokens")
    async def get_deployment_tokens(
        _user: Dict[str, str] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """
        Get deployment tokens for GitHub secrets configuration.
        Only accessible to @ciris.ai users.
        """
        return {
            "status": "success",
            "tokens": {
                "CIRISAI/CIRISAgent": {
                    "secret_name": "DEPLOY_TOKEN",
                    "secret_value": DEPLOY_TOKENS.get("agent", ""),
                },
                "CIRISAI/CIRISGUI": {
                    "secret_name": "DEPLOY_TOKEN",
                    "secret_value": DEPLOY_TOKENS.get("gui", ""),
                },
            },
            "instructions": "Add these as repository secrets in GitHub Settings > Secrets and variables > Actions",
        }

    # CD Orchestration endpoints
    @router.post("/updates/notify")
    async def notify_update(
        notification: UpdateNotification, _user: Dict[str, str] = Depends(deployment_auth)
    ) -> Dict[str, Any]:
        """
        Receive update notification from CD pipeline.

        This is the single API call from GitHub Actions to trigger deployment.
        CIRISManager evaluates and stages if needed (Wisdom-Based Deferral).
        """
        try:
            # Validate repo authorization for the provided images
            source_repo = _user.get("source_repo", "legacy")

            # Enforce repo-specific image restrictions
            if source_repo == "agent":
                # Agent repo can only update agent images
                if notification.gui_image or notification.nginx_image:
                    raise HTTPException(
                        status_code=403, detail="Agent repository can only update agent images"
                    )
                if not notification.agent_image:
                    raise HTTPException(
                        status_code=400, detail="Agent repository must provide agent_image"
                    )
            elif source_repo == "gui":
                # GUI repo can only update GUI images
                if notification.agent_image or notification.nginx_image:
                    raise HTTPException(
                        status_code=403, detail="GUI repository can only update GUI images"
                    )
                if not notification.gui_image:
                    raise HTTPException(
                        status_code=400, detail="GUI repository must provide gui_image"
                    )
            # Legacy token can update anything (backwards compatibility)

            # Get current agents with runtime status
            from ciris_manager.docker_discovery import DockerAgentDiscovery

            discovery = DockerAgentDiscovery(
                manager.agent_registry, docker_client_manager=manager.docker_client
            )
            agents = discovery.discover_agents()

            # Evaluate and potentially stage deployment
            deployment_id = await deployment_orchestrator.evaluate_and_stage(notification, agents)

            # Check if deployment was staged or started immediately
            if deployment_id in deployment_orchestrator.pending_deployments:
                staged_status = deployment_orchestrator.pending_deployments[deployment_id]
                logger.info(f"Staged deployment {deployment_id} for human review")

                # Determine deployment type for clearer messaging
                deployment_type = "Update"
                if "GUI" in staged_status.message:
                    deployment_type = "GUI Update"
                elif staged_status.agents_total > 0:
                    deployment_type = "Agent Update"

                return {
                    "deployment_id": deployment_id,
                    "status": "staged",
                    "message": f"{deployment_type} staged for human review (Wisdom-Based Deferral)",
                    "agents_affected": staged_status.agents_total,
                    "deployment_type": deployment_type.lower().replace(" ", "_"),
                }
            else:
                deploy_status: Optional[DeploymentStatus] = deployment_orchestrator.deployments.get(
                    deployment_id
                )
                if deploy_status:
                    logger.info(f"Auto-started low-risk deployment {deployment_id}")
                    return {
                        "deployment_id": deployment_id,
                        "status": deploy_status.status,
                        "message": deploy_status.message,
                        "agents_affected": deploy_status.agents_total,
                    }
                else:
                    # No-op deployment (no updates needed)
                    return {
                        "deployment_id": deployment_id,
                        "status": "completed",
                        "message": "No updates needed",
                        "agents_affected": 0,
                    }

        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except Exception as e:
            logger.error(f"Failed to process update notification: {e}")
            raise HTTPException(status_code=500, detail="Failed to process update")

    @router.get("/updates/events/{deployment_id}")
    async def get_deployment_events(
        deployment_id: str, _user: Dict[str, str] = auth_dependency
    ) -> Dict[str, Any]:
        """Get timeline of events for a specific deployment."""
        deployment = deployment_orchestrator.deployments.get(
            deployment_id
        ) or deployment_orchestrator.pending_deployments.get(deployment_id)

        if not deployment:
            raise HTTPException(status_code=404, detail="Deployment not found")

        return {
            "deployment_id": deployment_id,
            "status": deployment.status,
            "events": deployment.events if hasattr(deployment, "events") else [],
            "started_at": deployment.started_at,
            "completed_at": deployment.completed_at,
        }

    @router.get("/updates/status", response_model=Optional[DeploymentStatus])
    async def get_deployment_status(
        deployment_id: Optional[str] = None, _user: Dict[str, str] = auth_dependency
    ) -> Optional[DeploymentStatus]:
        """
        Get deployment status.

        If deployment_id is not provided, returns current active deployment.
        """
        if deployment_id:
            return await deployment_orchestrator.get_deployment_status(deployment_id)
        else:
            return await deployment_orchestrator.get_current_deployment()

    @router.get("/updates/pending/all")
    async def get_all_pending_deployments(
        _user: Dict[str, str] = auth_dependency,
    ) -> Dict[str, Any]:
        """
        Get all pending deployments (supports multiple staged deployments).

        Returns all staged deployments and information about what 'latest' points to.
        """
        # Get all pending deployments
        all_pending = []
        for deployment_id, deployment in deployment_orchestrator.pending_deployments.items():
            dep_info = {
                "deployment_id": deployment_id,
                "staged_at": deployment.staged_at,
                "affected_agents": deployment.agents_total,
                "status": deployment.status,
            }
            if deployment.notification:
                dep_info.update(
                    {
                        "agent_image": deployment.notification.agent_image,
                        "gui_image": deployment.notification.gui_image,
                        "strategy": deployment.notification.strategy,
                        "message": deployment.notification.message,
                        "version": deployment.notification.version,
                        "commit_sha": deployment.notification.commit_sha,
                    }
                )
            all_pending.append(dep_info)

        # Sort by staged_at (newest first)
        all_pending.sort(key=lambda x: str(x.get("staged_at", "")), reverse=True)

        # Get current 'latest' tag info
        latest_info = {}
        try:
            # Try to get digest of current latest tag locally
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "images",
                "ghcr.io/cirisai/ciris-agent:latest",
                "--format",
                "{{.ID}}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                stdout = b""

            if proc.returncode == 0 and stdout.strip():
                latest_info["local_image_id"] = stdout.decode().strip()[:12]  # Short ID

            # Try to get what version is currently running
            agents = (
                await deployment_orchestrator.manager.get_agent_statuses()
                if deployment_orchestrator.manager
                else []
            )
            if agents:
                # Get version from first agent (they should all be the same in production)
                for agent in agents:
                    if agent.get("is_running"):
                        latest_info["running_version"] = agent.get("current_version", "unknown")
                        break
        except Exception as e:
            logger.warning(f"Could not get latest tag info: {e}")

        return {
            "deployments": all_pending,
            "latest_tag": latest_info,
            "total_pending": len(all_pending),
        }

    @router.get("/updates/pending")
    async def get_pending_deployment(_user: Dict[str, str] = auth_dependency) -> Dict[str, Any]:
        """
        Get pending deployment details if any.

        Returns staged deployment waiting for operator approval or failed deployment blocking new ones.
        """
        # First check for actual pending deployments
        pending = await deployment_orchestrator.get_pending_deployment()
        if pending:
            result = {
                "pending": True,
                "deployment_id": pending.deployment_id,
                "staged_at": pending.staged_at,
                "affected_agents": pending.agents_total,
            }
            if pending.notification:
                result.update(
                    {
                        "agent_image": pending.notification.agent_image,
                        "gui_image": pending.notification.gui_image,
                        "strategy": pending.notification.strategy,
                        "message": pending.notification.message,
                        "version": pending.notification.version,
                        "commit_sha": pending.notification.commit_sha,
                    }
                )
            return result

        # Check if there's a failed deployment blocking new ones
        current = await deployment_orchestrator.get_current_deployment()
        if current and current.status == "failed":
            result = {
                "pending": True,  # Still blocking, so return true
                "deployment_id": current.deployment_id,
                "status": "failed",
                "staged_at": current.started_at,
                "affected_agents": current.agents_total,
                "message": current.message or "Deployment failed",
            }
            if current.notification:
                result.update(
                    {
                        "agent_image": current.notification.agent_image,
                        "gui_image": current.notification.gui_image,
                        "strategy": current.notification.strategy,
                        "version": current.notification.version,
                        "commit_sha": current.notification.commit_sha,
                    }
                )
            return result

        return {"pending": False}

    @router.get("/updates/preview/{deployment_id}")
    async def preview_deployment(
        deployment_id: str, _user: Dict[str, str] = auth_dependency
    ) -> Dict[str, Any]:
        """
        Get a preview of what a deployment will do.
        Shows which agents need updates and which are already current.
        Designed for scale - efficiently checks all agents.
        """
        preview = await deployment_orchestrator.get_deployment_preview(deployment_id)
        return preview

    @router.get("/updates/shutdown-reasons/{deployment_id}")
    async def get_shutdown_reasons(
        deployment_id: str, _user: Dict[str, str] = auth_dependency
    ) -> Dict[str, Any]:
        """Get the shutdown reasons that will be sent to each agent."""
        return await deployment_orchestrator.get_shutdown_reasons_preview(deployment_id)

    @router.post("/updates/launch")
    async def launch_deployment(
        request: Dict[str, str], _user: Dict[str, str] = auth_dependency
    ) -> Dict[str, str]:
        """
        Launch a staged deployment.

        Requires operator approval to start canary rollout.
        """
        deployment_id = request.get("deployment_id")
        if not deployment_id:
            raise HTTPException(status_code=400, detail="deployment_id required")

        success = await deployment_orchestrator.launch_staged_deployment(deployment_id)
        if success:
            return {"status": "launched", "deployment_id": deployment_id}
        else:
            raise HTTPException(status_code=404, detail="Deployment not found or not pending")

    @router.post("/updates/cancel")
    async def cancel_deployment(
        request: Dict[str, str], _user: Dict[str, str] = auth_dependency
    ) -> Dict[str, str]:
        """
        Cancel a stuck deployment.

        Clears the deployment lock to allow starting a new deployment.
        """
        deployment_id = request.get("deployment_id")
        reason = request.get("reason", "Cancelled due to stuck state")

        if not deployment_id:
            raise HTTPException(status_code=400, detail="deployment_id required")

        success = await deployment_orchestrator.cancel_stuck_deployment(deployment_id, reason)
        if success:
            return {"status": "cancelled", "deployment_id": deployment_id}
        else:
            raise HTTPException(status_code=404, detail="Deployment not found")

    @router.post("/updates/reject")
    async def reject_deployment(
        request: Dict[str, str], _user: Dict[str, str] = auth_dependency
    ) -> Dict[str, str]:
        """
        Reject a staged deployment.

        Cancels the deployment and logs the rejection reason.
        """
        deployment_id = request.get("deployment_id")
        reason = request.get("reason", "Rejected by operator")

        if not deployment_id:
            raise HTTPException(status_code=400, detail="deployment_id required")

        success = await deployment_orchestrator.reject_staged_deployment(deployment_id, reason)
        if success:
            return {"status": "rejected", "deployment_id": deployment_id}
        else:
            raise HTTPException(status_code=404, detail="Deployment not found or not pending")

    @router.post("/updates/pause")
    async def pause_deployment(
        request: Dict[str, str], _user: Dict[str, str] = auth_dependency
    ) -> Dict[str, str]:
        """
        Pause an active deployment.

        Stops further agent updates but keeps deployment active.
        """
        deployment_id = request.get("deployment_id")
        if not deployment_id:
            raise HTTPException(status_code=400, detail="deployment_id required")

        success = await deployment_orchestrator.pause_deployment(deployment_id)
        if success:
            return {"status": "paused", "deployment_id": deployment_id}
        else:
            raise HTTPException(status_code=404, detail="Deployment not found or not active")

    @router.post("/updates/rollback")
    async def rollback_deployment(
        request: Dict[str, Any], _user: Dict[str, str] = auth_dependency
    ) -> Dict[str, str]:
        """
        Rollback a deployment.

        Reverts updated agents to specified or previous version.

        Request body:
        {
            "deployment_id": "deploy-123",
            "target_version": "n-1" | "n-2" | "specific-version",  # Optional, defaults to n-1
            "target_versions": {  # Optional, for granular control
                "agents": {"agent1": "n-1", "agent2": "n-2"},
                "gui": "n-1",
                "nginx": "n-2"
            }
        }
        """
        deployment_id = request.get("deployment_id")
        if not deployment_id:
            raise HTTPException(status_code=400, detail="deployment_id required")

        target_version = request.get("target_version", "n-1")
        target_versions = request.get("target_versions", None)

        success = await deployment_orchestrator.rollback_deployment(
            deployment_id, target_version=target_version, target_versions=target_versions
        )
        if success:
            return {
                "status": "rolling_back",
                "deployment_id": deployment_id,
                "target_version": target_version,
            }
        else:
            raise HTTPException(status_code=404, detail="Deployment not found")

    @router.get("/updates/current-images")
    async def get_current_images(_user: Dict[str, str] = auth_dependency) -> Dict[str, Any]:
        """Get current running container images."""
        images = await deployment_orchestrator.get_current_images()
        return images

    @router.get("/updates/history")
    async def get_deployment_history(
        limit: int = 10, _user: Dict[str, str] = auth_dependency
    ) -> Dict[str, Any]:
        """Get deployment history."""
        history = await deployment_orchestrator.get_deployment_history(limit)
        return {"deployments": history}

    @router.get("/updates/rollback-options")
    async def get_rollback_options(_user: Dict[str, str] = auth_dependency) -> Dict[str, Any]:
        """
        Get available rollback options for all container types.
        Returns n-1 and n-2 versions for agents, GUI, and nginx containers.
        Uses DeploymentOrchestrator as single source of truth.
        """
        # Get rollback options from deployment history
        # For now, return empty structure - TODO: implement rollback from deployment history
        result = {
            "agent": {
                "current": None,  # TODO: Get from deployment orchestrator
                "n_minus_1": None,  # TODO: Get from deployment history
                "n_minus_2": None,  # TODO: Get from deployment history
            },
            "gui": {
                "current": None,  # GUI tracked separately
                "n_minus_1": None,
                "n_minus_2": None,
            },
            "nginx": {
                "current": None,  # Nginx rarely changes
                "n_minus_1": None,
                "n_minus_2": None,
            },
            # Legacy support
            "agents": {},  # Deprecated - use "agent" instead
        }

        return result

    @router.get("/updates/rollback/{deployment_id}/versions")
    async def get_rollback_versions(
        deployment_id: str, _user: Dict[str, str] = auth_dependency
    ) -> Dict[str, Any]:
        """
        Get available rollback versions for a deployment.

        Returns version history for all components that can be rolled back.
        """
        versions = await deployment_orchestrator.get_rollback_versions(deployment_id)
        if not versions:
            raise HTTPException(
                status_code=404, detail="Deployment not found or no versions available"
            )
        return versions

    @router.get("/updates/rollback-proposals")
    async def get_rollback_proposals(_user: Dict[str, str] = auth_dependency) -> Dict[str, Any]:
        """Get active rollback proposals requiring operator decision."""
        proposals = getattr(deployment_orchestrator, "rollback_proposals", {})

        # Return active proposals
        active_proposals = []
        for deployment_id, proposal in proposals.items():
            if deployment_id in deployment_orchestrator.deployments:
                deployment = deployment_orchestrator.deployments[deployment_id]
                if deployment.status == "rollback_proposed":
                    active_proposals.append(proposal)

        return {"proposals": active_proposals, "count": len(active_proposals)}

    @router.post("/updates/approve-rollback")
    async def approve_rollback(
        request: Dict[str, Any], _user: Dict[str, str] = auth_dependency
    ) -> Dict[str, Any]:
        """Approve a proposed rollback."""
        deployment_id = request.get("deployment_id")
        if not deployment_id:
            raise HTTPException(status_code=400, detail="deployment_id required")

        proposals = getattr(deployment_orchestrator, "rollback_proposals", {})
        if deployment_id not in proposals:
            raise HTTPException(status_code=404, detail="Rollback proposal not found")

        # Execute the rollback
        success = await deployment_orchestrator.rollback_deployment(deployment_id)

        if success:
            # Remove proposal
            del proposals[deployment_id]
            return {"status": "rollback_started", "deployment_id": deployment_id}
        else:
            raise HTTPException(status_code=404, detail="Deployment not found")

    @router.post("/updates/deploy-single")
    async def deploy_single_agent(
        request: Dict[str, Any], _user: Dict[str, str] = auth_dependency
    ) -> Dict[str, Any]:
        """
        Deploy a specific version to a single agent for testing.

        This endpoint allows targeted deployment to individual agents,
        respecting the consensual deployment system.

        Request body:
        {
            "agent_id": "datum",
            "agent_image": "ghcr.io/cirisai/ciris-agent:v1.4.5",
            "message": "Testing new feature X",
            "strategy": "immediate",  # immediate recommended for single agent
            "metadata": {...}
        }
        """
        agent_id = request.get("agent_id")
        agent_image = request.get("agent_image")
        message = request.get("message", "Single agent test deployment")
        strategy = request.get("strategy", "immediate")
        metadata = request.get("metadata", {})
        occurrence_id = request.get("occurrence_id")
        server_id = request.get("server_id")

        if not agent_id:
            raise HTTPException(status_code=400, detail="agent_id is required")
        if not agent_image:
            raise HTTPException(status_code=400, detail="agent_image is required")

        # Validate the agent exists using composite key resolution
        resolve_agent(agent_id, occurrence_id=occurrence_id, server_id=server_id)

        # Get the discovered agent info
        from ciris_manager.docker_discovery import DockerAgentDiscovery

        discovery = DockerAgentDiscovery(
            manager.agent_registry, docker_client_manager=manager.docker_client
        )
        agents = discovery.discover_agents()

        # Match by agent_id, occurrence_id, and server_id
        target_agent = next(
            (
                a
                for a in agents
                if a.agent_id == agent_id
                and (occurrence_id is None or a.occurrence_id == occurrence_id)
                and (server_id is None or a.server_id == server_id)
            ),
            None,
        )
        if not target_agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

        # Create a targeted update notification
        notification = UpdateNotification(
            agent_image=agent_image,
            gui_image=None,
            nginx_image=None,
            message=message,
            strategy=strategy,
            source="manager_ui",
            commit_sha=None,
            version=None,
            changelog=None,
            risk_level="low",
            metadata={
                **metadata,
                "single_agent_deployment": True,
                "target_agent": agent_id,
                "initiated_by": _user.get("email", "unknown"),
            },
        )

        # Start deployment for just this agent
        try:
            deployment_status = await deployment_orchestrator.start_single_agent_deployment(
                notification, target_agent
            )
        except ValueError as e:
            # Deployment already in progress
            raise HTTPException(status_code=409, detail=str(e))

        logger.info(
            f"Single agent deployment {deployment_status.deployment_id} started for {agent_id} "
            f"by {_user.get('email', 'unknown')}"
        )

        return {
            "deployment_id": deployment_status.deployment_id,
            "agent_id": agent_id,
            "status": deployment_status.status,
            "message": deployment_status.message,
            "image": agent_image,
        }

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

    @router.get("/canary/groups")
    async def get_canary_groups(_user: Dict[str, str] = auth_dependency) -> Dict[str, Any]:
        """Get agents organized by canary deployment groups."""
        from ciris_manager.docker_discovery import DockerAgentDiscovery

        discovery = DockerAgentDiscovery(
            manager.agent_registry, docker_client_manager=manager.docker_client
        )
        agents = discovery.discover_agents()

        # Get canary group assignments from registry
        groups: Dict[str, List[Dict[str, Any]]] = {
            "explorer": [],
            "early_adopter": [],
            "general": [],
            "unassigned": [],
        }

        for agent in agents:
            registry_agent = manager.agent_registry.get_agent(agent.agent_id)
            metadata = (
                registry_agent.metadata
                if registry_agent and hasattr(registry_agent, "metadata")
                else {}
            )
            group = metadata.get("canary_group", "unassigned")

            agent_data = {
                "agent_id": agent.agent_id,
                "agent_name": agent.agent_name,
                "status": agent.status,
                "version": agent.version or "unknown",
                "code_hash": agent.code_hash or "unknown",
                "last_updated": metadata.get("last_updated", "never"),
            }

            if group not in groups:
                group = "unassigned"
            groups[group].append(agent_data)

        # Calculate group sizes
        total = len(agents)
        group_stats = {
            "explorer": {
                "count": len(groups["explorer"]),
                "target_percentage": 10,
                "actual_percentage": round(len(groups["explorer"]) / total * 100)
                if total > 0
                else 0,
            },
            "early_adopter": {
                "count": len(groups["early_adopter"]),
                "target_percentage": 20,
                "actual_percentage": round(len(groups["early_adopter"]) / total * 100)
                if total > 0
                else 0,
            },
            "general": {
                "count": len(groups["general"]),
                "target_percentage": 70,
                "actual_percentage": round(len(groups["general"]) / total * 100)
                if total > 0
                else 0,
            },
            "unassigned": {
                "count": len(groups["unassigned"]),
                "target_percentage": 0,
                "actual_percentage": round(len(groups["unassigned"]) / total * 100)
                if total > 0
                else 0,
            },
        }

        return {"groups": groups, "stats": group_stats, "total_agents": total}

    @router.put("/canary/agent/{agent_id}/group")
    async def update_agent_canary_group(
        agent_id: str, request: Dict[str, str], _user: Dict[str, str] = auth_dependency
    ) -> Dict[str, str]:
        """Update an agent's canary deployment group."""
        group = request.get("group")
        valid_groups = ["explorer", "early_adopter", "general", "unassigned"]
        if group not in valid_groups:
            raise HTTPException(
                status_code=400, detail=f"Invalid group. Must be one of: {', '.join(valid_groups)}"
            )

        # Set to None if unassigned
        group_value = None if group == "unassigned" else group

        if manager.agent_registry.set_canary_group(agent_id, group_value):
            return {"status": "success", "agent_id": agent_id, "group": group}
        else:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

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

        discovery = DockerAgentDiscovery(
            manager.agent_registry, docker_client_manager=manager.docker_client
        )
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
                        "version": agent.version or "unknown",
                        "code_hash": agent.code_hash or "unknown",
                        "codename": agent.codename or "unknown",
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
                        "version": agent.version or "unknown",
                        "code_hash": agent.code_hash or "unknown",
                        "codename": agent.codename or "unknown",
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

    # Telemetry has been moved to external CIRISLens service

    # ==========================================================================
    # ADAPTER MANAGEMENT PROXY ROUTES
    # These routes proxy adapter management requests to agents using stored
    # service tokens for authentication. This allows the Manager GUI to manage
    # adapters without exposing credentials in client-side code.
    # ==========================================================================

    async def _get_agent_client_info(agent_id: str) -> tuple[str, Dict[str, str], "AgentInfo"]:
        """
        Get the base URL and auth headers for an agent.

        Returns:
            Tuple of (base_url, headers, agent_info)

        Raises:
            HTTPException: If agent not found or auth fails
        """
        from ciris_manager.docker_discovery import DockerAgentDiscovery
        from ciris_manager.agent_auth import get_agent_auth

        # Find the agent
        discovery = DockerAgentDiscovery(
            manager.agent_registry, docker_client_manager=manager.docker_client
        )
        agents = discovery.discover_agents()
        agent = next((a for a in agents if a.agent_id == agent_id), None)

        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

        # Get auth headers
        try:
            auth = get_agent_auth()
            headers = auth.get_auth_headers(
                agent.agent_id,
                occurrence_id=agent.occurrence_id,
                server_id=agent.server_id,
            )
        except ValueError as e:
            raise HTTPException(status_code=401, detail=str(e))

        # Get base URL
        try:
            server_config = manager.docker_client.get_server_config(agent.server_id)
            if server_config.is_local:
                base_url = f"http://localhost:{agent.api_port}"
            else:
                base_url = f"http://{server_config.vpc_ip}:{agent.api_port}"
        except Exception:
            base_url = f"http://localhost:{agent.api_port}"

        return base_url, headers, agent

    @router.get("/agents/{agent_id}/adapters")
    async def list_agent_adapters(
        agent_id: str,
        _user: Dict[str, str] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """
        List all adapters running on an agent.

        Proxies to agent's GET /v1/system/adapters endpoint.
        """
        base_url, headers, _ = await _get_agent_client_info(agent_id)

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(
                    f"{base_url}/v1/system/adapters",
                    headers=headers,
                )
                response.raise_for_status()
                result: Dict[str, Any] = response.json()
                return result
            except httpx.HTTPStatusError as e:
                raise HTTPException(
                    status_code=e.response.status_code,
                    detail=f"Agent returned error: {e.response.text}",
                )
            except Exception as e:
                raise HTTPException(
                    status_code=502,
                    detail=f"Failed to communicate with agent: {str(e)}",
                )

    @router.get("/agents/{agent_id}/adapters/types")
    async def list_agent_adapter_types(
        agent_id: str,
        _user: Dict[str, str] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """
        List available adapter types on an agent.

        Proxies to agent's GET /v1/system/adapters/types endpoint.
        """
        base_url, headers, _ = await _get_agent_client_info(agent_id)

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(
                    f"{base_url}/v1/system/adapters/types",
                    headers=headers,
                )
                response.raise_for_status()
                result: Dict[str, Any] = response.json()
                return result
            except httpx.HTTPStatusError as e:
                raise HTTPException(
                    status_code=e.response.status_code,
                    detail=f"Agent returned error: {e.response.text}",
                )
            except Exception as e:
                raise HTTPException(
                    status_code=502,
                    detail=f"Failed to communicate with agent: {str(e)}",
                )

    @router.get("/agents/{agent_id}/adapters/{adapter_id}")
    async def get_agent_adapter(
        agent_id: str,
        adapter_id: str,
        _user: Dict[str, str] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """
        Get status of a specific adapter on an agent.

        Proxies to agent's GET /v1/system/adapters/{adapter_id} endpoint.
        """
        base_url, headers, _ = await _get_agent_client_info(agent_id)

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(
                    f"{base_url}/v1/system/adapters/{adapter_id}",
                    headers=headers,
                )
                response.raise_for_status()
                result: Dict[str, Any] = response.json()
                return result
            except httpx.HTTPStatusError as e:
                raise HTTPException(
                    status_code=e.response.status_code,
                    detail=f"Agent returned error: {e.response.text}",
                )
            except Exception as e:
                raise HTTPException(
                    status_code=502,
                    detail=f"Failed to communicate with agent: {str(e)}",
                )

    @router.post("/agents/{agent_id}/adapters/{adapter_type}")
    async def load_agent_adapter(
        agent_id: str,
        adapter_type: str,
        request: Request,
        adapter_id: Optional[str] = None,
        _user: Dict[str, str] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """
        Load/create a new adapter on an agent.

        Proxies to agent's POST /v1/system/adapters/{adapter_type} endpoint.

        Request body should contain:
        {
            "config": {
                "adapter_type": "string",
                "enabled": true,
                "settings": {...},
                "adapter_config": {...}
            },
            "auto_start": true
        }
        """
        base_url, headers, _ = await _get_agent_client_info(agent_id)

        # Get request body
        try:
            body = await request.json()
        except Exception:
            body = {}

        # Build query params
        params = {}
        if adapter_id:
            params["adapter_id"] = adapter_id

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(
                    f"{base_url}/v1/system/adapters/{adapter_type}",
                    headers={**headers, "Content-Type": "application/json"},
                    json=body,
                    params=params,
                )
                response.raise_for_status()
                result: Dict[str, Any] = response.json()
                return result
            except httpx.HTTPStatusError as e:
                raise HTTPException(
                    status_code=e.response.status_code,
                    detail=f"Agent returned error: {e.response.text}",
                )
            except Exception as e:
                raise HTTPException(
                    status_code=502,
                    detail=f"Failed to communicate with agent: {str(e)}",
                )

    @router.put("/agents/{agent_id}/adapters/{adapter_id}/reload")
    async def reload_agent_adapter(
        agent_id: str,
        adapter_id: str,
        request: Request,
        _user: Dict[str, str] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """
        Reload an adapter on an agent with new configuration.

        Proxies to agent's PUT /v1/system/adapters/{adapter_id}/reload endpoint.

        Request body should contain:
        {
            "config": {...},
            "auto_start": true
        }
        """
        base_url, headers, _ = await _get_agent_client_info(agent_id)

        # Get request body
        try:
            body = await request.json()
        except Exception:
            body = {"auto_start": True}

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.put(
                    f"{base_url}/v1/system/adapters/{adapter_id}/reload",
                    headers={**headers, "Content-Type": "application/json"},
                    json=body,
                )
                response.raise_for_status()
                result: Dict[str, Any] = response.json()
                return result
            except httpx.HTTPStatusError as e:
                raise HTTPException(
                    status_code=e.response.status_code,
                    detail=f"Agent returned error: {e.response.text}",
                )
            except Exception as e:
                raise HTTPException(
                    status_code=502,
                    detail=f"Failed to communicate with agent: {str(e)}",
                )

    @router.delete("/agents/{agent_id}/adapters/{adapter_id}")
    async def unload_agent_adapter(
        agent_id: str,
        adapter_id: str,
        _user: Dict[str, str] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """
        Unload/stop an adapter on an agent.

        Proxies to agent's DELETE /v1/system/adapters/{adapter_id} endpoint.
        """
        base_url, headers, _ = await _get_agent_client_info(agent_id)

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.delete(
                    f"{base_url}/v1/system/adapters/{adapter_id}",
                    headers=headers,
                )
                response.raise_for_status()
                result: Dict[str, Any] = response.json()
                return result
            except httpx.HTTPStatusError as e:
                raise HTTPException(
                    status_code=e.response.status_code,
                    detail=f"Agent returned error: {e.response.text}",
                )
            except Exception as e:
                raise HTTPException(
                    status_code=502,
                    detail=f"Failed to communicate with agent: {str(e)}",
                )

    # End of adapter management routes
    # ==========================================================================

    print("CRITICAL DEBUG: Before jailbreaker initialization section", flush=True)
    print("CRITICAL DEBUG: About to call logger.info", flush=True)
    logger.info("DEBUG: About to start jailbreaker initialization block")
    print("CRITICAL DEBUG: logger.info call completed", flush=True)

    # DEBUG: Log actual environment variables
    discord_client_id = os.getenv("DISCORD_CLIENT_ID")
    discord_client_secret = os.getenv("DISCORD_CLIENT_SECRET")
    print(
        f"CRITICAL DEBUG: Environment check - DISCORD_CLIENT_ID exists: {bool(discord_client_id)}",
        flush=True,
    )
    print(
        f"CRITICAL DEBUG: Environment check - DISCORD_CLIENT_SECRET exists: {bool(discord_client_secret)}",
        flush=True,
    )
    logger.info(f"DEBUG: Environment check - DISCORD_CLIENT_ID exists: {bool(discord_client_id)}")
    logger.info(
        f"DEBUG: Environment check - DISCORD_CLIENT_SECRET exists: {bool(discord_client_secret)}"
    )

    # Initialize jailbreaker service if configured
    try:
        print("CRITICAL DEBUG: Entering jailbreaker try block", flush=True)
        logger.info("Starting jailbreaker initialization...")
        from ciris_manager.jailbreaker import (
            JailbreakerConfig,
            JailbreakerService,
            create_jailbreaker_routes,
        )
        from pathlib import Path

        print("CRITICAL DEBUG: Jailbreaker imports successful", flush=True)
        logger.info("Jailbreaker imports successful")

        # Check if Discord credentials are available
        discord_client_id = os.getenv("DISCORD_CLIENT_ID")
        discord_client_secret = os.getenv("DISCORD_CLIENT_SECRET")
        print(
            f"CRITICAL DEBUG: Discord credentials - client_id={bool(discord_client_id)}, client_secret={bool(discord_client_secret)}",
            flush=True,
        )
        logger.info(
            f"Discord credentials check: client_id={bool(discord_client_id)}, client_secret={bool(discord_client_secret)}"
        )
        logger.debug(
            f"All environment variables containing DISCORD: {[(k, '***' if 'SECRET' in k else v) for k, v in os.environ.items() if 'DISCORD' in k]}"
        )

        if discord_client_id and discord_client_secret:
            print("CRITICAL DEBUG: Discord credentials found, creating config...", flush=True)
            logger.info("Discord credentials found, creating config...")
            # Create jailbreaker config
            jailbreaker_config = JailbreakerConfig.from_env()
            print(
                f"CRITICAL DEBUG: Config created for target agent: {jailbreaker_config.target_agent_id}",
                flush=True,
            )
            logger.info(f"Config created for target agent: {jailbreaker_config.target_agent_id}")

            # Get agent directory from manager config
            agents_dir = Path(manager.config.manager.agents_directory)
            logger.info(f"Agents directory: {agents_dir}")

            # Initialize jailbreaker service
            logger.info("Creating jailbreaker service...")

            # Create a simple container manager interface for the jailbreaker
            class SimpleContainerManager:
                """Simple container manager for jailbreaker service."""

                async def start_container(self, container_name: str):
                    """Start a Docker container using docker-compose."""
                    import asyncio

                    logger.info(f"Starting container: {container_name}")
                    try:
                        # Use direct docker start (more reliable for existing containers)
                        process = await asyncio.create_subprocess_exec(
                            "docker",
                            "start",
                            container_name,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        stdout, stderr = await process.communicate()

                        if process.returncode == 0:
                            logger.info(f"Container {container_name} started successfully")
                        else:
                            logger.error(f"Failed to start {container_name}: {stderr.decode()}")
                            raise Exception(f"Docker start failed: {stderr.decode()}")

                        # Verify container is running
                        verify_process = await asyncio.create_subprocess_exec(
                            "docker",
                            "ps",
                            "--filter",
                            f"name={container_name}",
                            "--format",
                            "{{.Status}}",
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        status_out, _ = await verify_process.communicate()
                        if b"Up" in status_out:
                            logger.info(f"Container {container_name} verified running")
                        else:
                            logger.warning(
                                f"Container {container_name} may not be running properly"
                            )
                    except Exception as e:
                        logger.error(f"Failed to start container {container_name}: {e}")
                        raise

                async def stop_container(self, container_name: str):
                    """Stop a Docker container."""
                    import asyncio

                    logger.info(f"Stopping container: {container_name}")
                    try:
                        process = await asyncio.create_subprocess_exec(
                            "docker",
                            "stop",
                            container_name,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        stdout, stderr = await process.communicate()

                        if process.returncode == 0:
                            logger.info(f"Container {container_name} stopped successfully")
                        else:
                            # Container might already be stopped, which is fine for our use case
                            logger.warning(
                                f"Container {container_name} stop returned: {stderr.decode()}"
                            )

                        # Brief wait for cleanup
                        await asyncio.sleep(1)
                    except Exception as e:
                        logger.error(f"Failed to stop container {container_name}: {e}")
                        raise

            # Use the real manager instance instead of SimpleContainerManager
            # so that jailbreaker can update the agent registry service tokens
            print("CRITICAL DEBUG: Using real manager for jailbreaker", flush=True)

            jailbreaker_service = JailbreakerService(
                config=jailbreaker_config,
                agent_dir=agents_dir,
                container_manager=deployment_orchestrator,
            )
            logger.info("Jailbreaker service created")

            # Create and include jailbreaker routes
            logger.info("Creating jailbreaker routes...")
            jailbreaker_router = create_jailbreaker_routes(jailbreaker_service)
            router.include_router(jailbreaker_router, prefix="", tags=["jailbreaker"])
            logger.info("Jailbreaker routes added")

            print("CRITICAL DEBUG: Jailbreaker service initialized successfully", flush=True)
            logger.info("Jailbreaker service initialized successfully")
        else:
            print(
                "CRITICAL DEBUG: Jailbreaker service not initialized - Discord credentials not configured",
                flush=True,
            )
            logger.info("Jailbreaker service not initialized - Discord credentials not configured")

    except Exception as e:
        print(f"CRITICAL DEBUG: Exception in jailbreaker initialization: {e}", flush=True)
        logger.error(f"DEBUG: Exception in jailbreaker initialization: {e}", exc_info=True)
        logger.error(f"Failed to initialize jailbreaker service: {e}", exc_info=True)

    return router
