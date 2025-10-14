"""
CIRIS CLI commands module.

This module provides all command implementations for the CIRIS CLI tool.
Each command module follows the CommandHandler protocol and provides
static methods for command execution.
"""

from ciris_manager.cli.commands.agent import AgentCommands
from ciris_manager.cli.commands.inspect import InspectCommands

__all__ = [
    "AgentCommands",
    "InspectCommands",
]
