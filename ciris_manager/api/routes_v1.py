"""
API routes for CIRISManager v2 with pre-approved template support.

Provides endpoints for agent creation, discovery, and management.
"""

from fastapi import APIRouter, HTTPException, Header, Response, Request
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any, List, Union
import logging
import os  # noqa: F401 - used in jailbreaker section
from ciris_manager.models import AgentInfo
from ciris_manager.deployment import DeploymentOrchestrator

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

    # Check auth mode for GUI routes
    auth_mode = os.getenv("CIRIS_AUTH_MODE", "production")

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


    # Routes moved to modular files in routes/ package:
    # - system.py: /health, /status
    # - templates.py: /templates/*, /env/default
    # - infrastructure.py: /ports/allocated, /deployment/tokens
    # - agents.py: /agents/*, agent lifecycle
    # - config.py: /agents/{id}/config
    # - oauth.py: /agents/{id}/oauth/*
    # - deployment.py: /updates/*, /canary/*, /versions/adoption
    # - adapters.py: /agents/{id}/adapters/*

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

    # Add debug routes for querying agent persistence
    try:
        from ciris_manager.api.debug_routes import create_debug_routes

        debug_router = create_debug_routes(manager)
        router.include_router(debug_router, prefix="", tags=["debug"])
        logger.info("Debug routes added for agent persistence querying")
    except Exception as e:
        logger.warning(f"Failed to initialize debug routes: {e}")

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
