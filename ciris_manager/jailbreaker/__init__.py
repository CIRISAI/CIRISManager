"""
Jailbreaker module for CIRIS Manager.

Provides Discord OAuth-based agent reset functionality for users with jailbreak permissions.
"""

from .service import JailbreakerService
from .models import JailbreakerConfig, ResetResult, ResetStatus
from .routes import create_jailbreaker_routes

__all__ = [
    "JailbreakerService",
    "JailbreakerConfig", 
    "ResetResult",
    "ResetStatus",
    "create_jailbreaker_routes",
]