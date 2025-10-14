"""
Utility functions and classes for the CIRIS CLI tool.

This module provides common utilities like progress spinners, confirmation prompts,
config file handling, and SSH client management.
"""

import sys
import time
import json
import yaml
import threading
from typing import Optional, Dict, Any, Union, cast
from pathlib import Path
from contextlib import contextmanager

# Optional imports
try:
    import paramiko

    PARAMIKO_AVAILABLE = True
except ImportError:
    PARAMIKO_AVAILABLE = False


class ProgressSpinner:
    """
    Simple progress spinner for long-running operations.

    Shows a rotating spinner animation in the terminal.
    """

    def __init__(self, message: str = "Working...") -> None:
        """
        Initialize the progress spinner.

        Args:
            message: Message to display alongside the spinner
        """
        self.message = message
        self.spinning = False
        self.thread: Optional[threading.Thread] = None
        self.frames = ["-", "\\", "|", "/"]
        self.current_frame = 0

    def _spin(self) -> None:
        """Internal method to animate the spinner."""
        while self.spinning:
            frame = self.frames[self.current_frame % len(self.frames)]
            sys.stdout.write(f"\r{frame} {self.message}")
            sys.stdout.flush()
            self.current_frame += 1
            time.sleep(0.1)
        # Clear the line when done
        sys.stdout.write("\r" + " " * (len(self.message) + 2) + "\r")
        sys.stdout.flush()

    def start(self, message: Optional[str] = None) -> None:
        """
        Start showing the spinner.

        Args:
            message: Optional message to display (overrides constructor message)
        """
        if message:
            self.message = message

        self.spinning = True
        self.thread = threading.Thread(target=self._spin, daemon=True)
        self.thread.start()

    def update(self, message: str) -> None:
        """
        Update the spinner message.

        Args:
            message: New message to display
        """
        self.message = message

    def stop(self, message: Optional[str] = None) -> None:
        """
        Stop the spinner and optionally display a final message.

        Args:
            message: Optional final message to display
        """
        self.spinning = False
        if self.thread:
            self.thread.join(timeout=1.0)

        if message:
            print(message)

    def __enter__(self) -> "ProgressSpinner":
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:  # type: ignore
        """Context manager exit."""
        self.stop()


def confirm_action(prompt: str, default: bool = False, force: bool = False) -> bool:
    """
    Prompt the user for confirmation.

    Args:
        prompt: The confirmation prompt to display
        default: Default response if user just presses enter
        force: If True, skip confirmation and return True

    Returns:
        True if user confirmed, False otherwise
    """
    if force:
        return True

    # Format prompt with default indicator
    default_indicator = "[Y/n]" if default else "[y/N]"
    full_prompt = f"{prompt} {default_indicator}: "

    try:
        response = input(full_prompt).strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return False

    if not response:
        return default

    return response in ("y", "yes")


