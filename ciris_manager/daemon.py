"""
CIRISManager daemon entry point.

This module provides the command-line entry point for the CIRISManager daemon.
It handles configuration loading and starts the main manager service.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from ciris_manager.manager import main as manager_main


def main() -> None:
    """
    Main entry point for the CIRISManager daemon.

    This function:
    1. Parses command-line arguments (--config flag)
    2. Validates configuration file exists
    3. Starts the async manager main loop
    """
    parser = argparse.ArgumentParser(
        description="CIRIS Manager - Agent lifecycle management daemon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start the daemon with a config file
  ciris-manager --config /etc/ciris-manager/config.yml

  # Generate a default configuration
  ciris-manager --generate-config --config /etc/ciris-manager/config.yml
        """,
    )

    parser.add_argument(
        "--config",
        type=str,
        default="/etc/ciris-manager/config.yml",
        help="Path to configuration file (default: /etc/ciris-manager/config.yml)",
    )

    parser.add_argument(
        "--generate-config",
        action="store_true",
        help="Generate a default configuration file and exit",
    )

    args = parser.parse_args()

    # Handle config generation
    if args.generate_config:
        from ciris_manager.config.manager_config import generate_default_config

        try:
            generate_default_config(args.config)
            print(f"Default configuration generated at: {args.config}")
            sys.exit(0)
        except Exception as e:
            print(f"Error generating config: {e}", file=sys.stderr)
            sys.exit(1)

    # Validate config file exists
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Error: Configuration file not found: {args.config}", file=sys.stderr)
        print(
            f"Generate one with: ciris-manager --generate-config --config {args.config}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Run the manager
    try:
        asyncio.run(manager_main())
    except KeyboardInterrupt:
        print("\nShutting down CIRISManager...")
        sys.exit(0)
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
