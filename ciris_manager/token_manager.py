"""
Service token management for CIRIS agents.

Provides functionality to manage, rotate, and recover service tokens
used for secure communication between CIRISManager and agents.
"""

import asyncio
import json
import logging
import secrets
import shutil
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass

import httpx
from httpx import AsyncClient

from ciris_manager.agent_registry import AgentRegistry, RegisteredAgent
from ciris_manager.crypto import TokenEncryption
from ciris_manager.agent_auth import get_agent_auth

logger = logging.getLogger(__name__)


class TokenStatus(Enum):
    """Token status enumeration."""

    VALID = "valid"
    INVALID = "invalid"
    MISSING = "missing"
    CORRUPTED = "corrupted"
    UNENCRYPTED = "unencrypted"
    EXPIRED = "expired"


@dataclass
class TokenHealth:
    """Token health information for an agent."""

    agent_id: str
    status: TokenStatus
    last_updated: Optional[datetime] = None
    auth_tested: bool = False
    auth_successful: bool = False
    error_message: Optional[str] = None


@dataclass
class TokenRotationResult:
    """Result of a token rotation operation."""

    agent_id: str
    success: bool
    old_token_backed_up: bool
    new_token_generated: bool
    container_restarted: bool
    auth_verified: bool
    error_message: Optional[str] = None


