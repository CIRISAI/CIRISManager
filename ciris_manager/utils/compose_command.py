"""
Utility to detect and return the correct docker-compose command.

Supports both Docker Compose v1 (docker-compose) and v2 (docker compose).
"""

import shutil
import subprocess
from typing import List
import logging

logger = logging.getLogger(__name__)

# Cache the result to avoid repeated checks
_compose_command: List[str] | None = None


def get_compose_command() -> List[str]:
    """
    Get the correct docker-compose command for this system.

    Returns:
        List of command parts: ["docker-compose"] for v1, ["docker", "compose"] for v2

    Raises:
        RuntimeError: If neither docker-compose v1 nor v2 is available
    """
    global _compose_command

    if _compose_command is not None:
        return _compose_command

    # Try docker compose v2 first (more common in modern installs)
    try:
        result = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            _compose_command = ["docker", "compose"]
            logger.info("Using Docker Compose v2 (docker compose)")
            return _compose_command
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Fall back to docker-compose v1
    if shutil.which("docker-compose"):
        _compose_command = ["docker-compose"]
        logger.info("Using Docker Compose v1 (docker-compose)")
        return _compose_command

    raise RuntimeError(
        "Neither 'docker compose' (v2) nor 'docker-compose' (v1) is available. "
        "Please install Docker Compose."
    )


def compose_cmd(*args: str) -> List[str]:
    """
    Build a compose command with the given arguments.

    Example:
        compose_cmd("-f", "/path/to/compose.yml", "up", "-d")
        Returns: ["docker", "compose", "-f", "/path/to/compose.yml", "up", "-d"]
        Or:      ["docker-compose", "-f", "/path/to/compose.yml", "up", "-d"]

    Args:
        *args: Arguments to append to the compose command

    Returns:
        Complete command as a list
    """
    return get_compose_command() + list(args)
