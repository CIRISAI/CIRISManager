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
import time
from datetime import datetime, timezone
import dateutil.parser

from ciris_manager.core.watchdog import CrashLoopWatchdog
from ciris_manager.config.settings import CIRISManagerConfig
from ciris_manager.port_manager import PortManager
from ciris_manager.template_verifier import TemplateVerifier
from ciris_manager.agent_registry import AgentRegistry
from ciris_manager.compose_generator import ComposeGenerator
from ciris_manager.nginx_manager import NginxManager
from ciris_manager.docker_image_cleanup import DockerImageCleanup
from ciris_manager.logging_config import log_agent_operation
from ciris_manager.utils.log_sanitizer import sanitize_agent_id

logger = logging.getLogger(__name__)
agent_logger = logging.getLogger("ciris_manager.agent_lifecycle")


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
        self._start_time: Optional[datetime] = None

        # Track background tasks to prevent garbage collection
        self._background_tasks: set = set()

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
                    logger.info(
                        f"Found existing agent: {sanitize_agent_id(agent_id)} on port {agent_info.port}"
                    )

    async def create_agent(
        self,
        template: str,
        name: str,
        environment: Optional[Dict[str, str]] = None,
        wa_signature: Optional[str] = None,
        use_mock_llm: Optional[bool] = None,
        enable_discord: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Create a new agent.

        Args:
            template: Template name (e.g., 'scout')
            name: Agent name
            environment: Additional environment variables
            wa_signature: WA signature for non-approved templates
            use_mock_llm: Whether to use mock LLM (None = use default)
            enable_discord: Whether to enable Discord adapter (None = auto-detect)

        Returns:
            Agent creation result

        Raises:
            ValueError: Invalid template or name
            PermissionError: WA signature required but not provided
        """
        start_time = time.time()
        agent_logger.info(f"Starting agent creation - name: {name}, template: {template}")
        log_agent_operation(
            "create_start", agent_id="pending", details={"agent_name": name, "template": template}
        )
        # Validate inputs - prevent path traversal
        import re

        if not re.match(r"^[a-zA-Z0-9_-]+$", template):
            raise ValueError(f"Invalid template name: {template}")

        templates_dir = Path(self.config.manager.templates_directory).resolve()
        template_path = (templates_dir / f"{template}.yaml").resolve()

        # Ensure path is within templates directory
        if not str(template_path).startswith(str(templates_dir)):
            raise ValueError(f"Invalid template path: {template}")

        if not template_path.exists():
            raise ValueError(f"Template not found: {template}")

        # Check if template is pre-approved
        is_pre_approved = await self.template_verifier.is_pre_approved(template, template_path)

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
        logger.info(f"Generated service token for agent {sanitize_agent_id(agent_id)}")

        # Encrypt token for storage
        from ciris_manager.crypto import get_token_encryption

        encryption = get_token_encryption()
        encrypted_token = encryption.encrypt_token(service_token)

        # Create agent directory using agent_id (no spaces!)
        agent_dir = self.agents_dir / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)

        # Create subdirectories with proper permissions matching CIRIS agent expectations
        # Based on CIRIS File Permission System requirements
        directories = {
            "data": 0o755,  # Database files - readable by all
            "data_archive": 0o755,  # Archived thoughts/tasks - audit trail accessible
            "logs": 0o755,  # Log files - must be inspectable
            "config": 0o755,  # Configuration files - config is public
            "audit_keys": 0o700,  # Audit signing keys - prevent key compromise
            ".secrets": 0o700,  # Secrets storage - protect sensitive data
        }

        for dir_name, permissions in directories.items():
            dir_path = agent_dir / dir_name
            dir_path.mkdir(parents=True, exist_ok=True)
            dir_path.chmod(permissions)
            logger.info(f"Created directory {dir_path} with permissions {oct(permissions)}")

        # Change ownership to match container's ciris user (uid=1000, gid=1000)
        # IMPORTANT: Container ciris user is 1000, not 1005 like host ciris user!
        # Try to set ownership using subprocess with sudo (if available)
        import os
        import subprocess
        import shutil

        try:
            # Try to change ownership to uid 1000 (container user)
            # The ciris-manager user has sudo access to chown without password
            # per /etc/sudoers.d/ciris-manager configuration

            # Use sudo chown which should work with our sudoers config
            # Note: This works even with NoNewPrivileges=true in systemd
            # because sudo is a separate process with its own privileges

            # Method 1: Try sudo chown (most reliable)
            logger.debug(f"Attempting sudo chown for {agent_dir}")
            result = subprocess.run(
                ["sudo", "chown", "-R", "1000:1000", str(agent_dir)], capture_output=True, text=True
            )

            if result.returncode == 0:
                logger.info(f"Successfully set ownership to uid:gid 1000:1000 for {agent_dir}")
            else:
                logger.warning(f"sudo chown failed for {agent_dir}:")
                logger.warning(f"  Return code: {result.returncode}")
                if result.stdout:
                    logger.warning(f"  stdout: {result.stdout}")
                if result.stderr:
                    logger.warning(f"  stderr: {result.stderr}")

                # Method 2: Try direct chown (works if running as root)
                logger.debug("Attempting direct os.chown")
                try:
                    os.chown(agent_dir, 1000, 1000)
                    for dir_name in directories.keys():
                        dir_path = agent_dir / dir_name
                        os.chown(dir_path, 1000, 1000)
                    logger.info(f"Successfully set ownership using direct chown for {agent_dir}")
                except PermissionError as pe:
                    logger.debug(f"Direct chown failed: {pe}")

                    # Method 3: Try using a setuid helper script if it exists
                    helper_script = Path("/usr/local/bin/ciris-fix-permissions")
                    if helper_script.exists():
                        logger.debug(f"Attempting helper script: {helper_script}")
                        helper_result = subprocess.run(
                            [str(helper_script), str(agent_dir)], capture_output=True, text=True
                        )
                        if helper_result.returncode == 0:
                            logger.info(f"Fixed permissions using helper script for {agent_dir}")
                        else:
                            logger.warning(f"Helper script failed: {helper_result.stderr}")
                            raise PermissionError(f"Helper script failed: {helper_result.stderr}")
                    else:
                        # Method 4: Try emergency script approach
                        logger.debug("Attempting emergency script method")
                        try:
                            self._run_emergency_permission_fix(agent_dir, agent_id)
                            logger.info(f"Fixed permissions using emergency script for {agent_dir}")
                        except Exception as script_error:
                            logger.debug(f"Emergency script failed: {script_error}")
                            raise PermissionError(
                                f"All permission fixing methods failed. Last error: {script_error}"
                            )

        except Exception as e:
            logger.warning(
                f"Could not set ownership to uid 1000 for {agent_dir}: {e}\n"
                f"Agent may fail to start due to permission issues.\n"
                f"Manual fix required: sudo chown -R 1000:1000 {agent_dir}"
            )

            # Write a script to fix permissions that can be run manually
            fix_script = agent_dir / "fix_permissions.sh"
            fix_script.write_text(f"""#!/bin/bash
# Fix permissions for agent {agent_id}
echo "Fixing permissions for {agent_dir}..."
chmod 755 {agent_dir}/data {agent_dir}/data_archive {agent_dir}/logs {agent_dir}/config
chmod 700 {agent_dir}/audit_keys {agent_dir}/.secrets
chown -R 1000:1000 {agent_dir}/data {agent_dir}/data_archive {agent_dir}/logs {agent_dir}/config {agent_dir}/audit_keys {agent_dir}/.secrets
echo "Permissions fixed. Agent should now be able to start."
""")
            fix_script.chmod(0o755)
            logger.info(f"Created fix_permissions.sh script in {agent_dir} - run with sudo to fix")

        # Copy init script to agent directory
        init_script_src = Path(__file__).parent / "templates" / "init_permissions.sh"
        init_script_dst = agent_dir / "init_permissions.sh"
        if init_script_src.exists():
            try:
                # Try regular copy first
                shutil.copy2(init_script_src, init_script_dst)
                # Try to set permissions
                try:
                    init_script_dst.chmod(0o755)
                except PermissionError:
                    logger.warning(f"Could not set execute permission on {init_script_dst}")
                logger.info(f"Copied init script to {init_script_dst}")
            except PermissionError as e:
                logger.warning(f"Could not copy init script due to permissions: {e}")
                logger.warning(
                    f"Manual fix: sudo cp {init_script_src} {init_script_dst} && sudo chmod 755 {init_script_dst}"
                )
        else:
            logger.warning(f"Init script not found at {init_script_src}")

        # Add service token to environment for agent
        if environment is None:
            environment = {}
        environment["CIRIS_SERVICE_TOKEN"] = service_token

        # Generate docker-compose.yml
        # Default to mock LLM if not specified
        actual_use_mock_llm = use_mock_llm if use_mock_llm is not None else True
        # Default to auto-detect Discord if not specified
        actual_enable_discord = enable_discord if enable_discord is not None else False

        compose_config = self.compose_generator.generate_compose(
            agent_id=agent_id,
            agent_name=name,
            port=allocated_port,
            template=template,
            agent_dir=agent_dir,
            environment=environment,
            use_mock_llm=actual_use_mock_llm,
            enable_discord=actual_enable_discord,
        )

        # Write compose file
        compose_path = agent_dir / "docker-compose.yml"
        self.compose_generator.write_compose_file(compose_config, compose_path)

        # Ensure compose file has correct permissions for manager to update later
        # The manager needs to be able to update this file when settings change
        try:
            import pwd
            import grp

            # Get ciris-manager user/group IDs
            ciris_manager_user = pwd.getpwnam("ciris-manager")
            ciris_manager_group = grp.getgrnam("ciris-manager")

            # Set ownership to ciris-manager:ciris-manager so manager can update it
            os.chown(compose_path, ciris_manager_user.pw_uid, ciris_manager_group.gr_gid)
            compose_path.chmod(0o664)  # rw-rw-r-- (owner and group can write)
            logger.debug("Set compose file ownership to ciris-manager:ciris-manager")
        except Exception as e:
            logger.warning(f"Could not set compose file ownership: {e}")
            # Try sudo approach as fallback
            try:
                result = subprocess.run(
                    ["sudo", "chown", "ciris-manager:ciris-manager", str(compose_path)],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    subprocess.run(
                        ["sudo", "chmod", "664", str(compose_path)], capture_output=True, text=True
                    )
                    logger.debug("Set compose file ownership using sudo")
                else:
                    logger.warning(
                        f"Could not set compose file ownership via sudo: {result.stderr}"
                    )
            except Exception as sudo_error:
                logger.warning(f"Sudo fallback failed: {sudo_error}")

        # Register agent
        self.agent_registry.register_agent(
            agent_id=agent_id,
            name=name,
            port=allocated_port,
            template=template,
            compose_file=str(compose_path),
            service_token=encrypted_token,  # Store encrypted version
        )

        # Start the agent FIRST so Docker discovery can find it
        agent_logger.info(f"Starting container for agent {sanitize_agent_id(agent_id)}")
        try:
            await self._start_agent(agent_id, compose_path)
            agent_logger.info(f"✅ Container started for agent {sanitize_agent_id(agent_id)}")
        except Exception as e:
            agent_logger.error(
                f"❌ Failed to start container for {sanitize_agent_id(agent_id)}: {e}"
            )
            # Clean up on failure
            self.agent_registry.unregister_agent(agent_id)
            self.port_manager.release_port(agent_id)
            raise RuntimeError(f"Failed to start agent container: {e}")

        # Wait a moment for container to be fully up
        await asyncio.sleep(2)

        # NOW update nginx routing after container is running
        agent_logger.info(f"Updating nginx configuration for agent {sanitize_agent_id(agent_id)}")
        try:
            await self._add_nginx_route(agent_id, allocated_port)
            agent_logger.info(f"✅ Nginx routes added for agent {sanitize_agent_id(agent_id)}")
        except Exception as e:
            agent_logger.error(
                f"❌ Failed to add nginx routes for {sanitize_agent_id(agent_id)}: {e}"
            )
            # Container started but nginx failed - log but don't fail the creation
            agent_logger.warning(
                f"Agent {agent_id} created but nginx routing failed - agent may not be accessible via gateway"
            )

        duration_ms = int((time.time() - start_time) * 1000)
        agent_logger.info(
            f"✅ Agent {sanitize_agent_id(agent_id)} created successfully in {duration_ms}ms"
        )

        log_agent_operation(
            operation="create_complete",
            agent_id=agent_id,
            details={
                "agent_name": name,
                "template": template,
                "port": allocated_port,
                "duration_ms": duration_ms,
            },
        )

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

            discovery = DockerAgentDiscovery(self.agent_registry)
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

    async def _add_nginx_route(self, agent_id: str, port: int) -> None:
        """Update nginx configuration after adding a new agent."""
        logger.debug(f"_add_nginx_route called for agent {agent_id} on port {port}")
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
        """Container management loop - handles crash recovery only.

        This loop ONLY restarts containers that have crashed (stopped unexpectedly).
        It does NOT:
        - Pull new images (that's handled by deployment orchestrator)
        - Restart running containers (maintains agent autonomy)
        - Interfere with consensual shutdowns (deployment updates)

        The loop specifically checks for stopped containers and only restarts them
        if they are not part of an active deployment.
        """
        logger.info("Container management loop started - crash recovery mode only")

        # Import deployment orchestrator to check active deployments

        while self._running:
            try:
                # Check for stopped containers that need recovery
                await self._recover_crashed_containers()
            except Exception as e:
                logger.error(f"Error in container recovery loop: {e}")

            # Sleep before next check (default 30 seconds for crash recovery)
            await asyncio.sleep(30)  # Check more frequently for crashes

    async def _recover_crashed_containers(self) -> None:
        """Recover containers that have crashed (stopped unexpectedly).

        This method:
        1. Finds all stopped containers
        2. Checks if they're part of an active deployment
        3. Only restarts containers that crashed (not part of deployment)
        """
        try:
            import docker
            from docker.errors import DockerException

            client = docker.from_env()

            # Get all registered agents
            agents = self.agent_registry.list_agents()

            for agent_info in agents:
                agent_id = agent_info.agent_id
                container_name = f"ciris-{agent_id}"

                try:
                    # Check container status
                    container = client.containers.get(container_name)

                    # CRITICAL: Only act on stopped containers
                    # Never touch running containers (maintains autonomy)
                    if container.status != "exited":
                        continue

                    # Check exit code to determine if it was a crash or consensual shutdown
                    exit_code = container.attrs.get("State", {}).get("ExitCode", -1)

                    # Exit code 0 = consensual shutdown (deployment or user request)
                    # Non-zero = crash or error
                    if exit_code == 0:
                        logger.debug(
                            f"Container {container_name} exited cleanly (code 0), not restarting"
                        )
                        continue

                    # Check if this agent is part of an active deployment
                    # by looking for recent deployment activity
                    if await self._is_agent_in_deployment(agent_id):
                        logger.debug(
                            f"Container {container_name} is part of active deployment, skipping recovery"
                        )
                        continue

                    # This is a crashed container not part of deployment - restart it
                    logger.warning(
                        f"Container {container_name} crashed (exit code {exit_code}), attempting recovery"
                    )

                    # Use docker-compose to restart (maintains configuration)
                    compose_path = Path(agent_info.compose_file)
                    if compose_path.exists():
                        await self._restart_crashed_container(agent_id, compose_path)
                    else:
                        logger.error(f"Compose file not found for {agent_id}: {compose_path}")

                except docker.errors.NotFound:
                    # Container doesn't exist - might be newly created or deleted
                    logger.debug(f"Container {container_name} not found, may be new or deleted")
                except Exception as e:
                    logger.error(f"Error checking container {container_name}: {e}")

        except DockerException as e:
            logger.error(f"Docker error in crash recovery: {e}")
        except Exception as e:
            logger.error(f"Unexpected error in crash recovery: {e}")

    async def _is_agent_in_deployment(self, agent_id: str) -> bool:
        """Check if an agent is part of an active deployment.

        Returns True if the agent has been part of a deployment in the last 5 minutes.
        This prevents us from interfering with deployment-related shutdowns.
        """
        # Check deployment orchestrator state
        # For now, we'll use a simple time-based check
        # In the future, this could query the deployment orchestrator directly

        # Simple implementation: assume any container that stopped in the last 5 minutes
        # might be part of a deployment
        try:
            import docker

            client = docker.from_env()
            container_name = f"ciris-{agent_id}"

            container = client.containers.get(container_name)
            finished_at = container.attrs.get("State", {}).get("FinishedAt")

            if finished_at:
                finished_time = dateutil.parser.parse(finished_at)
                now = datetime.now(timezone.utc)
                time_since_stop = (now - finished_time).total_seconds()

                # If stopped less than 5 minutes ago, might be deployment
                if time_since_stop < 300:
                    return True

        except Exception as e:
            logger.debug(f"Error checking deployment status for {agent_id}: {e}")

        return False

    async def _restart_crashed_container(self, agent_id: str, compose_path: Path) -> None:
        """Restart a crashed container using docker-compose.

        This uses 'docker-compose up -d' which will:
        - Start the container if stopped
        - Do nothing if already running (safe operation)
        - Use the existing image (no pull)
        """
        try:
            logger.info(f"Restarting crashed container for agent {agent_id}")

            # Use docker-compose up -d (safe - won't affect running containers)
            cmd = ["docker-compose", "-f", str(compose_path), "up", "-d"]
            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                logger.info(f"Successfully restarted crashed container for agent {agent_id}")
            else:
                logger.error(f"Failed to restart container for {agent_id}: {stderr.decode()}")

        except Exception as e:
            logger.error(f"Error restarting container for {agent_id}: {e}")

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

        self._running = True
        self._start_time = datetime.now(timezone.utc)

        # Generate initial nginx config
        logger.info("Updating nginx configuration on startup...")
        success = await self.update_nginx_config()
        if not success:
            logger.error("Failed to update nginx configuration on startup")

        # Start the new container management loop
        task = asyncio.create_task(self.container_management_loop())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

        # Start watchdog
        await self.watchdog.start()

        # Start API server if configured
        if hasattr(self.config.manager, "port") and self.config.manager.port:
            task = asyncio.create_task(self._start_api_server())
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

        # Start periodic Docker image cleanup (runs every 24 hours)
        task = asyncio.create_task(self.image_cleanup.run_periodic_cleanup(interval_hours=24))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

        # Run initial cleanup on startup (with deployment check)
        task = asyncio.create_task(self._run_initial_cleanup_safe())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

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

            # Try to add rate limiting if available
            try:
                from .api.rate_limit import limiter, rate_limit_exceeded_handler, SLOWAPI_AVAILABLE

                if SLOWAPI_AVAILABLE and limiter:
                    from slowapi.errors import RateLimitExceeded

                    app.state.limiter = limiter
                    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)  # type: ignore
                    logger.info("Rate limiting enabled")
                else:
                    logger.warning("Rate limiting disabled - slowapi not available")
            except ImportError:
                logger.warning("Rate limiting disabled - module not available")

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

            # Mount v2 API alongside v1
            try:
                # Set global manager instance for v2 API
                from .manager_core import set_manager

                set_manager(self)

                from .api.v2 import (
                    agents_router,
                    versions_router,
                    deployments_router,
                    templates_router,
                    system_router,
                )

                # Mount v2 routers
                app.include_router(system_router, prefix="/manager/v2")
                app.include_router(agents_router, prefix="/manager/v2")
                app.include_router(versions_router, prefix="/manager/v2")
                app.include_router(deployments_router, prefix="/manager/v2")
                app.include_router(templates_router, prefix="/manager/v2")

                logger.info("v2 API mounted successfully at /manager/v2")
            except ImportError as e:
                logger.warning(f"Could not mount v2 API: {e}")

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

            discovery = DockerAgentDiscovery(self.agent_registry)
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

        # Save deployment state before shutdown
        if hasattr(self, "deployment_orchestrator") and self.deployment_orchestrator:
            await self.deployment_orchestrator.stop()

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

    def _run_emergency_permission_fix(self, agent_dir: Path, agent_id: str) -> None:
        """Emergency permission fixing using a temporary script."""
        import tempfile
        import subprocess

        script_content = f"""#!/bin/bash
set -e
echo "Emergency permission fix for agent {agent_id}..."

# Change ownership to container user
chown -R 1000:1000 "{agent_dir}"

# Set directory permissions
find "{agent_dir}" -type d -exec chmod 755 {{}} \\;
chmod 700 "{agent_dir}/audit_keys" "{agent_dir}/.secrets" 2>/dev/null || true

# Set file permissions  
find "{agent_dir}" -type f -exec chmod 644 {{}} \\;
chmod 755 "{agent_dir}/"*.sh 2>/dev/null || true

echo "✓ Emergency permission fix completed"
"""

        # Write script to a temporary location
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
            f.write(script_content)
            script_path = f.name

        try:
            # Make script executable
            import os

            os.chmod(script_path, 0o755)

            # Execute the script with sudo
            result = subprocess.run(
                ["sudo", "bash", script_path], capture_output=True, text=True, timeout=30
            )

            if result.returncode != 0:
                raise RuntimeError(f"Emergency script failed: {result.stderr}")

        finally:
            # Clean up temp script
            try:
                os.unlink(script_path)
            except Exception:
                pass

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

    async def _run_initial_cleanup_safe(self) -> None:
        """Run initial Docker image cleanup on startup, but only if no deployment is active."""
        max_wait_time = 300  # Wait up to 5 minutes for deployments to complete
        check_interval = 30  # Check every 30 seconds
        elapsed = 0

        while elapsed < max_wait_time:
            if not (
                hasattr(self, "deployment_orchestrator")
                and self.deployment_orchestrator
                and self.deployment_orchestrator.has_active_deployment()
            ):
                logger.info("No active deployments detected, proceeding with initial cleanup")
                await self._run_initial_cleanup()
                return

            logger.info(f"Active deployment detected, delaying initial cleanup (waited {elapsed}s)")
            await asyncio.sleep(check_interval)
            elapsed += check_interval

        # If we've waited too long, skip cleanup to avoid interfering
        logger.warning(
            f"Skipping initial cleanup after waiting {max_wait_time}s - deployments still active"
        )

    def get_status(self) -> dict:
        """Get current manager status."""
        uptime_seconds = None
        if self._start_time:
            delta = datetime.now(timezone.utc) - self._start_time
            uptime_seconds = int(delta.total_seconds())

        # Get system metrics
        system_metrics = {}
        try:
            import psutil

            system_metrics = {
                "cpu_percent": psutil.cpu_percent(interval=0.1),
                "memory_percent": psutil.virtual_memory().percent,
                "disk_percent": psutil.disk_usage("/").percent,
                "load_average": list(psutil.getloadavg())
                if hasattr(psutil, "getloadavg")
                else None,
            }
        except ImportError:
            pass  # psutil not installed
        except Exception as e:
            logger.debug(f"Could not get system metrics: {e}")

        return {
            "running": self._running,
            "uptime_seconds": uptime_seconds,
            "start_time": self._start_time.isoformat() if self._start_time else None,
            "config": self.config.model_dump(),
            "watchdog_status": self.watchdog.get_status(),
            "components": {
                "watchdog": "running" if self._running else "stopped",
                "api_server": "running" if self._running else "stopped",
                "nginx": "enabled" if self.config.nginx.enabled else "disabled",
            },
            "system_metrics": system_metrics,
        }


async def main() -> None:
    """Main entry point for CIRISManager."""
    # Setup file-based logging
    from ciris_manager.logging_config import setup_logging
    import os

    # Set up logging before anything else
    # Use /var/log if available, otherwise fallback to local directory
    log_dir = "/var/log/ciris-manager"
    if not os.access("/var/log", os.W_OK):
        # Can't write to /var/log, use local directory
        local_log_path = Path.home() / ".local" / "log" / "ciris-manager"
        log_dir = str(local_log_path)

    try:
        setup_logging(
            log_dir=log_dir,
            console_level="INFO",
            file_level="DEBUG",
            use_json=False,  # Use human-readable format for now
        )
    except PermissionError:
        # Fall back to basic logging if file logging fails
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )

    logger = logging.getLogger(__name__)
    logger.info("=== CIRISManager Starting ===")

    # Load configuration
    config_path = "/etc/ciris-manager/config.yml"
    logger.info(f"Loading configuration from {config_path}")
    config = CIRISManagerConfig.from_file(config_path)

    # Create and run manager
    manager = CIRISManager(config)
    await manager.run()


if __name__ == "__main__":
    asyncio.run(main())
