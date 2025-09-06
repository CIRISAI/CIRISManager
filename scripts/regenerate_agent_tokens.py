#!/usr/bin/env python3
"""
Regenerate service tokens for all CIRIS agents.

This script connects to each agent, gets a fresh service token,
encrypts it with the current encryption key, and updates metadata.json.

Usage:
    python3 regenerate_agent_tokens.py [--dry-run]
"""

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

import httpx

# Add the project root to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from ciris_manager.crypto import get_token_encryption


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class TokenRegenerator:
    """Regenerates service tokens for all CIRIS agents."""

    def __init__(
        self, metadata_path: Path = Path("/opt/ciris/agents/metadata.json"), dry_run: bool = False
    ):
        self.metadata_path = metadata_path
        self.dry_run = dry_run

    async def load_metadata(self) -> Dict:
        """Load agent metadata from file."""
        if not self.metadata_path.exists():
            raise FileNotFoundError(f"Metadata file not found: {self.metadata_path}")

        with open(self.metadata_path) as f:
            return json.load(f)

    async def save_metadata(self, metadata: Dict) -> None:
        """Save updated metadata to file."""
        if self.dry_run:
            logger.info("DRY RUN: Would save metadata to %s", self.metadata_path)
            return

        # Create backup
        backup_path = self.metadata_path.with_suffix(".json.backup")
        if self.metadata_path.exists():
            import shutil

            shutil.copy2(self.metadata_path, backup_path)
            logger.info("Created backup at %s", backup_path)

        # Write updated metadata
        with open(self.metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)
        logger.info("Updated metadata saved to %s", self.metadata_path)

    async def get_agent_service_token(self, agent_id: str, port: int) -> Optional[str]:
        """Get a fresh service token from an agent."""
        try:
            # Step 1: Login with default admin credentials
            login_url = f"http://localhost:{port}/v1/auth/login"
            login_data = {"username": "admin", "password": "ciris_admin_password"}

            async with httpx.AsyncClient(timeout=10.0) as client:
                logger.info("Logging into agent %s on port %d", agent_id, port)
                response = await client.post(login_url, json=login_data)

                if response.status_code != 200:
                    logger.error(
                        "Login failed for %s: %d %s", agent_id, response.status_code, response.text
                    )
                    return None

                login_result = response.json()
                access_token = login_result.get("access_token")
                if not access_token:
                    logger.error("No access token in login response for %s", agent_id)
                    return None

                # Step 2: Get service token (if endpoint exists)
                # Try common service token endpoints
                service_token_endpoints = [
                    "/v1/auth/service-token",
                    "/v1/system/service-token",
                    "/v1/admin/service-token",
                ]

                headers = {"Authorization": f"Bearer {access_token}"}

                for endpoint in service_token_endpoints:
                    try:
                        token_url = f"http://localhost:{port}{endpoint}"
                        logger.debug("Trying service token endpoint: %s", endpoint)
                        response = await client.get(token_url, headers=headers)

                        if response.status_code == 200:
                            token_data = response.json()
                            service_token = token_data.get("service_token") or token_data.get(
                                "token"
                            )
                            if service_token:
                                logger.info("Got service token for %s from %s", agent_id, endpoint)
                                return service_token
                        elif response.status_code == 404:
                            continue  # Try next endpoint
                        else:
                            logger.warning(
                                "Endpoint %s returned %d for %s",
                                endpoint,
                                response.status_code,
                                agent_id,
                            )
                    except Exception as e:
                        logger.debug("Endpoint %s failed for %s: %s", endpoint, agent_id, e)
                        continue

                # If no service token endpoint works, use the access token itself
                # This is a fallback for agents that don't have dedicated service token endpoints
                logger.info("Using access token as service token for %s", agent_id)
                return access_token

        except Exception as e:
            logger.error("Failed to get service token for %s: %s", agent_id, e)
            return None

    def encrypt_token(self, token: str) -> str:
        """Encrypt a service token."""
        token_encryption = get_token_encryption()
        return token_encryption.encrypt_token(token)

    async def regenerate_all_tokens(self) -> Tuple[int, int]:
        """Regenerate service tokens for all agents."""
        metadata = await self.load_metadata()
        agents = metadata.get("agents", {})

        if not agents:
            logger.warning("No agents found in metadata")
            return 0, 0

        success_count = 0
        total_count = len(agents)

        logger.info("Found %d agents to process", total_count)

        for agent_id, agent_data in agents.items():
            port = agent_data.get("port")
            if not port:
                logger.warning("Agent %s has no port, skipping", agent_id)
                continue

            logger.info("Processing agent %s on port %d", agent_id, port)

            # Get fresh service token
            service_token = await self.get_agent_service_token(agent_id, port)
            if not service_token:
                logger.error("Failed to get service token for %s", agent_id)
                continue

            # Encrypt the token
            try:
                encrypted_token = self.encrypt_token(service_token)

                # Update metadata
                agent_data["service_token"] = encrypted_token
                success_count += 1

                logger.info("Successfully updated token for %s", agent_id)

            except Exception as e:
                logger.error("Failed to encrypt token for %s: %s", agent_id, e)
                continue

        # Save updated metadata
        await self.save_metadata(metadata)

        return success_count, total_count


async def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Regenerate CIRIS agent service tokens")
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

    regenerator = TokenRegenerator(metadata_path=Path(args.metadata_path), dry_run=args.dry_run)

    try:
        success_count, total_count = await regenerator.regenerate_all_tokens()

        logger.info("Token regeneration complete:")
        logger.info("  Successful: %d/%d agents", success_count, total_count)

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
        logger.error("Token regeneration failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
