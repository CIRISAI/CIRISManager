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

            # Stop the container if running
            container_name = f"ciris-{self.config.target_agent_id}"
            await self._stop_container(container_name)

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

            # Restart the container
            await self._start_container(container_name)

            # Update agent registry with correct service token after reset
            if self.config.agent_service_token and self.container_manager:
                await self._update_agent_service_token()

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

    async def _stop_container(self, container_name: str) -> None:
        """Stop a Docker container."""
        try:
            logger.debug(f"Stopping container: {container_name}")
            await self.container_manager.stop_container(container_name)

            # Wait a bit for graceful shutdown
            await asyncio.sleep(2)
            logger.debug(f"Container {container_name} stopped")

        except Exception as e:
            logger.warning(f"Failed to stop container {container_name}: {e}")
            # Continue with reset even if stop fails

    async def _start_container(self, container_name: str) -> None:
        """Start a Docker container."""
        try:
            logger.debug(f"Starting container: {container_name}")
            await self.container_manager.start_container(container_name)

            # Wait a bit for startup
            await asyncio.sleep(3)
            logger.debug(f"Container {container_name} started")

        except Exception as e:
            logger.error(f"Failed to start container {container_name}: {e}")
            raise

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

    async def _update_agent_service_token(self) -> None:
        """
        Update the agent registry with the correct service token after reset.

        This ensures that CIRISManager uses the same service token that jailbreaker
        is configured with, preventing authentication failures after agent resets.
        """
        try:
            from ciris_manager.crypto import get_token_encryption

            # Get the agent registry from container manager
            if not hasattr(self.container_manager, "agent_registry"):
                logger.warning("Container manager has no agent_registry, skipping token update")
                return

            agent_registry = self.container_manager.agent_registry

            # Encrypt the jailbreaker service token using the same encryption as the registry
            encryption = get_token_encryption()
            encrypted_token = encryption.encrypt_token(self.config.agent_service_token)

            # Update the agent registry
            success = agent_registry.update_agent_token(
                self.config.target_agent_id, encrypted_token
            )

            if success:
                logger.info(
                    f"Updated agent registry service token for {self.config.target_agent_id} "
                    f"to match jailbreaker token"
                )
            else:
                logger.error(
                    f"Failed to update agent registry service token for {self.config.target_agent_id}"
                )

        except Exception as e:
            logger.error(f"Error updating agent service token in registry: {e}")
            # Don't fail the reset operation due to token update issues

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
