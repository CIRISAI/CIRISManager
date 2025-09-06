#!/usr/bin/env python3
"""
Reset agent admin passwords to default to allow token regeneration.

This script connects to agents that have changed passwords,
resets them to default, gets new tokens, and optionally changes passwords back.
"""

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Optional

import httpx

# Add the project root to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from ciris_manager.crypto import get_token_encryption

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class AgentPasswordManager:
    """Manages agent password resets and token regeneration."""

    def __init__(
        self, metadata_path: Path = Path("/opt/ciris/agents/metadata.json"), dry_run: bool = False
    ):
        self.metadata_path = metadata_path
        self.dry_run = dry_run
        self.agents_to_fix = [
            "datum",
            "echo-core-jm2jy2",
            "echo-speculative-4fc6ru",
            "sage-2wnuc8",
            "scout-u7e9s3",
        ]

    async def reset_agent_password(self, agent_id: str, port: int) -> bool:
        """Reset agent admin password to default via API."""
        try:
            # This approach won't work since we don't know current passwords
            logger.error(f"Cannot reset password for {agent_id} - need admin access")
            return False

        except Exception as e:
            logger.error(f"Failed to reset password for {agent_id}: {e}")
            return False

    async def restart_agent_container(self, agent_id: str) -> bool:
        """Restart agent container to reset password to default."""
        try:
            import docker

            client = docker.from_env()

            # Find container name pattern
            container_name = f"ciris-{agent_id}"
            if agent_id == "echo-core-jm2jy2":
                container_name = "ciris-echo-core-jm2jy2"
            elif agent_id == "echo-speculative-4fc6ru":
                container_name = "ciris-echo-speculative-4fc6ru"
            elif agent_id == "sage-2wnuc8":
                container_name = "ciris-sage-2wnuc8"
            elif agent_id == "scout-u7e9s3":
                container_name = "ciris-scout-u7e9s3"

            if self.dry_run:
                logger.info(f"DRY RUN: Would restart container {container_name}")
                return True

            container = client.containers.get(container_name)
            container.restart()
            logger.info(f"Restarted container {container_name}")

            # Wait for container to be ready
            await asyncio.sleep(10)
            return True

        except Exception as e:
            logger.error(f"Failed to restart container for {agent_id}: {e}")
            return False

    async def get_fresh_token(self, agent_id: str, port: int) -> Optional[str]:
        """Get fresh service token after password reset."""
        try:
            login_url = f"http://localhost:{port}/v1/auth/login"
            login_data = {
                "username": "admin",
                "password": "ciris_admin_password",  # Default password after restart
            }

            async with httpx.AsyncClient(timeout=15.0) as client:
                logger.info(f"Logging into {agent_id} on port {port}")
                response = await client.post(login_url, json=login_data)

                if response.status_code != 200:
                    logger.error(
                        f"Login failed for {agent_id}: {response.status_code} {response.text}"
                    )
                    return None

                login_result = response.json()
                access_token = login_result.get("access_token")
                if not access_token:
                    logger.error(f"No access token in login response for {agent_id}")
                    return None

                # Use access token as service token (same as our working script)
                logger.info(f"Got fresh token for {agent_id}")
                return access_token

        except Exception as e:
            logger.error(f"Failed to get fresh token for {agent_id}: {e}")
            return None

    async def fix_all_agents(self):
        """Fix all broken agents by restarting containers and getting fresh tokens."""

        with open(self.metadata_path) as f:
            metadata = json.load(f)

        token_encryption = get_token_encryption()
        success_count = 0

        for agent_id in self.agents_to_fix:
            if agent_id not in metadata["agents"]:
                logger.warning(f"Agent {agent_id} not found in metadata")
                continue

            agent_data = metadata["agents"][agent_id]
            port = agent_data.get("port")
            if not port:
                logger.warning(f"No port found for {agent_id}")
                continue

            logger.info(f"Processing {agent_id}...")

            # Step 1: Restart container to reset password
            if not await self.restart_agent_container(agent_id):
                continue

            # Step 2: Get fresh token with default password
            fresh_token = await self.get_fresh_token(agent_id, port)
            if not fresh_token:
                continue

            # Step 3: Encrypt and store token
            try:
                encrypted_token = token_encryption.encrypt_token(fresh_token)

                if not self.dry_run:
                    agent_data["service_token"] = encrypted_token

                logger.info(f"Successfully updated token for {agent_id}")
                success_count += 1

            except Exception as e:
                logger.error(f"Failed to encrypt token for {agent_id}: {e}")
                continue

        if success_count > 0 and not self.dry_run:
            # Create backup and save
            backup_path = self.metadata_path.with_suffix(".json.backup-password-reset")
            import shutil

            shutil.copy2(self.metadata_path, backup_path)
            logger.info(f"Created backup at {backup_path}")

            with open(self.metadata_path, "w") as f:
                json.dump(metadata, f, indent=2)
            logger.info("Updated metadata saved")

        logger.info(
            f"Password reset complete: {success_count}/{len(self.agents_to_fix)} agents fixed"
        )
        return success_count, len(self.agents_to_fix)


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="Reset agent passwords and regenerate tokens")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be done without making changes"
    )
    parser.add_argument(
        "--metadata-path",
        default="/opt/ciris/agents/metadata.json",
        help="Path to metadata.json file",
    )

    args = parser.parse_args()

    if args.dry_run:
        logger.info("DRY RUN MODE - No changes will be made")

    manager = AgentPasswordManager(metadata_path=Path(args.metadata_path), dry_run=args.dry_run)

    try:
        success_count, total_count = await manager.fix_all_agents()

        if success_count < total_count:
            logger.warning("Some agents failed - check logs above")
            sys.exit(1)
        else:
            logger.info("All agents processed successfully!")
            if not args.dry_run:
                logger.info(
                    "Restart CIRISManager to pick up new tokens: systemctl restart ciris-manager"
                )

    except Exception as e:
        logger.error(f"Password reset failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
