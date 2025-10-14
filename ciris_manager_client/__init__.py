"""
CIRIS CLI Package.

This package provides a comprehensive command-line interface for managing
CIRIS agents and infrastructure.
"""

from ciris_manager_client.main import (
    main,
    CommandContext,
    CLIError,
    CLIAuthenticationError,
    CLIAPIError,
    ValidationError,
    NotFoundError,
    EXIT_SUCCESS,
    EXIT_ERROR,
    EXIT_INVALID_ARGS,
    EXIT_AUTH_ERROR,
    EXIT_API_ERROR,
    EXIT_VALIDATION_ERROR,
    EXIT_NOT_FOUND,
)

__all__ = [
    # Main entry point
    "main",
    # Context
    "CommandContext",
    # Error classes
    "CLIError",
    "CLIAuthenticationError",
    "CLIAPIError",
    "ValidationError",
    "NotFoundError",
    # Exit codes
    "EXIT_SUCCESS",
    "EXIT_ERROR",
    "EXIT_INVALID_ARGS",
    "EXIT_AUTH_ERROR",
    "EXIT_API_ERROR",
    "EXIT_VALIDATION_ERROR",
    "EXIT_NOT_FOUND",
]
