#!/usr/bin/env python3
"""
Grace command-line interface for CIRISManager.
Simple, direct, helpful.
"""

import sys

from .main import Grace


def main() -> None:
    """Main entry point."""
    grace = Grace()

    # Default command
    if len(sys.argv) < 2:
        command = "status"
    else:
        command = sys.argv[1]

    # Command mapping
    commands = {
        "status": grace.status,
        "ci": lambda: grace.ci(sys.argv[2] if len(sys.argv) > 2 else None),
        "quality": grace.quality,
        "sonar": grace.quality,  # Alias for quality
        "precommit": lambda: grace.precommit(autofix="--fix" in sys.argv),
        "fix": grace.fix,
        "deploy": grace.deploy_status,
        "test": grace.test,
        # Short aliases
        "s": grace.status,
        "c": lambda: grace.ci(sys.argv[2] if len(sys.argv) > 2 else None),
        "q": grace.quality,
        "pc": lambda: grace.precommit(autofix="--fix" in sys.argv),
        "f": grace.fix,
        "d": grace.deploy_status,
        "t": grace.test,
    }

    if command in commands:
        print(commands[command]())
    elif command in ["help", "-h", "--help"]:
        print("Grace - CIRISManager development companion\n")
        print("Commands:")
        print("  status     - Current project and system health")
        print("  ci         - Check CI/CD status")
        print("             Usage: grace ci [prs|builds|analyze]")
        print("             Default: current branch + PR summary")
        print("  quality    - Check SonarCloud quality gate")
        print("  precommit  - Check pre-commit issues (--fix to auto-fix)")
        print("  fix        - Auto-fix pre-commit issues")
        print("  deploy     - Check deployment status")
        print("  test       - Run tests with coverage")
        print("\nShort forms: s, c, q, pc, f, d, t")
    else:
        print(f"Unknown command: {command}")
        print("Try 'grace help' for available commands")


if __name__ == "__main__":
    main()