def load_config_file(file_path: Union[str, Path]) -> Dict[str, Any]:
    """
    Load configuration from a JSON or YAML file.

    Args:
        file_path: Path to the configuration file

    Returns:
        Dictionary containing the configuration

    Raises:
        FileNotFoundError: If the file doesn't exist
        ValueError: If the file format is not supported or invalid
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {file_path}")

    # Determine format from extension
    suffix = path.suffix.lower()

    try:
        with open(path, "r") as f:
            if suffix == ".json":
                return cast(Dict[str, Any], json.load(f))
            elif suffix in (".yaml", ".yml"):
                return cast(Dict[str, Any], yaml.safe_load(f))
            else:
                # Try to detect format from content
                content = f.read()
                f.seek(0)

                # Try JSON first
                try:
                    return cast(Dict[str, Any], json.loads(content))
                except json.JSONDecodeError:
                    pass

                # Try YAML
                try:
                    return cast(Dict[str, Any], yaml.safe_load(content))
                except yaml.YAMLError:
                    pass

                raise ValueError(
                    f"Unable to determine file format for {file_path}. "
                    "Supported formats: .json, .yaml, .yml"
                )
    except (json.JSONDecodeError, yaml.YAMLError) as e:
        raise ValueError(f"Failed to parse configuration file: {e}")


def save_config_file(
    data: Dict[str, Any], file_path: Union[str, Path], format: Optional[str] = None
) -> None:
    """
    Save configuration to a JSON or YAML file.

    Args:
        data: Dictionary containing the configuration
        file_path: Path to save the configuration file
        format: Format to use ('json' or 'yaml'). If None, infer from extension

    Raises:
        ValueError: If the format is not supported
    """
    path = Path(file_path)

    # Create parent directories if they don't exist
    path.parent.mkdir(parents=True, exist_ok=True)

    # Determine format
    if format:
        format = format.lower()
    else:
        suffix = path.suffix.lower()
        if suffix == ".json":
            format = "json"
        elif suffix in (".yaml", ".yml"):
            format = "yaml"
        else:
            # Default to JSON
            format = "json"

    # Save file
    with open(path, "w") as f:
        if format == "json":
            json.dump(data, f, indent=2, default=str)
        elif format == "yaml":
            yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
        else:
            raise ValueError(f"Unsupported format: {format}. Use 'json' or 'yaml'.")


def get_ssh_client(
    hostname: str,
    username: str = "root",
    key_path: Optional[Union[str, Path]] = None,
    password: Optional[str] = None,
    port: int = 22,
) -> Optional["paramiko.SSHClient"]:
    """
    Create and connect an SSH client for remote server inspection.

    Args:
        hostname: Hostname or IP address of the server
        username: SSH username (default: root)
        key_path: Path to SSH private key file
        password: SSH password (if not using key auth)
        port: SSH port (default: 22)

    Returns:
        Connected SSHClient instance, or None if paramiko is not available

    Raises:
        ImportError: If paramiko is not installed
        Exception: If SSH connection fails
    """
    if not PARAMIKO_AVAILABLE:
        raise ImportError("paramiko is not installed. Install it with: pip install paramiko")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        if key_path:
            # Use key-based authentication
            key_path = Path(key_path).expanduser()
            client.connect(hostname, port=port, username=username, key_filename=str(key_path))
        elif password:
            # Use password authentication
            client.connect(hostname, port=port, username=username, password=password)
        else:
            # Try default key locations
            client.connect(hostname, port=port, username=username)

        return client
    except Exception as e:
        client.close()
        raise Exception(f"Failed to connect to {hostname}: {e}")


@contextmanager
def ssh_connection(
    hostname: str,
    username: str = "root",
    key_path: Optional[Union[str, Path]] = None,
    password: Optional[str] = None,
    port: int = 22,
):  # type: ignore
    """
    Context manager for SSH connections.

    Args:
        hostname: Hostname or IP address of the server
        username: SSH username (default: root)
        key_path: Path to SSH private key file
        password: SSH password (if not using key auth)
        port: SSH port (default: 22)

    Yields:
        Connected SSHClient instance

    Example:
        with ssh_connection("server.example.com", key_path="~/.ssh/id_rsa") as ssh:
            stdin, stdout, stderr = ssh.exec_command("ls -la")
            print(stdout.read().decode())
    """
    client = get_ssh_client(hostname, username, key_path, password, port)
    try:
        yield client
    finally:
        if client:
            client.close()


def handle_cli_error(error: Exception) -> int:
    """
    Handle CLI errors and return appropriate exit code.

    Args:
        error: The exception that occurred

    Returns:
        Appropriate exit code
    """
    from .protocols import (
        CLIError,
        AuthenticationError,
        APIError,
        ValidationError,
        NotFoundError,
        EXIT_ERROR,
    )

    if isinstance(error, AuthenticationError):
        print(f"Authentication error: {error}", file=sys.stderr)
        return error.exit_code
    elif isinstance(error, APIError):
        print(f"API error: {error}", file=sys.stderr)
        if hasattr(error, "status_code") and error.status_code:
            print(f"Status code: {error.status_code}", file=sys.stderr)
        return error.exit_code
    elif isinstance(error, ValidationError):
        print(f"Validation error: {error}", file=sys.stderr)
        return error.exit_code
    elif isinstance(error, NotFoundError):
        print(f"Not found: {error}", file=sys.stderr)
        return error.exit_code
    elif isinstance(error, CLIError):
        print(f"Error: {error}", file=sys.stderr)
        return error.exit_code
    else:
        print(f"Unexpected error: {error}", file=sys.stderr)
        return EXIT_ERROR


def truncate_string(text: str, max_length: int = 50, suffix: str = "...") -> str:
    """
    Truncate a string to a maximum length.

    Args:
        text: String to truncate
        max_length: Maximum length (including suffix)
        suffix: Suffix to add when truncating

    Returns:
        Truncated string
    """
    if len(text) <= max_length:
        return text

    return text[: max_length - len(suffix)] + suffix
