#!/usr/bin/env python3
"""
Fix broken service tokens that were encrypted with wrong keys.

This script attempts to decrypt existing tokens with various possible keys
and re-encrypt them with the current correct key.
"""

import json
import logging
import sys
from pathlib import Path
from typing import Optional

# Add the project root to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from ciris_manager.crypto import get_token_encryption
from cryptography.fernet import Fernet
import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def try_decrypt_with_old_key(encrypted_token: str) -> Optional[str]:
    """Try to decrypt token with various possible old keys."""

    # Possible old scenarios when encryption key was missing
    old_key_scenarios = [
        # Scenario 1: Empty or minimal salt with default password
        ("default_password", "minimal_salt_123"),
        ("ciris_admin_password", "ciris_salt"),
        ("", "ciris_production_salt_2024"),  # Empty password with current salt
    ]

    for password, salt in old_key_scenarios:
        if not password:
            continue

        try:
            # Generate key the same way the crypto module does
            if len(salt) < 16:
                continue  # Skip invalid salts

            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt.encode(),
                iterations=100000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
            cipher = Fernet(key)

            # Try to decrypt
            decrypted = cipher.decrypt(encrypted_token.encode()).decode()
            logger.info(f"Successfully decrypted token with password='{password}', salt='{salt}'")
            return decrypted

        except Exception as e:
            logger.debug(f"Failed with password='{password}', salt='{salt}': {e}")
            continue

    return None


def fix_agent_tokens(
    metadata_path: Path = Path("/opt/ciris/agents/metadata.json"), dry_run: bool = False
):
    """Fix broken tokens for all agents except echo-nemesis."""

    if not metadata_path.exists():
        raise FileNotFoundError(f"Metadata file not found: {metadata_path}")

    with open(metadata_path) as f:
        metadata = json.load(f)

    # Get current correct encryption instance
    current_encryption = get_token_encryption()

    agents = metadata.get("agents", {})
    agents_to_fix = [aid for aid in agents.keys() if aid != "echo-nemesis-v2tyey"]

    logger.info(f"Found {len(agents_to_fix)} agents to fix: {agents_to_fix}")

    success_count = 0

    for agent_id in agents_to_fix:
        agent_data = agents[agent_id]
        encrypted_token = agent_data.get("service_token")

        if not encrypted_token:
            logger.warning(f"No service token found for {agent_id}")
            continue

        logger.info(f"Processing {agent_id}...")

        # Try to decrypt with old keys
        decrypted_token = try_decrypt_with_old_key(encrypted_token)
        if not decrypted_token:
            logger.error(f"Could not decrypt token for {agent_id} with any known key")
            continue

        # Re-encrypt with current correct key
        try:
            new_encrypted_token = current_encryption.encrypt_token(decrypted_token)

            if not dry_run:
                agent_data["service_token"] = new_encrypted_token

            logger.info(f"Successfully re-encrypted token for {agent_id}")
            success_count += 1

        except Exception as e:
            logger.error(f"Failed to re-encrypt token for {agent_id}: {e}")
            continue

    if success_count > 0 and not dry_run:
        # Create backup
        backup_path = metadata_path.with_suffix(".json.backup-token-fix")
        import shutil

        shutil.copy2(metadata_path, backup_path)
        logger.info(f"Created backup at {backup_path}")

        # Save updated metadata
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)
        logger.info(f"Updated metadata saved to {metadata_path}")

    logger.info(f"Token fix complete: {success_count}/{len(agents_to_fix)} agents fixed")
    return success_count, len(agents_to_fix)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fix broken service tokens")
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

    try:
        success_count, total_count = fix_agent_tokens(
            metadata_path=Path(args.metadata_path), dry_run=args.dry_run
        )

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
        logger.error(f"Token fix failed: {e}")
        sys.exit(1)
