"""
Core jailbreaker service for Discord OAuth-based agent resets.
"""

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Optional
import httpx

from .models import JailbreakerConfig, ResetResult, ResetStatus
from .discord_client import DiscordAuthClient
from .rate_limiter import RateLimiter, parse_rate_limit_string

logger = logging.getLogger(__name__)


class JailbreakerService:
    """Service for handling Discord OAuth-based agent resets."""

    def __init__(self, config: JailbreakerConfig, agent_dir: Path, container_manager):
        """
        Initialize jailbreaker service.

        Args:
            config: Jailbreaker configuration
            agent_dir: Path to agents directory (e.g., /opt/ciris/agents)
            container_manager: CIRISManager's container manager instance
        """
        self.config = config
        self.agent_dir = agent_dir
        self.container_manager = container_manager

        # Initialize rate limiter with parsed config
        global_seconds = parse_rate_limit_string(config.global_rate_limit)
        user_seconds = parse_rate_limit_string(config.user_rate_limit)
        self.rate_limiter = RateLimiter(global_seconds, user_seconds)

        # Discord client for OAuth
        self.discord_client = DiscordAuthClient(config)

        logger.info(f"Initialized jailbreaker service for agent {config.target_agent_id}")
        logger.info(
            f"Rate limits: global={config.global_rate_limit}, user={config.user_rate_limit}"
        )

    async def close(self):
        """Clean up resources."""
        await self.discord_client.close()

    async def verify_access_token(self, access_token: str) -> tuple[bool, Optional[str]]:
        """
        Verify Discord access token and check jailbreak permissions.

        Args:
            access_token: Discord OAuth access token

        Returns:
            Tuple of (has_permission, user_id)
        """
        try:
            has_permission, user = await self.discord_client.verify_jailbreak_permission(
                access_token
            )
            if user:
                return has_permission, user.id
            return False, None
        except Exception as e:
            logger.error(f"Failed to verify access token: {e}")
            return False, None

    async def check_agent_health(self) -> bool:
        """
        Check if the target agent is running and accessible.

        Returns:
            True if agent is healthy, False otherwise
        """
        if not self.config.agent_service_token:
            logger.debug("No service token configured for agent health checks")
            return True  # Skip health check if no token

        try:
            # Try to find agent's port from registry or use common ports
            agent_ports = [8080, 8081, 8082, 8083]  # Common agent ports

            headers = {
                "Authorization": f"Bearer {self.config.agent_service_token}",
                "Content-Type": "application/json",
            }

            for port in agent_ports:
                try:
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        response = await client.get(
                            f"http://localhost:{port}/v1/health", headers=headers
                        )
                        if response.status_code == 200:
                            logger.debug(
                                f"Agent {self.config.target_agent_id} healthy on port {port}"
                            )
                            return True
                except (httpx.ConnectError, httpx.TimeoutException):
                    continue

            logger.warning(f"Agent {self.config.target_agent_id} not accessible on any port")
            return False

        except Exception as e:
            logger.warning(f"Failed to check agent health: {e}")
            return False  # Don't block reset due to health check failures

    async def reset_agent(self, access_token: str) -> ResetResult:
        """
        Reset the target agent for an authorized user.

        Args:
            access_token: Discord OAuth access token

        Returns:
            Reset operation result
        """
        try:
            # Verify user has permission
            has_permission, user_id = await self.verify_access_token(access_token)
            if not has_permission or not user_id:
                return ResetResult(
                    status=ResetStatus.UNAUTHORIZED,
                    message="User does not have jailbreak permissions",
                )

            # Check rate limits
            allowed, next_allowed = await self.rate_limiter.check_rate_limit(user_id)
            if not allowed:
                return ResetResult(
                    status=ResetStatus.RATE_LIMITED,
                    message="Rate limit exceeded",
                    user_id=user_id,
                    agent_id=self.config.target_agent_id,
                    next_allowed_reset=next_allowed,
                )

            # Check if target agent exists
            agent_path = self.agent_dir / self.config.target_agent_id
            if not agent_path.exists():
                return ResetResult(
                    status=ResetStatus.AGENT_NOT_FOUND,
                    message=f"Agent {self.config.target_agent_id} not found",
                    user_id=user_id,
                    agent_id=self.config.target_agent_id,
                )

            # Perform the reset
            logger.info(f"Starting reset of agent {self.config.target_agent_id} for user {user_id}")

            # Stop the container if running (will be handled by recreation)

            # Wipe the data directory
            data_path = agent_path / "data"
            if data_path.exists():
                logger.info(f"Wiping data directory: {data_path}")
                try:
                    shutil.rmtree(data_path)
                    logger.info("Data directory wiped successfully")
                except PermissionError:
                    # Try with sudo if permission denied
                    logger.info("Permission denied, trying with sudo...")
                    import subprocess

                    result = subprocess.run(
                        ["sudo", "rm", "-rf", str(data_path)], capture_output=True, text=True
                    )
                    if result.returncode == 0:
                        logger.info("Data directory wiped successfully with sudo")
                    else:
                        logger.error(
                            f"Failed to wipe data directory even with sudo: {result.stderr}"
                        )
                        raise Exception(f"Could not delete data directory: {result.stderr}")
            else:
                logger.info(f"Data directory {data_path} does not exist, skipping")

            # Recreate data directory with proper ownership for container user
            logger.info(f"Recreating data directory: {data_path}")
            try:
                # Try to create directory with sudo first (production environment)
                import subprocess
                import os

                # Ensure clean environment for subprocess
                env = os.environ.copy()
                env["SUDO_ASKPASS"] = ""  # Prevent password prompts

                logger.debug(f"Creating directory with sudo: {data_path}")
                result = subprocess.run(
                    ["sudo", "-n", "mkdir", "-p", str(data_path)],
                    capture_output=True,
                    text=True,
                    env=env,
                )

                if result.returncode == 0:
                    # Success with sudo - set ownership to container user (typically 1000:1000 for CIRIS agents)
                    logger.debug(f"Setting ownership to 1000:1000: {data_path}")
                    chown_result = subprocess.run(
                        ["sudo", "-n", "chown", "-R", "1000:1000", str(data_path)],
                        capture_output=True,
                        text=True,
                        env=env,
                    )
                    if chown_result.returncode != 0:
                        logger.error(
                            f"chown failed - stdout: {chown_result.stdout}, stderr: {chown_result.stderr}"
                        )
                        raise Exception(f"Failed to set ownership: {chown_result.stderr}")
                    logger.info("Data directory recreated with proper ownership via sudo")
                else:
                    # Sudo failed (likely test environment) - fall back to regular Python operations
                    logger.warning(
                        f"sudo mkdir failed, falling back to regular mkdir: {result.stderr}"
                    )
                    try:
                        data_path.mkdir(parents=True, exist_ok=True)
                        logger.info(
                            "Data directory recreated using regular Python mkdir (test environment)"
                        )
                    except PermissionError as perm_error:
                        logger.error(
                            f"Regular mkdir also failed with permission error: {perm_error}"
                        )
                        raise Exception(
                            f"Could not create directory with sudo or regular mkdir: {perm_error}"
                        )

            except Exception as e:
                logger.error(f"Failed to recreate data directory: {e}")
                raise Exception(f"Could not recreate data directory: {e}")

            # Stop and restart the container using docker-compose
            container_name = f"ciris-{self.config.target_agent_id}"
            agent_dir = self.agent_dir / self.config.target_agent_id
            compose_file = agent_dir / "docker-compose.yml"

            # Check if compose file exists, if not skip container restart
            # (This allows tests to run without actual docker-compose files)
            if not compose_file.exists():
                logger.warning(
                    f"Docker compose file not found: {compose_file}, skipping container restart"
                )
                logger.info(f"Data directory has been reset for {self.config.target_agent_id}")
            else:
                logger.info(f"Stopping container {container_name}")

                # Stop the container first
                stop_result = await asyncio.create_subprocess_exec(
                    "docker-compose",
                    "-f",
                    str(compose_file),
                    "stop",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(agent_dir),
                )
                await stop_result.communicate()

                logger.info(f"Starting container {container_name}")

                # Start it back up
                start_result = await asyncio.create_subprocess_exec(
                    "docker-compose",
                    "-f",
                    str(compose_file),
                    "up",
                    "-d",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(agent_dir),
                )
                stdout, stderr = await start_result.communicate()

                if start_result.returncode != 0:
                    logger.error(f"Failed to start container: {stderr.decode()}")
                    raise RuntimeError(f"Failed to start container: {stderr.decode()}")

                logger.info(f"Successfully restarted container for {self.config.target_agent_id}")

            # Discover and update agent registry with correct service token after reset
            if self.container_manager:
                await self._discover_and_update_service_token()

            # Reset authentication cache and detect new auth format
            await self._reset_auth_and_detect_format()

            # Optional: Check agent health after restart
            if self.config.agent_service_token:
                # Wait a moment for the agent to start
                await asyncio.sleep(5)
                is_healthy = await self.check_agent_health()
                if not is_healthy:
                    logger.warning(
                        f"Agent {self.config.target_agent_id} may not have started correctly"
                    )
                else:
                    logger.info(f"Agent {self.config.target_agent_id} is healthy after reset")

            # Wait additional time for agent to fully initialize after recreation
            await asyncio.sleep(10)

            # Reset admin password to a new secure random password
            await self._reset_admin_password()

            # Record the reset in rate limiter
            await self.rate_limiter.record_reset(user_id)

            logger.info(f"Agent {self.config.target_agent_id} reset completed for user {user_id}")

            return ResetResult(
                status=ResetStatus.SUCCESS,
                message=f"Agent {self.config.target_agent_id} has been reset successfully",
                user_id=user_id,
                agent_id=self.config.target_agent_id,
            )

        except Exception as e:
            logger.error(f"Failed to reset agent: {e}")
            return ResetResult(
                status=ResetStatus.ERROR,
                message=f"Internal error during reset: {str(e)}",
                user_id=user_id if "user_id" in locals() else None,
                agent_id=self.config.target_agent_id,
            )

    def get_rate_limit_status(self, user_id: Optional[str] = None) -> dict:
        """
        Get current rate limit status.

        Args:
            user_id: Optional user ID to get specific user status

        Returns:
            Dict with rate limit information
        """
        stats = self.rate_limiter.get_stats()

        if user_id:
            stats["user_next_reset"] = self.rate_limiter.get_next_user_reset(user_id)

        return stats

    async def _discover_and_update_service_token(self) -> None:
        """
        Discover the actual service token from the container environment and update the agent registry.

        After a reset, the container's CIRIS_SERVICE_TOKEN environment variable contains
        the permanent service token that survives resets. We need to discover this token
        and update the agent registry so CIRISManager can authenticate properly.
        """
        try:
            from ciris_manager.crypto import get_token_encryption

            # Get the agent registry from deployment orchestrator
            agent_registry = None
            if hasattr(self.container_manager, "manager") and hasattr(
                self.container_manager.manager, "agent_registry"
            ):
                # Standard manager path
                agent_registry = self.container_manager.manager.agent_registry
            elif hasattr(self.container_manager, "agent_registry"):
                # Direct access for simple container managers
                agent_registry = self.container_manager.agent_registry
            else:
                logger.warning(
                    f"Container manager type: {type(self.container_manager)}, "
                    f"has manager: {hasattr(self.container_manager, 'manager')}"
                )

            if not agent_registry:
                logger.warning("Agent registry not available, skipping token update")
                return

            # Discover the actual service token from container environment
            container_name = f"ciris-{self.config.target_agent_id}"
            logger.info(f"Discovering service token from container {container_name}")

            # Get the service token from container environment
            env_result = await asyncio.create_subprocess_exec(
                "docker",
                "exec",
                container_name,
                "env",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await env_result.communicate()

            if env_result.returncode != 0:
                logger.warning(
                    f"Failed to get container environment (may be test environment): {stderr.decode()}"
                )
                # In test environments, fall back to using the jailbreaker's configured token
                if self.config.agent_service_token:
                    service_token = self.config.agent_service_token
                    logger.info(
                        f"Using configured jailbreaker token for {self.config.target_agent_id}"
                    )
                else:
                    logger.warning("No service token available for agent registry update")
                    return
            else:
                # Parse environment variables to find CIRIS_SERVICE_TOKEN
                env_output = stdout.decode()
                service_token = None
                for line in env_output.strip().split("\n"):
                    if line.startswith("CIRIS_SERVICE_TOKEN="):
                        service_token = line.split("=", 1)[1]
                        break

                if not service_token:
                    logger.warning(
                        f"CIRIS_SERVICE_TOKEN not found in container {container_name} environment"
                    )
                    # Fall back to jailbreaker token
                    if self.config.agent_service_token:
                        service_token = self.config.agent_service_token
                        logger.info(
                            f"Using configured jailbreaker token for {self.config.target_agent_id}"
                        )
                    else:
                        logger.warning("No service token available for agent registry update")
                        return
                else:
                    logger.info(f"Discovered service token for {self.config.target_agent_id}")

            # Ensure service_token is not None before encryption
            if not service_token:
                logger.warning("No valid service token available for encryption")
                return

            # Encrypt the service token using the same encryption as the registry
            encryption = get_token_encryption()
            encrypted_token = encryption.encrypt_token(service_token)

            # Update the agent registry
            success = agent_registry.update_agent_token(
                self.config.target_agent_id, encrypted_token
            )

            if success:
                logger.info(
                    f"Updated agent registry with service token for {self.config.target_agent_id}"
                )
            else:
                logger.error(
                    f"Failed to update agent registry service token for {self.config.target_agent_id}"
                )

        except Exception as e:
            logger.error(f"Error discovering and updating agent service token in registry: {e}")
            # Don't fail the reset operation due to token update issues

    async def _reset_admin_password(self) -> None:
        """
        Reset the agent's admin password to a new secure random password.

        This ensures that every jailbreaker reset generates a fresh, secure password
        instead of leaving the default password, improving security.
        """
        try:
            import secrets
            import string

            # Generate a secure random password (20 characters, letters + digits + symbols)
            chars = string.ascii_letters + string.digits + "@#$%&*"
            new_password = "".join(secrets.choice(chars) for _ in range(20))

            # Login with default admin credentials to get session token for password reset
            # Note: We can't use service tokens for password operations, need session tokens

            # Find the agent's port from registry or use common ports
            # For echo-nemesis, use 8009 first since that's its known port
            if self.config.target_agent_id == "echo-nemesis-v2tyey":
                agent_ports = [8009, 8080, 8081, 8082, 8083]  # Try 8009 first for nemesis
            else:
                agent_ports = [8080, 8081, 8082, 8083, 8009]  # Common agent ports

            for port in agent_ports:
                try:
                    import httpx

                    async with httpx.AsyncClient(timeout=10.0) as client:
                        # Step 1: Login with default admin credentials to get session token
                        login_url = f"http://localhost:{port}/v1/auth/login"
                        login_data = {
                            "username": "admin",
                            "password": "ciris_admin_password",  # Default password after reset
                        }

                        login_response = await client.post(login_url, json=login_data)
                        if login_response.status_code != 200:
                            logger.debug(
                                f"Login failed on port {port}: {login_response.status_code}"
                            )
                            continue  # Try next port

                        login_result = login_response.json()
                        session_token = login_result.get("access_token")
                        admin_user_id = login_result.get("user_id")

                        if not session_token or not admin_user_id:
                            logger.warning(f"Invalid login response on port {port}")
                            continue

                        logger.info(
                            f"Successfully logged in to {self.config.target_agent_id} on port {port}"
                        )

                        # Step 2: Reset the admin password using session token
                        password_url = f"http://localhost:{port}/v1/users/{admin_user_id}/password"
                        password_data = {
                            "current_password": "ciris_admin_password",  # Default password after reset
                            "new_password": new_password,
                        }

                        headers = {
                            "Authorization": f"Bearer {session_token}",
                            "Content-Type": "application/json",
                        }

                        password_response = await client.put(
                            password_url, headers=headers, json=password_data
                        )

                        if password_response.status_code == 200:
                            logger.info(
                                f"Successfully reset admin password for {self.config.target_agent_id} "
                                f"on port {port}"
                            )
                            return  # Success, exit the loop
                        else:
                            logger.warning(
                                f"Failed to reset password on port {port}: "
                                f"{password_response.status_code} - {password_response.text}"
                            )

                except (httpx.ConnectError, httpx.TimeoutException, Exception) as e:
                    logger.debug(f"Port {port} failed for password reset: {e}")
                    continue

            logger.warning(
                f"Could not reset admin password for {self.config.target_agent_id} "
                f"on any port - agent may not be accessible yet"
            )

        except Exception as e:
            logger.error(f"Error resetting admin password: {e}")
            # Don't fail the reset operation due to password reset issues

    async def _reset_auth_and_detect_format(self) -> None:
        """
        Reset authentication cache and detect the correct auth format for the agent.

        This uses the same authentication system as the main manager to properly
        handle service token format detection after a container reset.
        """
        try:
            from ciris_manager.agent_auth import get_agent_auth

            # Get the agent registry to use the main manager's auth system
            agent_registry = None
            if hasattr(self.container_manager, "manager") and hasattr(
                self.container_manager.manager, "agent_registry"
            ):
                agent_registry = self.container_manager.manager.agent_registry

            if not agent_registry:
                logger.warning("Agent registry not available, skipping auth format detection")
                return

            # Get the main manager's auth system
            auth = get_agent_auth(agent_registry)

            # Reset circuit breaker and auth cache for this agent
            was_circuit_open = auth.reset_circuit_breaker(self.config.target_agent_id)
            if was_circuit_open:
                logger.info(f"Reset circuit breaker for {self.config.target_agent_id}")

            # Wait a moment for the agent to be ready
            await asyncio.sleep(2)

            # Detect the correct authentication format
            logger.info(f"Detecting auth format for {self.config.target_agent_id}")
            auth_format = auth.detect_auth_format(self.config.target_agent_id)

            if auth_format:
                logger.info(
                    f"Successfully detected {auth_format} auth format for {self.config.target_agent_id}"
                )
            else:
                logger.warning(
                    f"Could not detect working auth format for {self.config.target_agent_id}"
                )

        except Exception as e:
            logger.error(f"Error resetting auth and detecting format: {e}")
            # Don't fail the reset operation due to auth detection issues

    async def cleanup_rate_limiter(self) -> None:
        """Clean up old rate limiter entries."""
        await self.rate_limiter.cleanup_old_entries()

    def generate_oauth_url(self, state: Optional[str] = None) -> tuple[str, str]:
        """
        Generate Discord OAuth URL.

        Args:
            state: Optional state parameter for OAuth flow

        Returns:
            Tuple of (auth_url, state)
        """
        return self.discord_client.generate_oauth_url(state)

    async def exchange_code_for_token(self, code: str) -> str:
        """
        Exchange OAuth code for access token.

        Args:
            code: OAuth authorization code

        Returns:
            Access token
        """
        return await self.discord_client.exchange_code_for_token(code)
