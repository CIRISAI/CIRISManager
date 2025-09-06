#!/usr/bin/env python3
"""
Fix agent service tokens by reading them from container environment variables.
"""

import json
import logging
import sys
from pathlib import Path

# Add the project root to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from ciris_manager.crypto import get_token_encryption

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def fix_agent_tokens(
    metadata_path: Path = Path("/opt/ciris/agents/metadata.json"), dry_run: bool = False
):
    """Fix tokens by reading from container environment variables."""

    # Service tokens extracted from container environments
    agent_tokens = {
        "datum": "21131fdf6cd5a44044fcec261aba2c596aa8fad1a5b9725a41cacf6b33419023",
        "echo-core-jm2jy2": "Y5Qk8d_r7ft3UMM_pc5leGxkz9dTwalBlXZYzS0Y4d8",
        "echo-speculative-4fc6ru": "fqE_hW_PeaowhIVd4Rxy4P-n_0gO0YCEv1aEnuv38pA",
        "sage-2wnuc8": "FTlGCN5yJ2Vv4vCDu-XqBSlRJcu3H--RBrnBDoWbrRA",
        "scout-u7e9s3": "E0yMcJ3hew7q_nThOJv_yggqRYGitr14Qidv_hNlD0k",
    }

    with open(metadata_path) as f:
        metadata = json.load(f)

    # Get current correct encryption instance
    current_encryption = get_token_encryption()

    success_count = 0

    for agent_id, plain_token in agent_tokens.items():
        if agent_id not in metadata["agents"]:
            logger.warning(f"Agent {agent_id} not found in metadata")
            continue

        logger.info(f"Processing {agent_id}...")

        try:
            # Encrypt the token with current correct key
            encrypted_token = current_encryption.encrypt_token(plain_token)

            if not dry_run:
                metadata["agents"][agent_id]["service_token"] = encrypted_token

            logger.info(f"Successfully updated token for {agent_id}")
            success_count += 1

        except Exception as e:
            logger.error(f"Failed to encrypt token for {agent_id}: {e}")
            continue

    if success_count > 0 and not dry_run:
        # Create backup
        backup_path = metadata_path.with_suffix(".json.backup-env-fix")
        import shutil

        shutil.copy2(metadata_path, backup_path)
        logger.info(f"Created backup at {backup_path}")

        # Save updated metadata
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)
        logger.info(f"Updated metadata saved to {metadata_path}")

    logger.info(f"Token fix complete: {success_count}/{len(agent_tokens)} agents fixed")
    return success_count, len(agent_tokens)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fix service tokens from environment variables")
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
