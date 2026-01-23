"""
Utility to detect and return the correct docker-compose command.

Supports both Docker Compose v1 (docker-compose) and v2 (docker compose).
"""

import shutil
import subprocess
from typing import List, Optional
import logging

logger = logging.getLogger(__name__)

# Cache the result to avoid repeated checks
_compose_command: Optional[List[str]] = None


class ComposeNotFoundError(RuntimeError):
    """Raised when neither Docker Compose v1 nor v2 is available."""

    def __init__(self, v2_error: Optional[str] = None, v1_checked: bool = True):
        self.v2_error = v2_error
        self.v1_checked = v1_checked

        message = (
            "Docker Compose is not available on this system.\n"
            "\n"
            "Troubleshooting:\n"
            "  1. Check if Docker is installed: docker --version\n"
            "  2. Check Compose v2 (plugin): docker compose version\n"
            "  3. Check Compose v1 (standalone): docker-compose --version\n"
            "\n"
            "Installation options:\n"
            "  - Docker Desktop includes Compose v2 by default\n"
            "  - Linux: apt install docker-compose-plugin (v2) or docker-compose (v1)\n"
        )

        if v2_error:
            message += f"\nDocker Compose v2 check failed: {v2_error}"

        super().__init__(message)


def reset_compose_command_cache() -> None:
    """
    Reset the cached compose command.

    Useful for testing or when the system configuration changes.
    """
    global _compose_command
    _compose_command = None


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

    v2_error: Optional[str] = None

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
        else:
            v2_error = f"Command returned exit code {result.returncode}"
            if result.stderr:
                v2_error += f": {result.stderr.decode().strip()}"
    except subprocess.TimeoutExpired:
        v2_error = "Command timed out after 5 seconds"
    except FileNotFoundError:
        v2_error = "Docker binary not found in PATH"

    # Fall back to docker-compose v1
    if shutil.which("docker-compose"):
        _compose_command = ["docker-compose"]
        logger.info("Using Docker Compose v1 (docker-compose)")
        return _compose_command

    raise ComposeNotFoundError(v2_error=v2_error)


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
