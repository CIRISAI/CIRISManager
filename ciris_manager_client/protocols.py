"""
Protocol definitions for the CIRIS CLI tool.

This module defines the core protocols and types used across all CLI commands.
"""

from dataclasses import dataclass
from typing import Protocol, Any, List, Dict, Optional
from argparse import Namespace


# Exit code constants
EXIT_SUCCESS = 0  # Command succeeded
EXIT_ERROR = 1  # General error
EXIT_INVALID_ARGS = 2  # Invalid arguments
EXIT_AUTH_ERROR = 3  # Authentication error
EXIT_API_ERROR = 4  # API error
EXIT_VALIDATION_ERROR = 5  # Validation error
EXIT_NOT_FOUND = 6  # Resource not found


@dataclass
class CommandContext:
    """Context passed to all commands with common resources."""

    client: Any  # CIRISManagerClient
    """API client instance"""

    output_format: str
    """Output format: 'table', 'json', or 'yaml'"""

    quiet: bool
    """Suppress non-essential output"""

    verbose: bool
    """Enable verbose logging"""


class OutputFormatter(Protocol):
    """Protocol for output formatting."""

    def format_table(self, data: List[Dict[str, Any]], columns: Optional[List[str]] = None) -> str:
        """Format data as a table."""
        ...

    def format_json(self, data: Any) -> str:
        """Format data as JSON."""
        ...

    def format_yaml(self, data: Any) -> str:
        """Format data as YAML."""
        ...

    def format_output(self, data: Any, format: str, columns: Optional[List[str]] = None) -> str:
        """Format output based on format string."""
        ...


class CommandHandler(Protocol):
    """Protocol for command handlers."""

    def execute(self, ctx: CommandContext, args: Namespace) -> int:
        """
        Execute the command.

        Args:
            ctx: Command context with client and settings
            args: Parsed command-line arguments

        Returns:
            Exit code (0 for success, non-zero for error)
        """
        ...


# Exception Hierarchy


class CLIError(Exception):
    """Base class for CLI errors."""

    exit_code: int = EXIT_ERROR

    def __init__(self, message: str, exit_code: Optional[int] = None) -> None:
        super().__init__(message)
        if exit_code is not None:
            self.exit_code = exit_code


class AuthenticationError(CLIError):
    """Authentication failed."""

    exit_code: int = EXIT_AUTH_ERROR


class APIError(CLIError):
    """API request failed."""

    exit_code: int = EXIT_API_ERROR

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class ValidationError(CLIError):
    """Validation failed."""

    exit_code: int = EXIT_VALIDATION_ERROR


class NotFoundError(CLIError):
    """Resource not found."""

    exit_code: int = EXIT_NOT_FOUND
