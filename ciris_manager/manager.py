"""
Main CIRISManager service.

Coordinates container management, crash loop detection, and provides
API for agent discovery and lifecycle management.
"""

import asyncio
import logging
import signal
import secrets
from pathlib import Path
from typing import Optional, Dict, Any

from ciris_manager.core.watchdog import CrashLoopWatchdog
from ciris_manager.config.settings import CIRISManagerConfig
from ciris_manager.port_manager import PortManager
from ciris_manager.template_verifier import TemplateVerifier
from ciris_manager.agent_registry import AgentRegistry
from ciris_manager.compose_generator import ComposeGenerator
from ciris_manager.nginx_manager import NginxManager
from ciris_manager.docker_image_cleanup import DockerImageCleanup

logger = logging.getLogger(__name__)


class CIRISManager:
    """Main manager service coordinating all components."""

    # URL-safe characters excluding visually confusing ones
    # Removed: 0, O, I, l, 1
    SAFE_CHARS = "abcdefghjkmnpqrstuvwxyz23456789"

    def __init__(self, config: Optional[CIRISManagerConfig] = None):
        """
        Initialize CIRISManager.

        Args:
            config: Configuration object, uses defaults if not provided
        """
        logger.info("Initializing CIRISManager...")
        self.config = config or CIRISManagerConfig()

        # Create necessary directories
        self.agents_dir = Path(self.config.manager.agents_directory)
        logger.info(f"Creating agents directory: {self.agents_dir}")
        try:
            self.agents_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Agents directory ready: {self.agents_dir}")
        except Exception as e:
            logger.error(f"Failed to create agents directory {self.agents_dir}: {e}")
            raise

        # Initialize new components
        metadata_path = self.agents_dir / "metadata.json"
        self.agent_registry = AgentRegistry(metadata_path)

        self.port_manager = PortManager(
            start_port=self.config.ports.start,
            end_port=self.config.ports.end,
            metadata_path=metadata_path,
        )

        # Add reserved ports
        for port in self.config.ports.reserved:
            self.port_manager.add_reserved_port(port)

        # Initialize template verifier
        manifest_path = Path(self.config.manager.manifest_path)
        self.template_verifier = TemplateVerifier(manifest_path)

        # Initialize compose generator
        self.compose_generator = ComposeGenerator(
            docker_registry=self.config.docker.registry,
            default_image=self.config.docker.image,
        )

        # Initialize nginx manager - fail fast if there are issues
        if self.config.nginx.enabled:
            logger.info(
                f"Initializing Nginx Manager with config_dir: {self.config.nginx.config_dir}"
            )
            try:
                self.nginx_manager = NginxManager(
                    config_dir=self.config.nginx.config_dir,
                    container_name=self.config.nginx.container_name,
                )
                logger.info("Successfully initialized Nginx Manager")
            except Exception as e:
                logger.error(f"Failed to initialize Nginx Manager: {e}")
                logger.error(f"Config dir: {self.config.nginx.config_dir}")
                logger.error(f"Container name: {self.config.nginx.container_name}")
                raise
        else:
            raise RuntimeError("Nginx must be enabled - CIRISManager requires nginx for routing")

        # Initialize existing components

        self.watchdog = CrashLoopWatchdog(
            check_interval=self.config.watchdog.check_interval,
            crash_threshold=self.config.watchdog.crash_threshold,
            crash_window=self.config.watchdog.crash_window,
        )

        # Initialize Docker image cleanup service
        self.image_cleanup = DockerImageCleanup(versions_to_keep=2)

        # Scan existing agents on startup
        self._scan_existing_agents()

        self._running = False
        self._shutdown_event = asyncio.Event()

    def _scan_existing_agents(self) -> None:
        """Scan agent directories to rebuild registry on startup."""
        if not self.agents_dir.exists():
            return

        # Look for agent directories
        for agent_dir in self.agents_dir.iterdir():
            if not agent_dir.is_dir() or agent_dir.name == "metadata.json":
                continue

            compose_path = agent_dir / "docker-compose.yml"
            if compose_path.exists():
                # Extract agent info from directory name
                agent_name = agent_dir.name
                agent_id = agent_name

                # Try to get port from existing registry
                agent_info = self.agent_registry.get_agent(agent_id)
                if agent_info:
                    # Ensure port manager knows about this allocation
                    self.port_manager.allocate_port(agent_id)
                    logger.info(f"Found existing agent: {agent_id} on port {agent_info.port}")

    async def create_agent(
        self,
        template: str,
        name: str,
        environment: Optional[Dict[str, str]] = None,
        wa_signature: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new agent.

        Args:
            template: Template name (e.g., 'scout')
            name: Agent name
            environment: Additional environment variables
            wa_signature: WA signature for non-approved templates

        Returns:
            Agent creation result

        Raises:
            ValueError: Invalid template or name
            PermissionError: WA signature required but not provided
        """
        # Validate inputs
        template_path = Path(self.config.manager.templates_directory) / f"{template}.yaml"
        if not template_path.exists():
            raise ValueError(f"Template not found: {template}")

        # Check if template is pre-approved
        is_pre_approved = self.template_verifier.is_pre_approved(template, template_path)

        if not is_pre_approved and not wa_signature:
            raise PermissionError(
                f"Template '{template}' is not pre-approved. WA signature required."
            )

        if wa_signature and not is_pre_approved:
            logger.info(f"Verifying WA signature for custom template: {template}")

        # Generate agent ID with 4-digit suffix
        base_id = name.lower().replace(" ", "-")
        suffix = self._generate_agent_suffix()
        agent_id = f"{base_id}-{suffix}"

        # Allocate port
        allocated_port = self.port_manager.allocate_port(agent_id)

        # Generate service token for secure manager-to-agent communication
        service_token = self._generate_service_token()
        logger.info(f"Generated service token for agent {agent_id}")

        # Encrypt token for storage
        from ciris_manager.crypto import get_token_encryption

        encryption = get_token_encryption()
        encrypted_token = encryption.encrypt_token(service_token)

        # Create agent directory using agent_id (no spaces!)
        agent_dir = self.agents_dir / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)

        # Add service token to environment for agent
        if environment is None:
            environment = {}
        environment["CIRIS_SERVICE_TOKEN"] = service_token

        # Generate docker-compose.yml
        compose_config = self.compose_generator.generate_compose(
            agent_id=agent_id,
            agent_name=name,
            port=allocated_port,
            template=template,
            agent_dir=agent_dir,
            environment=environment,
            use_mock_llm=False,  # Use real LLMs
        )

        # Write compose file
        compose_path = agent_dir / "docker-compose.yml"
        self.compose_generator.write_compose_file(compose_config, compose_path)

        # Register agent
        self.agent_registry.register_agent(
            agent_id=agent_id,
            name=name,
            port=allocated_port,
            template=template,
            compose_file=str(compose_path),
            service_token=encrypted_token,  # Store encrypted version
        )

        # Update nginx routing (no conditional needed - handled by manager type)
        await self._add_nginx_route(name.lower(), allocated_port)

        # Start the agent
        await self._start_agent(agent_id, compose_path)

        return {
            "agent_id": agent_id,
            "container": f"ciris-{agent_id}",
            "port": allocated_port,
            "api_endpoint": f"http://localhost:{allocated_port}",
            "compose_file": str(compose_path),
            "status": "starting",
        }

    async def update_nginx_config(self) -> bool:
        """Update nginx configuration with all current agents."""
        try:
            # Discover all running agents
            from ciris_manager.docker_discovery import DockerAgentDiscovery

            discovery = DockerAgentDiscovery()
            agents = discovery.discover_agents()

            # Update nginx config with current agent list
            success = self.nginx_manager.update_config(agents)

            if success:
                logger.info(f"Updated nginx config with {len(agents)} agents")
            else:
                logger.error("Failed to update nginx configuration")

            return success

        except Exception as e:
            logger.error(f"Error updating nginx config: {e}")
            return False

    async def _add_nginx_route(self, agent_name: str, port: int) -> None:
        """Update nginx configuration after adding a new agent."""
        # With the new template-based approach, we regenerate the entire config
        success = await self.update_nginx_config()
        if not success:
            raise RuntimeError("Failed to update nginx configuration")

    async def _start_agent(self, agent_id: str, compose_path: Path) -> None:
        """Start an agent container."""
        cmd = ["docker-compose", "-f", str(compose_path), "up", "-d"]
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logger.error(f"Failed to start agent {agent_id}: {stderr.decode()}")
            raise RuntimeError(f"Failed to start agent: {stderr.decode()}")

        logger.info(f"Started agent {agent_id}")

    async def container_management_loop(self) -> None:
        """Updated container management for per-agent compose files."""
        while self._running:
            try:
                # Iterate through all registered agents
                for agent_info in self.agent_registry.list_agents():
                    compose_path = Path(agent_info.compose_file)
                    if compose_path.exists():
                        # Pull latest images if configured
                        if self.config.container_management.pull_images:
                            await self._pull_agent_images(compose_path)

                        # Run docker-compose up -d for this agent
                        await self._start_agent(agent_info.agent_id, compose_path)

                # Wait for next iteration
                await asyncio.sleep(self.config.container_management.interval)

            except Exception as e:
                logger.error(f"Error in container management loop: {e}")
                await asyncio.sleep(30)  # Back off on error

    async def _pull_agent_images(self, compose_path: Path) -> None:
        """Pull latest images for an agent."""
        cmd = ["docker-compose", "-f", str(compose_path), "pull"]
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()

    async def start(self) -> None:
        """Start all manager services."""
        logger.info("Starting CIRISManager...")

        # Set up audit logging
        from ciris_manager.audit import setup_audit_logging

        setup_audit_logging()

        self._running = True

        # Generate initial nginx config
        logger.info("Updating nginx configuration on startup...")
        success = await self.update_nginx_config()
        if not success:
            logger.error("Failed to update nginx configuration on startup")

        # Start the new container management loop
        asyncio.create_task(self.container_management_loop())

        # Start watchdog
        await self.watchdog.start()

        # Start API server if configured
        if hasattr(self.config.manager, "port") and self.config.manager.port:
            asyncio.create_task(self._start_api_server())

        # Start periodic Docker image cleanup (runs every 24 hours)
        asyncio.create_task(self.image_cleanup.run_periodic_cleanup(interval_hours=24))

        # Run initial cleanup on startup
        asyncio.create_task(self._run_initial_cleanup())

        logger.info("CIRISManager started successfully")

    async def _start_api_server(self) -> None:
        """Start the FastAPI server for CIRISManager API."""
        try:
            from fastapi import FastAPI
            from fastapi.responses import JSONResponse
            import uvicorn
            from typing import Union
            from .api.routes import create_routes
            from .api.auth import create_auth_routes, load_oauth_config
            from .api.device_auth_routes import create_device_auth_routes

            app = FastAPI(title="CIRISManager API", version="1.0.0")

            # Add exception handler for 401 errors to redirect browsers to login
            from fastapi import Request, HTTPException
            from fastapi.responses import RedirectResponse

            @app.exception_handler(HTTPException)
            async def auth_exception_handler(
                request: Request, exc: HTTPException
            ) -> Union[RedirectResponse, JSONResponse]:
                # If it's a 401 error and the request accepts HTML, redirect to login
                if exc.status_code == 401:
                    accept_header = request.headers.get("accept", "")
                    if "text/html" in accept_header:
                        # Browser request - redirect to login
                        return RedirectResponse(url="/", status_code=302)
                # Otherwise return normal JSON error

                return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

            # Create routes with manager instance
            router = create_routes(self)
            app.include_router(router, prefix="/manager/v1")

            # Include auth routes if in production mode
            if self.config.auth.mode == "production":
                auth_router = create_auth_routes()
                app.include_router(auth_router, prefix="/manager/v1")

                # Add device auth routes
                device_auth_router = create_device_auth_routes()
                app.include_router(device_auth_router, prefix="/manager/v1")

                # Load OAuth configuration
                if not load_oauth_config():
                    logger.warning("OAuth not configured. Authentication will not work.")
                else:
                    logger.info("OAuth configured successfully")

            # Add OAuth callback redirect for Google Console compatibility
            from fastapi import Request

            @app.get("/manager/oauth/callback")
            async def oauth_callback_compat(request: Request) -> RedirectResponse:
                """Redirect from Google's registered URL to our actual endpoint"""
                return RedirectResponse(
                    url=f"/manager/v1/oauth/callback?{request.url.query}",
                    status_code=307,  # Temporary redirect, preserves method
                )

            config = uvicorn.Config(
                app,
                host=self.config.manager.host,
                port=self.config.manager.port,
                log_level="info",
            )
            server = uvicorn.Server(config)

            logger.info(
                f"Starting API server on {self.config.manager.host}:{self.config.manager.port}"
            )
            await server.serve()

        except Exception as e:
            logger.error(f"Failed to start API server: {e}")

    async def delete_agent(self, agent_id: str) -> bool:
        """
        Delete an agent and clean up its resources.

        Args:
            agent_id: ID of agent to delete

        Returns:
            True if successful
        """
        try:
            # Get agent info
            agent_info = self.agent_registry.get_agent(agent_id)
            if not agent_info:
                logger.error(f"Agent {agent_id} not found")
                return False

            # Stop the agent container
            compose_path = Path(agent_info.compose_file)
            if compose_path.exists():
                logger.info(f"Stopping agent {agent_id}")
                cmd = ["docker-compose", "-f", str(compose_path), "down", "-v"]
                process = await asyncio.create_subprocess_exec(
                    *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )
                await process.communicate()

            # Remove nginx routes (no conditional needed)
            logger.info(f"Removing nginx routes for {agent_id}")
            # Get current list of agents to pass to nginx manager
            from ciris_manager.docker_discovery import DockerAgentDiscovery

            discovery = DockerAgentDiscovery()
            agents = discovery.discover_agents()
            self.nginx_manager.remove_agent_routes(agent_id, agents)

            # Free the port
            if agent_info.port:
                self.port_manager.release_port(agent_id)

            # Remove from registry
            self.agent_registry.unregister_agent(agent_id)

            # Don't try to delete the agent directory - it contains root-owned files
            # from the Docker container. The docker-compose down -v should handle cleanup.
            # We'll just remove the docker-compose.yml file
            agent_dir = compose_path.parent
            if compose_path.exists():
                compose_path.unlink()
                logger.info(f"Removed docker-compose.yml for agent {agent_id}")

            # Note: The agent directory with data/logs will remain but the container is stopped
            logger.info(
                f"Agent {agent_id} stopped. Directory {agent_dir} retained for data preservation."
            )

            logger.info(f"Successfully deleted agent {agent_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete agent {agent_id}: {e}")
            return False

    async def stop(self) -> None:
        """Stop all manager services."""
        logger.info("Stopping CIRISManager...")

        self._running = False

        # Stop watchdog
        await self.watchdog.stop()

        self._shutdown_event.set()

        logger.info("CIRISManager stopped")

    async def run(self) -> None:
        """Run the manager until shutdown signal."""
        # Setup signal handlers
        loop = asyncio.get_event_loop()

        def handle_signal() -> None:
            logger.info("Shutdown signal received")
            self._shutdown_event.set()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, handle_signal)

        try:
            # Start services
            await self.start()

            # Wait for shutdown
            await self._shutdown_event.wait()

        finally:
            # Stop services
            await self.stop()

    def _generate_agent_suffix(self) -> str:
        """
        Generate a 6-character URL-safe suffix for agent IDs.

        Uses cryptographically secure random number generation to ensure:
        - Unpredictability: Prevents guessing of agent IDs
        - Uniqueness: Very low collision probability (1 in 32^6 = ~1 billion)
        - Security: Agent IDs cannot be enumerated or predicted

        Excludes visually confusing characters:
        - 0/O (zero and capital O)
        - I/l/1 (capital I, lowercase L, and one)

        Returns:
            6-character lowercase string safe for URLs
        """
        return "".join(secrets.choice(self.SAFE_CHARS) for _ in range(6))

    def _generate_service_token(self) -> str:
        """
        Generate a secure service account token for agent authentication.

        Uses cryptographically secure random generation to create a 32-byte token.
        The token is URL-safe base64 encoded for easy transmission.

        Returns:
            URL-safe base64 encoded token (43 characters)
        """
        # Generate 32 bytes of random data (256 bits of entropy)
        return secrets.token_urlsafe(32)

    async def _run_initial_cleanup(self) -> None:
        """Run initial Docker image cleanup on startup."""
        try:
            logger.info("Running initial Docker image cleanup")
            results = await self.image_cleanup.cleanup_images()

            total_removed = sum(results.values())
            if total_removed > 0:
                logger.info(f"Initial cleanup removed {total_removed} old images")
                for repo, count in results.items():
                    if count > 0:
                        logger.info(f"  {repo}: removed {count} images")
            else:
                logger.info("No old images to clean up")

        except Exception as e:
            logger.error(f"Initial image cleanup failed: {e}")

    def get_status(self) -> dict:
        """Get current manager status."""
        return {
            "running": self._running,
            "config": self.config.model_dump(),
            "watchdog_status": self.watchdog.get_status(),
            "components": {
                "watchdog": "running" if self._running else "stopped",
                "api_server": "running" if self._running else "stopped",
                "nginx": "enabled" if self.config.nginx.enabled else "disabled",
            },
        }


async def main() -> None:
    """Main entry point for CIRISManager."""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Load configuration
    config_path = "/etc/ciris-manager/config.yml"
    config = CIRISManagerConfig.from_file(config_path)

    # Create and run manager
    manager = CIRISManager(config)
    await manager.run()


if __name__ == "__main__":
    asyncio.run(main())
