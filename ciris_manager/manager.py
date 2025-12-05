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
from ciris_manager.multi_server_docker import MultiServerDockerClient
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

        # Initialize multi-server Docker client
        logger.info(
            f"Initializing multi-server Docker client with {len(self.config.servers)} servers"
        )
        self.docker_client = MultiServerDockerClient(self.config.servers)

        # Test connections to all servers and initialize remote server shared files
        for server in self.config.servers:
            if self.docker_client.test_connection(server.server_id):
                logger.info(
                    f"✅ Docker connection successful: {server.server_id} ({server.hostname})"
                )
                # Initialize shared files on remote servers
                if not server.is_local:
                    try:
                        self._ensure_remote_server_shared_files(server.server_id)
                        logger.info(f"✅ Initialized shared files on {server.server_id}")
                    except Exception as e:
                        logger.warning(
                            f"Failed to initialize shared files on {server.server_id}: {e}"
                        )
            else:
                logger.error(f"❌ Docker connection failed: {server.server_id} ({server.hostname})")
                if not server.is_local:
                    logger.warning(
                        f"Remote server {server.server_id} is not reachable - agents on this server may not work"
                    )

        # Initialize nginx managers - one for each server
        if self.config.nginx.enabled:
            logger.info(f"Initializing Nginx Managers for {len(self.config.servers)} servers")
            try:
                # Create nginx managers dict
                self.nginx_managers: Dict[str, NginxManager] = {}

                # Main server nginx manager (manages local nginx config file)
                main_server = next(
                    (s for s in self.config.servers if s.server_id == "main"),
                    self.config.servers[0],
                )
                self.nginx_managers["main"] = NginxManager(
                    config_dir=self.config.nginx.config_dir,
                    container_name=self.config.nginx.container_name,
                    hostname=main_server.hostname,
                )
                logger.info(
                    f"✅ Initialized Nginx Manager for main server ({main_server.hostname})"
                )

                # Remote server nginx managers (for config generation only, deployed via Docker API)
                for server in self.config.servers:
                    if not server.is_local and server.server_id != "main":
                        # For remote servers, we only need the NginxManager for config generation
                        # The deploy_remote_config() method will handle deployment via Docker API
                        self.nginx_managers[server.server_id] = NginxManager(
                            config_dir="/tmp",  # Not used for remote servers
                            container_name="ciris-nginx",  # Standard nginx container name
                            hostname=server.hostname,
                        )
                        logger.info(
                            f"✅ Initialized Nginx Manager for remote server {server.server_id} ({server.hostname})"
                        )

                # Keep backward compatibility - self.nginx_manager points to main
                self.nginx_manager = self.nginx_managers["main"]

                logger.info(f"Successfully initialized {len(self.nginx_managers)} Nginx Managers")
            except Exception as e:
                logger.error(f"Failed to initialize Nginx Managers: {e}")
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
        billing_enabled: Optional[bool] = None,
        billing_api_key: Optional[str] = None,
        server_id: Optional[str] = None,
        database_url: Optional[str] = None,
        database_ssl_cert_path: Optional[str] = None,
        agent_occurrence_id: Optional[str] = None,
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
            billing_enabled: Whether to enable paid billing (None = use default: False)
            billing_api_key: Billing API key (required if billing_enabled=True)
            server_id: Target server ID (defaults to 'main')
            database_url: PostgreSQL database URL with SSL mode
            database_ssl_cert_path: Path to SSL certificate file for database
            agent_occurrence_id: Unique occurrence ID for database isolation (enables multiple agents on same DB)

        Returns:
            Agent creation result

        Raises:
            ValueError: Invalid template or name
            PermissionError: WA signature required but not provided
        """
        start_time = time.time()

        # Default to main server if not specified
        target_server_id = server_id or "main"

        # Validate server exists (get_server_config will raise ValueError if not found)
        server_config = self.docker_client.get_server_config(target_server_id)
        agent_logger.info(
            f"Starting agent creation - name: {name}, template: {template}, "
            f"server: {target_server_id} ({server_config.hostname})"
        )
        log_agent_operation(
            "create_start",
            agent_id="pending",
            details={
                "agent_name": name,
                "template": template,
                "server_id": target_server_id,
                "server_hostname": server_config.hostname,
            },
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

        # Generate agent ID based on whether occurrence_id is provided
        base_id = name.lower().replace(" ", "-")

        if agent_occurrence_id:
            # Multi-occurrence agent: use base_id without suffix
            # The occurrence_id makes this unique
            agent_id = base_id

            # Check if this exact combination (agent_id, occurrence_id, server_id) exists
            existing = self.agent_registry.get_agent(
                agent_id, occurrence_id=agent_occurrence_id, server_id=target_server_id
            )

            if existing:
                raise ValueError(
                    f"Agent {agent_id} with occurrence_id={agent_occurrence_id} on "
                    f"server={target_server_id} already exists"
                )
        else:
            # Single-occurrence agent: use suffix for uniqueness
            max_attempts = 10
            for attempt in range(max_attempts):
                suffix = self._generate_agent_suffix()
                agent_id = f"{base_id}-{suffix}"

                # Check if this agent_id exists (no occurrence_id)
                existing = self.agent_registry.get_agent(
                    agent_id, occurrence_id=None, server_id=target_server_id
                )

                if not existing:
                    break  # This agent_id is unique, use it

                logger.warning(
                    f"Agent {agent_id} on server={target_server_id} already exists "
                    f"(attempt {attempt + 1}/{max_attempts}), generating new suffix"
                )
            else:
                # Failed to generate unique ID after max attempts
                raise RuntimeError(
                    f"Failed to generate unique agent ID after {max_attempts} attempts. "
                    "This should be extremely rare - please try again."
                )

        # Allocate port
        allocated_port = self.port_manager.allocate_port(agent_id)

        # Generate service token for secure manager-to-agent communication
        service_token = self._generate_service_token()
        logger.info(f"Generated service token for agent {sanitize_agent_id(agent_id)}")

        # Generate random admin password to replace default
        admin_password = self._generate_admin_password()
        logger.info(f"Generated secure admin password for agent {sanitize_agent_id(agent_id)}")

        # Encrypt both token and password for storage
        from ciris_manager.crypto import get_token_encryption

        encryption = get_token_encryption()
        encrypted_token = encryption.encrypt_token(service_token)
        encrypted_password = encryption.encrypt_token(admin_password)

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

        # NOTE: We defer ownership changes until AFTER all files are written
        # This ensures the manager can write docker-compose.yml and init scripts
        import os
        import subprocess
        import shutil

        # Ownership change deferred to after all files are written (see below)

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
        # Default to billing disabled if not specified
        actual_billing_enabled = billing_enabled if billing_enabled is not None else False

        compose_config = self.compose_generator.generate_compose(
            agent_id=agent_id,
            agent_name=name,
            port=allocated_port,
            template=template,
            agent_dir=agent_dir,
            environment=environment,
            use_mock_llm=actual_use_mock_llm,
            enable_discord=actual_enable_discord,
            billing_enabled=actual_billing_enabled,
            billing_api_key=billing_api_key,
            database_url=database_url,
            database_ssl_cert_path=database_ssl_cert_path,
            agent_occurrence_id=agent_occurrence_id,
            oauth_callback_hostname=server_config.hostname,
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

        # NOW change ownership of data directories to container user (uid 1000)
        # This happens AFTER all files are written so the manager can create them
        # The compose file stays owned by ciris-manager so it can be updated later
        logger.debug("Changing ownership of data directories to container user (1000:1000)")
        try:
            # Only change ownership of the data directories, NOT the compose file
            dirs_to_chown = [
                agent_dir / "data",
                agent_dir / "data_archive",
                agent_dir / "logs",
                agent_dir / "config",
                agent_dir / "audit_keys",
                agent_dir / ".secrets",
            ]

            # Also include init_permissions.sh if it exists
            if (agent_dir / "init_permissions.sh").exists():
                dirs_to_chown.append(agent_dir / "init_permissions.sh")

            # Change ownership of all data directories
            result = subprocess.run(
                ["sudo", "chown", "-R", "1000:1000"] + [str(d) for d in dirs_to_chown],
                capture_output=True,
                text=True,
            )

            if result.returncode == 0:
                logger.info("Successfully set ownership of data directories to uid:gid 1000:1000")
            else:
                logger.warning(f"Failed to set data directory ownership: {result.stderr}")
                logger.warning(
                    f"Agent may have permission issues. Manual fix: sudo chown -R 1000:1000 {agent_dir}/data {agent_dir}/logs {agent_dir}/config"
                )
        except Exception as e:
            logger.warning(f"Could not change data directory ownership: {e}")
            logger.warning(
                f"Agent may have permission issues. Manual fix: sudo chown -R 1000:1000 {agent_dir}/data {agent_dir}/logs {agent_dir}/config"
            )

        # Register agent
        self.agent_registry.register_agent(
            agent_id=agent_id,
            name=name,
            port=allocated_port,
            template=template,
            compose_file=str(compose_path),
            service_token=encrypted_token,  # Store encrypted version
            admin_password=encrypted_password,  # Store encrypted version
            server_id=target_server_id,
            occurrence_id=agent_occurrence_id,  # For multi-instance database isolation
            custom_environment=environment,  # Store custom env vars for tracking
        )

        # Start the agent FIRST so Docker discovery can find it
        agent_logger.info(
            f"Starting container for agent {sanitize_agent_id(agent_id)} on server {target_server_id}"
        )
        try:
            await self._start_agent(agent_id, compose_path, target_server_id)
            agent_logger.info(
                f"✅ Container started for agent {sanitize_agent_id(agent_id)} on {target_server_id}"
            )
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

        # Change the admin password from default to the secure random one
        agent_logger.info(f"Securing admin password for agent {sanitize_agent_id(agent_id)}")
        try:
            await self._set_agent_admin_password(
                agent_id, allocated_port, admin_password, target_server_id
            )
            agent_logger.info(f"✅ Admin password secured for agent {sanitize_agent_id(agent_id)}")
        except Exception as e:
            agent_logger.warning(
                f"Failed to set admin password for {sanitize_agent_id(agent_id)}: {e}"
            )
            agent_logger.warning(
                "Agent created but still uses default password - this is a security risk"
            )

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
        """Update nginx configuration with all current agents across all servers."""
        try:
            # Discover all running agents (from Docker across all servers)
            from ciris_manager.docker_discovery import DockerAgentDiscovery

            discovery = DockerAgentDiscovery(
                agent_registry=self.agent_registry, docker_client_manager=self.docker_client
            )
            all_agents = discovery.discover_agents()

            # Group agents by server_id
            agents_by_server: Dict[str, list] = {}
            for agent in all_agents:
                # Get server_id directly from discovered agent object
                # This is already set by DockerAgentDiscovery and avoids ambiguity
                # when multiple agents share the same agent_id (multi-occurrence deployments)
                server_id = agent.server_id if hasattr(agent, "server_id") else "main"

                if server_id not in agents_by_server:
                    agents_by_server[server_id] = []
                agents_by_server[server_id].append(agent)

            # Update nginx on each server
            all_success = True
            for server_id, nginx_manager in self.nginx_managers.items():
                # Get agents for this server
                server_agents = agents_by_server.get(server_id, [])
                logger.info(
                    f"Updating nginx config for server {server_id} with {len(server_agents)} agents"
                )

                # Get server config
                server_config = self.docker_client.get_server_config(server_id)

                if server_config.is_local:
                    # Main server: update local nginx config file
                    success = nginx_manager.update_config(server_agents)
                    if success:
                        logger.info(
                            f"✅ Updated nginx config for main server with {len(server_agents)} agents"
                        )
                    else:
                        logger.error("❌ Failed to update nginx config for main server")
                        all_success = False
                else:
                    # Remote server: deploy config via Docker API
                    logger.info(f"Deploying nginx config to remote server {server_id}")

                    try:
                        # Generate config for this server
                        config_content = nginx_manager.generate_config(server_agents)

                        # Get Docker client for remote server
                        docker_client = self.docker_client.get_client(server_id)

                        # Deploy to remote nginx container
                        success = nginx_manager.deploy_remote_config(
                            config_content=config_content,
                            docker_client=docker_client,
                            container_name="ciris-nginx",
                        )

                        if success:
                            logger.info(
                                f"✅ Deployed nginx config to remote server {server_id} with {len(server_agents)} agents"
                            )
                        else:
                            logger.error(
                                f"❌ Failed to deploy nginx config to remote server {server_id}"
                            )
                            all_success = False
                    except Exception as e:
                        logger.error(
                            f"❌ Exception deploying nginx config to remote server {server_id}: {e}",
                            exc_info=True,
                        )
                        all_success = False

            return all_success

        except Exception as e:
            logger.error(f"Error updating nginx config: {e}", exc_info=True)
            return False

    async def _add_nginx_route(self, agent_id: str, port: int) -> None:
        """Update nginx configuration after adding a new agent."""
        logger.debug(f"_add_nginx_route called for agent {agent_id} on port {port}")
        # With the new template-based approach, we regenerate the entire config
        success = await self.update_nginx_config()
        if not success:
            raise RuntimeError("Failed to update nginx configuration")

    def _ensure_remote_server_shared_files(self, server_id: str) -> None:
        """
        Ensure shared files exist on a remote server.

        Copies common scripts like fix_agent_permissions.sh to /home/ciris/shared/
        on the remote server. This is done once per server, not per agent.

        Args:
            server_id: Remote server ID
        """
        logger.info(f"Ensuring shared files exist on remote server {server_id}")

        docker_client = self.docker_client.get_client(server_id)

        # Create /home/ciris/shared directory if it doesn't exist
        shared_dir_cmd = "mkdir -p /home/ciris/shared && chown 1000:1000 /home/ciris/shared"
        try:
            nginx_container = docker_client.containers.get("ciris-nginx")
            exec_result = nginx_container.exec_run(f"sh -c '{shared_dir_cmd}'", user="root")
            if exec_result.exit_code != 0:
                raise RuntimeError(f"Failed to create shared directory: {exec_result.output}")
        except Exception as e:
            logger.warning(f"Could not use nginx container for shared directory: {e}")
            docker_client.containers.run(
                "alpine:latest",
                command=f"sh -c '{shared_dir_cmd}'",
                volumes={"/home/ciris": {"bind": "/home/ciris", "mode": "rw"}},
                remove=True,
                detach=False,
            )

        # Copy fix_agent_permissions.sh script
        script_src = Path(__file__).parent / "templates" / "fix_agent_permissions.sh"
        if script_src.exists():
            with open(script_src, "r") as f:
                script_content = f.read()

            script_path = "/home/ciris/shared/fix_agent_permissions.sh"
            write_cmd = f"cat > {script_path} << 'EOFSCRIPT'\n{script_content}\nEOFSCRIPT\n"
            write_cmd += f"chmod 755 {script_path}\n"
            write_cmd += f"chown 1000:1000 {script_path}"

            try:
                nginx_container = docker_client.containers.get("ciris-nginx")
                exec_result = nginx_container.exec_run(f"sh -c '{write_cmd}'", user="root")
                if exec_result.exit_code != 0:
                    raise RuntimeError(
                        f"Failed to write fix_agent_permissions.sh: {exec_result.output}"
                    )
            except Exception as e:
                logger.warning(f"Could not use nginx container for script copy: {e}")
                docker_client.containers.run(
                    "alpine:latest",
                    command=f"sh -c '{write_cmd}'",
                    volumes={"/home/ciris": {"bind": "/home/ciris", "mode": "rw"}},
                    remove=True,
                    detach=False,
                )

            logger.info(f"✅ Copied fix_agent_permissions.sh to {server_id}:/home/ciris/shared/")
        else:
            logger.warning(f"Script not found at {script_src}")

    async def _create_remote_agent_directories(self, agent_id: str, server_id: str) -> None:
        """
        Create agent directory structure on a remote server.

        Args:
            agent_id: Agent identifier
            server_id: Remote server ID

        Raises:
            RuntimeError: If directory creation fails
        """
        logger.info(f"Creating agent directories for {agent_id} on remote server {server_id}")

        # Get Docker client for remote server
        docker_client = self.docker_client.get_client(server_id)

        # Base path for agent directories on remote server
        base_path = f"/opt/ciris/agents/{agent_id}"

        # Subdirectories to create with their permissions
        directories = {
            "data": "755",
            "data_archive": "755",
            "logs": "755",
            "config": "755",
            "audit_keys": "700",
            ".secrets": "700",
        }

        try:
            # First, create the base agent directory
            base_dir_cmd = f"mkdir -p {base_path} && chown 1000:1000 {base_path}"
            try:
                nginx_container = docker_client.containers.get("ciris-nginx")
                exec_result = nginx_container.exec_run(f"sh -c '{base_dir_cmd}'", user="root")
                if exec_result.exit_code != 0:
                    raise RuntimeError(f"Failed to create base directory: {exec_result.output}")
            except Exception as e:
                logger.warning(f"Could not use nginx container for base directory: {e}")
                docker_client.containers.run(
                    "alpine:latest",
                    command=f"sh -c '{base_dir_cmd}'",
                    volumes={"/opt/ciris": {"bind": "/opt/ciris", "mode": "rw"}},
                    remove=True,
                    detach=False,
                )
            logger.info(f"Created base directory: {base_path}")

            # Create subdirectories
            for dir_name, perms in directories.items():
                dir_path = f"{base_path}/{dir_name}"
                create_cmd = (
                    f"mkdir -p {dir_path} && chmod {perms} {dir_path} && chown 1000:1000 {dir_path}"
                )

                try:
                    nginx_container = docker_client.containers.get("ciris-nginx")
                    exec_result = nginx_container.exec_run(f"sh -c '{create_cmd}'", user="root")
                    if exec_result.exit_code != 0:
                        raise RuntimeError(f"Failed to create directory: {exec_result.output}")
                except Exception as e:
                    logger.warning(f"Could not use nginx container for {dir_name}: {e}")
                    docker_client.containers.run(
                        "alpine:latest",
                        command=f"sh -c '{create_cmd}'",
                        volumes={"/opt/ciris": {"bind": "/opt/ciris", "mode": "rw"}},
                        remove=True,
                        detach=False,
                    )

                logger.debug(f"Created directory {dir_path} with permissions {perms}")

            # Permissions are already set correctly by the alpine/nginx containers above
            # The fix_agent_permissions.sh script is only needed for local servers
            # For remote servers, we've already set ownership to 1000:1000 in each directory creation
            logger.info(
                f"✅ Created agent directories on {server_id} at {base_path} with correct permissions"
            )

        except Exception as e:
            logger.error(f"Failed to create agent directories on {server_id}: {e}")
            raise RuntimeError(f"Failed to create agent directories on {server_id}: {e}")

    async def _start_agent(
        self, agent_id: str, compose_path: Path, server_id: str = "main"
    ) -> None:
        """
        Start an agent container on the specified server.

        Args:
            agent_id: Agent identifier
            compose_path: Path to docker-compose.yml file
            server_id: Target server ID (defaults to 'main')
        """
        server_config = self.docker_client.get_server_config(server_id)

        if server_config.is_local:
            # Local server: use docker-compose CLI
            cmd = ["docker-compose", "-f", str(compose_path), "up", "-d"]
            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                logger.error(f"Failed to start agent {agent_id}: {stderr.decode()}")
                raise RuntimeError(f"Failed to start agent: {stderr.decode()}")

            logger.info(f"Started agent {agent_id} on local server")
        else:
            # Remote server: use Docker API to create container from compose config
            logger.info(f"Starting agent {agent_id} on remote server {server_id} via Docker API")

            import yaml

            # Read and parse compose file
            with open(compose_path, "r") as f:
                compose_config = yaml.safe_load(f)

            # Get the first service (should be the agent)
            services = compose_config.get("services", {})
            if not services:
                raise ValueError(f"No services found in compose file {compose_path}")

            service_name, service_config = next(iter(services.items()))

            # Get Docker client for remote server
            docker_client = self.docker_client.get_client(server_id)

            # Extract container configuration
            image = service_config.get("image")
            environment = service_config.get("environment", {})
            ports = service_config.get("ports", [])
            volumes_config = service_config.get("volumes", [])
            container_name = service_config.get("container_name", f"ciris-{agent_id}")
            restart_policy = service_config.get("restart", "unless-stopped")
            labels = service_config.get("labels", {})

            # Create agent directories on remote server BEFORE starting container
            logger.info(f"Creating agent directories on remote server {server_id}")
            await self._create_remote_agent_directories(agent_id, server_id)

            # Convert ports to port bindings format
            port_bindings: dict[str, int | tuple[str, int] | None] = {}
            for port_mapping in ports:
                if ":" in str(port_mapping):
                    host_port, container_port = str(port_mapping).split(":")
                    port_bindings[container_port] = int(host_port)

            # Convert volume mounts from docker-compose format to Docker SDK format
            # docker-compose format: ["./data:/app/data:rw", "./logs:/app/logs:rw"]
            # Docker SDK format: {"/host/path": {"bind": "/container/path", "mode": "rw"}}
            volumes: dict[str, dict[str, str]] = {}
            for volume_str in volumes_config:
                if isinstance(volume_str, str) and ":" in volume_str:
                    parts = volume_str.split(":")
                    if len(parts) >= 2:
                        host_path = parts[0]
                        container_path = parts[1]
                        mode = parts[2] if len(parts) > 2 else "rw"

                        # Convert paths to remote server paths
                        # Relative paths (e.g., "./data") -> /opt/ciris/agents/{agent_id}/data
                        if not host_path.startswith("/"):
                            host_path = f"/opt/ciris/agents/{agent_id}/{host_path.lstrip('./')}"
                        # Absolute paths referencing local agents dir -> convert to remote path
                        # e.g., /home/ciris/agents/{agent_id}/data -> /opt/ciris/agents/{agent_id}/data
                        elif f"agents/{agent_id}" in host_path:
                            # Extract the path after agents/{agent_id}/
                            path_after_agent = (
                                host_path.split(f"agents/{agent_id}/", 1)[1]
                                if f"agents/{agent_id}/" in host_path
                                else ""
                            )
                            if path_after_agent:
                                host_path = f"/opt/ciris/agents/{agent_id}/{path_after_agent}"
                            else:
                                # Just the agent directory itself
                                host_path = f"/opt/ciris/agents/{agent_id}"

                        volumes[host_path] = {"bind": container_path, "mode": mode}

            logger.info(f"Configured {len(volumes)} volume mounts for remote server {server_id}")

            try:
                # Create and start container with volume mounts
                docker_client.containers.run(
                    image=image,
                    name=container_name,
                    environment=environment,
                    ports=port_bindings,
                    volumes=volumes,
                    labels=labels,
                    detach=True,
                    restart_policy={"Name": restart_policy},
                )
                logger.info(
                    f"✅ Started container {container_name} on remote server {server_id} with {len(volumes)} volumes"
                )
            except Exception as e:
                logger.error(f"Failed to start container on remote server {server_id}: {e}")
                raise RuntimeError(f"Failed to start agent on {server_id}: {e}")

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
        1. Finds all stopped containers across ALL servers
        2. Checks if they're part of an active deployment
        3. Only restarts containers that crashed (not part of deployment)
        """
        try:
            import docker
            from docker.errors import DockerException

            # Get all registered agents
            agents = self.agent_registry.list_agents()

            # Check containers on ALL servers
            for server in self.config.servers:
                server_id = server.server_id

                try:
                    # Get Docker client for this server
                    client = self.docker_client.get_client(server_id)

                    # Filter agents for this server
                    server_agents = [
                        a
                        for a in agents
                        if (hasattr(a, "server_id") and a.server_id == server_id)
                        or (not hasattr(a, "server_id") and server_id == "main")
                    ]

                    logger.debug(f"Checking {len(server_agents)} agents on server {server_id}")

                except Exception as e:
                    logger.error(f"Failed to get Docker client for server {server_id}: {e}")
                    continue

                for agent_info in server_agents:
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

                        # Check if agent has do_not_autostart flag set (maintenance mode)
                        if hasattr(agent_info, "do_not_autostart") and agent_info.do_not_autostart:
                            # Skip logging crash warnings for agents in maintenance mode
                            continue

                        # This is a crashed container that should be restarted
                        logger.warning(
                            f"Container {container_name} crashed (exit code {exit_code}), checking restart policy"
                        )

                        logger.info(f"Attempting recovery for {agent_id} on server {server_id}")
                        # Restart using appropriate method for server type
                        compose_path = Path(agent_info.compose_file)
                        if compose_path.exists():
                            await self._restart_crashed_container(agent_id, compose_path, server_id)
                        else:
                            logger.error(f"Compose file not found for {agent_id}: {compose_path}")

                    except docker.errors.NotFound:
                        # Container doesn't exist - might be newly created or deleted
                        logger.debug(
                            f"Container {container_name} not found on {server_id}, may be new or deleted"
                        )
                    except Exception as e:
                        logger.error(
                            f"Error checking container {container_name} on {server_id}: {e}"
                        )

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
            # Get agent info to determine which server to check
            agent_info = self.agent_registry.get_agent(agent_id)
            server_id = (
                agent_info.server_id if agent_info and hasattr(agent_info, "server_id") else "main"
            )

            client = self.docker_client.get_client(server_id)
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

    async def _restart_crashed_container(
        self, agent_id: str, compose_path: Path, server_id: str = "main"
    ) -> None:
        """Restart a crashed container on the specified server.

        Args:
            agent_id: Agent identifier
            compose_path: Path to docker-compose.yml file
            server_id: Target server ID (defaults to 'main')
        """
        try:
            server_config = self.docker_client.get_server_config(server_id)
            logger.info(f"Restarting crashed container for agent {agent_id} on server {server_id}")

            if server_config.is_local:
                # Local server: use docker-compose
                cmd = ["docker-compose", "-f", str(compose_path), "up", "-d"]
                process = await asyncio.create_subprocess_exec(
                    *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()

                if process.returncode == 0:
                    logger.info(f"✅ Successfully restarted crashed container for agent {agent_id}")
                else:
                    logger.error(f"Failed to restart container for {agent_id}: {stderr.decode()}")
            else:
                # Remote server: use _start_agent which handles remote deployment
                await self._start_agent(agent_id, compose_path, server_id)
                logger.info(
                    f"✅ Successfully restarted crashed container for agent {agent_id} on {server_id}"
                )

        except Exception as e:
            logger.error(f"Error restarting container for {agent_id} on {server_id}: {e}")

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
        logger.info("DEBUG: _start_api_server method called")
        try:
            from fastapi import FastAPI
            from fastapi.responses import JSONResponse
            import uvicorn
            from typing import Union
            from .api.routes import create_routes
            from .api.auth import create_auth_routes, load_oauth_config
            from .api.device_auth_routes import create_device_auth_routes
            from .api.server_routes import create_server_routes

            app = FastAPI(title="CIRISManager API", version="1.0.0")
            logger.info("DEBUG: FastAPI app created in manager.py")

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
            logger.info("DEBUG: About to call create_routes in manager.py")
            router = create_routes(self)
            logger.info("DEBUG: create_routes returned successfully in manager.py")
            app.include_router(router, prefix="/manager/v1")
            logger.info("DEBUG: Included router in FastAPI app in manager.py")

            # Include server management routes
            server_router = create_server_routes(self)
            app.include_router(server_router, prefix="/manager/v1")
            logger.info("Server management routes mounted at /manager/v1/servers")

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

    async def delete_agent(
        self,
        agent_id: str,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> bool:
        """
        Delete an agent and clean up its resources.

        Args:
            agent_id: ID of agent to delete
            occurrence_id: Optional occurrence ID for multi-instance deployments
            server_id: Optional server ID for multi-server deployments

        Returns:
            True if successful
        """
        try:
            # Get agent info with composite key support
            if occurrence_id or server_id:
                # Use precise lookup
                agent_info = self.agent_registry.get_agent(
                    agent_id, occurrence_id=occurrence_id, server_id=server_id
                )
            else:
                # Try to find the agent - handle case of multiple instances
                all_instances = self.agent_registry.get_agents_by_agent_id(agent_id)
                if len(all_instances) == 0:
                    logger.error(f"Agent {agent_id} not found")
                    return False
                elif len(all_instances) == 1:
                    agent_info = all_instances[0]
                else:
                    # Multiple instances exist - need disambiguation
                    logger.error(
                        f"Multiple instances of agent {agent_id} exist. "
                        "Please specify occurrence_id and/or server_id"
                    )
                    return False

            if not agent_info:
                logger.error(f"Agent {agent_id} not found")
                return False

            # Determine which server the agent is on
            target_server_id = (
                agent_info.server_id
                if hasattr(agent_info, "server_id") and agent_info.server_id
                else "main"
            )
            server_config = self.docker_client.get_server_config(target_server_id)

            # Get compose path (used by both local and remote)
            compose_path = Path(agent_info.compose_file)

            # Stop the agent container
            if server_config.is_local:
                # Local server: use docker-compose
                if compose_path.exists():
                    logger.info(f"Stopping agent {agent_id} on local server")
                    cmd = ["docker-compose", "-f", str(compose_path), "down", "-v"]
                    process = await asyncio.create_subprocess_exec(
                        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                    )
                    await process.communicate()
            else:
                # Remote server: use Docker API
                logger.info(f"Stopping agent {agent_id} on remote server {target_server_id}")
                try:
                    docker_client = self.docker_client.get_client(target_server_id)
                    container_name = f"ciris-{agent_id}"
                    container = docker_client.containers.get(container_name)
                    container.stop(timeout=10)
                    container.remove(v=True)  # Remove volumes
                    logger.info(
                        f"✅ Stopped and removed container {container_name} on {target_server_id}"
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to stop container on remote server {target_server_id}: {e}"
                    )

            # Remove nginx routes (no conditional needed)
            logger.info(f"Removing nginx routes for {agent_id}")
            # Get current list of agents to pass to nginx manager
            from ciris_manager.docker_discovery import DockerAgentDiscovery

            discovery = DockerAgentDiscovery(
                agent_registry=self.agent_registry, docker_client_manager=self.docker_client
            )
            agents = discovery.discover_agents()
            self.nginx_manager.remove_agent_routes(agent_id, agents)

            # Free the port
            if agent_info.port:
                self.port_manager.release_port(agent_id)

            # Remove from registry - use composite key for multi-instance support
            self.agent_registry.unregister_agent(
                agent_id,
                occurrence_id=agent_info.occurrence_id
                if hasattr(agent_info, "occurrence_id")
                else None,
                server_id=agent_info.server_id if hasattr(agent_info, "server_id") else None,
            )

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

    def _generate_admin_password(self) -> str:
        """
        Generate a secure random admin password for agent.

        Replaces the default 'ciris_admin_password' with a cryptographically
        secure random password to prevent unauthorized access.

        Returns:
            URL-safe base64 encoded password (32 characters)
        """
        # Generate 24 bytes of random data (192 bits of entropy)
        return secrets.token_urlsafe(24)

    async def _set_agent_admin_password(
        self, agent_id: str, port: int, new_password: str, server_id: str = "main"
    ) -> None:
        """
        Set the agent's admin password via API.

        Args:
            agent_id: Agent identifier
            port: Agent API port
            new_password: New password to set
            server_id: Server ID where agent is running
        """
        import httpx

        # Determine the base URL based on server
        if server_id == "main":
            base_url = "localhost"
        else:
            server_config = self.docker_client.get_server_config(server_id)
            base_url = server_config.vpc_ip if server_config.vpc_ip else server_config.hostname

        # Step 1: Login with default admin credentials to get session token
        login_url = f"http://{base_url}:{port}/v1/auth/login"
        login_data = {"username": "admin", "password": "ciris_admin_password"}

        async with httpx.AsyncClient(timeout=10.0) as client:
            logger.info(f"Logging into agent {sanitize_agent_id(agent_id)} to set password")
            login_response = await client.post(login_url, json=login_data)

            if login_response.status_code != 200:
                raise RuntimeError(
                    f"Login failed: {login_response.status_code} - {login_response.text}"
                )

            login_result = login_response.json()
            session_token = login_result.get("access_token")
            admin_user_id = login_result.get("user_id")

            if not session_token or not admin_user_id:
                raise RuntimeError("Invalid login response - missing access_token or user_id")

            # Step 2: Change the admin password using session token
            password_url = f"http://{base_url}:{port}/v1/users/{admin_user_id}/password"
            password_data = {
                "current_password": "ciris_admin_password",
                "new_password": new_password,
            }

            headers = {
                "Authorization": f"Bearer {session_token}",
                "Content-Type": "application/json",
            }

            password_response = await client.put(password_url, headers=headers, json=password_data)

            if password_response.status_code != 200:
                raise RuntimeError(
                    f"Password change failed: {password_response.status_code} - {password_response.text}"
                )

            logger.info(f"Successfully set admin password for {sanitize_agent_id(agent_id)}")

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
    log_dir = "/var/log/cirismanager"
    if not os.access("/var/log", os.W_OK):
        # Can't write to /var/log, use local directory
        local_log_path = Path.home() / ".local" / "log" / "cirismanager"
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
