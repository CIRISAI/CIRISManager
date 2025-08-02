"""
CIRISManager CLI entry point.
"""

import asyncio
import sys
import argparse
import logging

from ciris_manager.manager import CIRISManager
from ciris_manager.config.settings import CIRISManagerConfig


def setup_logging(verbose: bool = False) -> None:
    """Setup logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO

    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="CIRISManager - Agent lifecycle management service"
    )

    parser.add_argument(
        "--config",
        "-c",
        type=str,
        default="/etc/ciris-manager/config.yml",
        help="Path to configuration file",
    )

    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")

    parser.add_argument(
        "--generate-config",
        action="store_true",
        help="Generate default configuration file and exit",
    )

    parser.add_argument(
        "--validate-config", action="store_true", help="Validate configuration file and exit"
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    # Handle config generation
    if args.generate_config:
        config = CIRISManagerConfig()
        config.save(args.config)
        print(f"Generated default configuration at: {args.config}")
        return 0

    # Handle config validation
    if args.validate_config:
        try:
            config = CIRISManagerConfig.from_file(args.config)
            print(f"Configuration valid: {args.config}")
            return 0
        except Exception as e:
            print(f"Configuration invalid: {e}")
            return 1

    # Run the manager
    try:
        # Load configuration
        logger.info(f"Loading configuration from {args.config}")
        config = CIRISManagerConfig.from_file(args.config)
        logger.info("Configuration loaded successfully")

        # Create and run manager
        logger.info("Creating CIRISManager instance...")
        manager = CIRISManager(config)
        logger.info("CIRISManager created successfully, starting...")
        asyncio.run(manager.run())

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 0
    except PermissionError as e:
        logger.error(f"Permission error: {e}")
        logger.error(f"File/Directory: {getattr(e, 'filename', 'unknown')}")
        logger.error(f"Error number: {getattr(e, 'errno', 'unknown')}")
        logger.error("Full traceback:", exc_info=True)
        # Print to stderr for systemd journal
        print(f"Error running CIRISManager: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        # Print to stderr for systemd journal
        print(f"Error running CIRISManager: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