class TokenManager:
    """Manages service tokens for CIRIS agents."""

    def __init__(
        self,
        registry: AgentRegistry,
        agents_dir: Optional[Path] = None,
        docker_client_manager: Optional[Any] = None,
    ):
        """
        Initialize token manager.

        Args:
            registry: Agent registry instance
            agents_dir: Directory containing agent configurations
            docker_client_manager: Optional multi-server Docker client manager
        """
        self.registry = registry
        self.encryption = TokenEncryption()
        self.agents_dir = agents_dir or Path("/opt/ciris/agents")
        self.backup_dir = self.agents_dir / "token_backups"
        self.backup_dir.mkdir(exist_ok=True)
        self.docker_client_manager = docker_client_manager

    async def list_tokens(self) -> List[TokenHealth]:
        """
        List all agents and their token status.

        Returns:
            List of TokenHealth objects for all agents
        """
        agents = self.registry.list_agents()
        token_health = []

        for agent in agents:
            health = await self._check_token_health(agent)
            token_health.append(health)

        return token_health

    async def _check_token_health(self, agent: RegisteredAgent) -> TokenHealth:
        """Check health of a single agent's token."""
        health = TokenHealth(agent_id=agent.agent_id, status=TokenStatus.MISSING)

        # Check if token exists
        if not agent.service_token:
            health.status = TokenStatus.MISSING
            health.error_message = "No service token found in metadata"
            return health

        # Check if token is encrypted
        token = agent.service_token
        if len(token) < 100:
            health.status = TokenStatus.UNENCRYPTED
            health.error_message = "Token appears to be unencrypted"
            return health

        # Try to decrypt token
        try:
            decrypted = self.encryption.decrypt_token(token)
            if decrypted:
                health.status = TokenStatus.VALID
            else:
                health.status = TokenStatus.CORRUPTED
                health.error_message = "Failed to decrypt token"
        except Exception as e:
            health.status = TokenStatus.CORRUPTED
            health.error_message = f"Decryption error: {str(e)}"

        return health

    async def verify_token(self, agent_id: str) -> Tuple[bool, str]:
        """
        Verify that an agent's token is working.

        Args:
            agent_id: ID of the agent to verify

        Returns:
            Tuple of (success, message)
        """
        agent = self.registry.get_agent(agent_id)
        if not agent:
            return False, f"Agent {agent_id} not found"

        # Get auth headers using the token
        auth = get_agent_auth()
        headers = auth.get_auth_headers(agent_id)

        if not headers:
            return False, "Failed to get authentication headers"

        # Test the token by calling the agent's health endpoint
        try:
            # Get the correct URL for this agent's server
            if self.docker_client_manager:
                try:
                    server_config = self.docker_client_manager.get_server_config(agent.server_id)
                    if server_config.is_local:
                        url = f"http://localhost:{agent.port}/v1/system/health"
                    else:
                        url = f"http://{server_config.vpc_ip}:{agent.port}/v1/system/health"
                except Exception:
                    # Fallback to localhost if server config fails
                    url = f"http://localhost:{agent.port}/v1/system/health"
            else:
                url = f"http://localhost:{agent.port}/v1/system/health"

            async with AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)

                if response.status_code == 200:
                    return True, "Token authentication successful"
                elif response.status_code == 401:
                    return False, "Token authentication failed (401 Unauthorized)"
                else:
                    return False, f"Unexpected response: {response.status_code}"

        except httpx.ConnectError:
            return False, f"Failed to connect to agent on port {agent.port}"
        except Exception as e:
            return False, f"Error testing token: {str(e)}"

    async def regenerate_token(
        self, agent_id: str, restart_container: bool = True
    ) -> TokenRotationResult:
        """
        Regenerate token for a specific agent.

        Args:
            agent_id: ID of the agent
            restart_container: Whether to restart the container with new token

        Returns:
            TokenRotationResult with operation details
        """
        result = TokenRotationResult(
            agent_id=agent_id,
            success=False,
            old_token_backed_up=False,
            new_token_generated=False,
            container_restarted=False,
            auth_verified=False,
        )

        # Get agent info
        agent = self.registry.get_agent(agent_id)
        if not agent:
            result.error_message = f"Agent {agent_id} not found"
            return result

        # Backup existing token
        if agent.service_token:
            backup_file = self.backup_dir / f"{agent_id}_{datetime.now().isoformat()}.token"
            try:
                import aiofiles  # type: ignore

                async with aiofiles.open(backup_file, "w") as f:
                    await f.write(
                        json.dumps(
                            {
                                "agent_id": agent_id,
                                "token": agent.service_token,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            }
                        )
                    )
                result.old_token_backed_up = True
                logger.info(f"Backed up token for {agent_id} to {backup_file}")
            except Exception as e:
                logger.error(f"Failed to backup token: {e}")

        # Generate new token
        new_token = secrets.token_urlsafe(32)
        encrypted_token = self.encryption.encrypt_token(new_token)
        result.new_token_generated = True

        # Update registry
        self.registry.update_agent_token(agent_id, encrypted_token)
        logger.info(f"Generated new token for {agent_id}")

        # Restart container if requested
        if restart_container:
            success = await self._restart_agent_with_token(agent_id, new_token)
            result.container_restarted = success

            if success:
                # Wait for container to be ready
                await asyncio.sleep(5)

                # Verify new token works
                verified, message = await self.verify_token(agent_id)
                result.auth_verified = verified
                if not verified:
                    result.error_message = f"Token verification failed: {message}"
            else:
                result.error_message = "Failed to restart container"

        result.success = result.new_token_generated and (
            not restart_container or result.auth_verified
        )
        return result

    async def _restart_agent_with_token(self, agent_id: str, token: str) -> bool:
        """Restart an agent container with a new token."""
        agent = self.registry.get_agent(agent_id)
        if not agent or not agent.compose_file:
            return False

        compose_path = Path(agent.compose_file)
        if not compose_path.exists():
            logger.error(f"Compose file not found: {compose_path}")
            return False

        try:
            # This is a simple approach - in production, use proper YAML parsing
            # For now, we'll use docker-compose with environment override
            env_file = compose_path.parent / ".env"
            env_content = []

            if env_file.exists():
                import aiofiles  # type: ignore

                async with aiofiles.open(env_file, "r") as f:
                    lines = await f.readlines()
                    for line in lines:
                        if not line.startswith("CIRIS_SERVICE_TOKEN="):
                            env_content.append(line)

            env_content.append(f"CIRIS_SERVICE_TOKEN={token}\n")

            async with aiofiles.open(env_file, "w") as f:
                await f.writelines(env_content)

            # Restart container
            cmd = ["docker-compose", "-f", str(compose_path), "up", "-d", "--force-recreate"]
            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                logger.info(f"Successfully restarted {agent_id} with new token")
                return True
            else:
                logger.error(f"Failed to restart {agent_id}: {stderr.decode()}")
                return False

        except Exception as e:
            logger.error(f"Error restarting agent {agent_id}: {e}")
            return False

    async def recover_tokens_from_containers(self) -> Dict[str, bool]:
        """
        Recover tokens from running containers and update metadata.

        Returns:
            Dictionary mapping agent_id to recovery success
        """
        results = {}
        agents = self.registry.list_agents()

        for agent in agents:
            agent_id = agent.agent_id
            container_name = f"ciris-{agent_id}"

            try:
                # Get token from container environment
                proc = await asyncio.create_subprocess_exec(
                    "docker",
                    "exec",
                    container_name,
                    "printenv",
                    "CIRIS_SERVICE_TOKEN",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                try:
                    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
                    raise

                if proc.returncode == 0:
                    token = stdout.decode().strip()
                    if token:
                        # Encrypt and update
                        encrypted = self.encryption.encrypt_token(token)
                        self.registry.update_agent_token(agent_id, encrypted)
                        results[agent_id] = True
                        logger.info(f"Recovered token for {agent_id}")
                    else:
                        results[agent_id] = False
                        logger.warning(f"Empty token for {agent_id}")
                else:
                    results[agent_id] = False
                    logger.warning(f"Could not get token from {container_name}")

            except asyncio.TimeoutError:
                results[agent_id] = False
                logger.error(f"Timeout getting token from {container_name}")
            except Exception as e:
                results[agent_id] = False
                logger.error(f"Error recovering token for {agent_id}: {e}")

        return results

    async def validate_all_tokens(self) -> Dict[str, TokenHealth]:
        """
        Validate health of all agent tokens.

        Returns:
            Dictionary mapping agent_id to TokenHealth
        """
        agents = self.registry.list_agents()
        results = {}

        for agent in agents:
            health = await self._check_token_health(agent)

            # Also test authentication if token seems valid
            if health.status == TokenStatus.VALID:
                verified, message = await self.verify_token(agent.agent_id)
                health.auth_tested = True
                health.auth_successful = verified
                if not verified:
                    health.error_message = message

            results[agent.agent_id] = health

        return results

    async def rotate_all_tokens(
        self, strategy: str = "immediate", canary_percentage: int = 10
    ) -> Dict[str, TokenRotationResult]:
        """
        Rotate tokens for all agents.

        Args:
            strategy: Rotation strategy ('immediate', 'canary')
            canary_percentage: Percentage of agents for canary deployment

        Returns:
            Dictionary mapping agent_id to rotation results
        """
        agents = self.registry.list_agents()
        results = {}

        if strategy == "canary":
            # Start with a subset of agents
            canary_count = max(1, len(agents) * canary_percentage // 100)
            canary_agents = agents[:canary_count]

            logger.info(f"Starting canary token rotation for {len(canary_agents)} agents")

            # Rotate canary agents
            for agent in canary_agents:
                result = await self.regenerate_token(agent.agent_id)
                results[agent.agent_id] = result

                if not result.success:
                    logger.error(f"Canary rotation failed for {agent.agent_id}, aborting")
                    return results

            # Wait and verify canary agents
            logger.info("Waiting 30 seconds to verify canary agents...")
            await asyncio.sleep(30)

            canary_healthy = True
            for agent in canary_agents:
                verified, _ = await self.verify_token(agent.agent_id)
                if not verified:
                    canary_healthy = False
                    logger.error(f"Canary agent {agent.agent_id} failed verification")
                    break

            if not canary_healthy:
                logger.error("Canary deployment failed, aborting full rotation")
                return results

            logger.info("Canary successful, proceeding with remaining agents")
            remaining_agents = agents[canary_count:]

        else:
            remaining_agents = agents

        # Rotate remaining agents
        for agent in remaining_agents:
            if agent.agent_id not in results:
                result = await self.regenerate_token(agent.agent_id)
                results[agent.agent_id] = result

        return results

    def backup_metadata(self) -> Path:
        """
        Create a backup of the current metadata.

        Returns:
            Path to backup file
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.backup_dir / f"metadata_backup_{timestamp}.json"

        metadata_path = self.agents_dir / "metadata.json"
        if metadata_path.exists():
            shutil.copy2(metadata_path, backup_path)
            logger.info(f"Created metadata backup at {backup_path}")
            return backup_path
        else:
            raise FileNotFoundError(f"Metadata file not found at {metadata_path}")

    def restore_metadata(self, backup_path: Path) -> bool:
        """
        Restore metadata from a backup.

        Args:
            backup_path: Path to backup file

        Returns:
            True if successful
        """
        if not backup_path.exists():
            logger.error(f"Backup file not found: {backup_path}")
            return False

        metadata_path = self.agents_dir / "metadata.json"
        try:
            shutil.copy2(backup_path, metadata_path)
            logger.info(f"Restored metadata from {backup_path}")

            # Reload registry
            self.registry._load_metadata()
            return True
        except Exception as e:
            logger.error(f"Failed to restore metadata: {e}")
            return False
