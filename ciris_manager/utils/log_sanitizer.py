"""
Log sanitization utilities to prevent log injection attacks.
"""

import re
from typing import Any


def sanitize_for_log(value: Any, max_length: int = 100) -> str:
    """
    Sanitize a value for safe logging.

    Removes control characters, newlines, and other potentially dangerous characters
    that could be used for log injection attacks.

    Args:
        value: The value to sanitize
        max_length: Maximum length of the output (default 100)

    Returns:
        Sanitized string safe for logging
    """
    # Convert to string
    str_value = str(value)

    # Remove control characters, newlines, carriage returns
    # Keep only printable ASCII and common unicode
    sanitized = re.sub(r"[\x00-\x1f\x7f-\x9f\r\n\t]", "", str_value)

    # Limit length to prevent log flooding
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length] + "..."

    return sanitized


def sanitize_agent_id(agent_id: str) -> str:
    """
    Sanitize an agent ID for logging.

    Agent IDs should only contain alphanumeric characters, hyphens, and underscores.

    Args:
        agent_id: The agent ID to sanitize

    Returns:
        Sanitized agent ID
    """
    # Only allow alphanumeric, hyphen, underscore
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "", agent_id)

    # Limit length
    return sanitized[:50]


def sanitize_email(email: str) -> str:
    """
    Sanitize an email address for logging.

    Args:
        email: The email to sanitize

    Returns:
        Sanitized email
    """
    # Basic email pattern validation and sanitization
    # Remove any control characters but keep @ and .
    sanitized = re.sub(r"[^\w@.\-+]", "", email)

    # Limit length
    return sanitized[:100]
